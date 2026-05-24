from __future__ import annotations

import email.utils
import html
import hashlib
import json
import logging
import math
import os
import random
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

DEFAULT_ENDPOINT = "https://api.sam.gov/opportunities/v2/search"
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
DEFAULT_MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
DEFAULT_BASE_BACKOFF_SECONDS = float(os.getenv("BASE_BACKOFF_SECONDS", "1.0"))
DEFAULT_MAX_BACKOFF_SECONDS = float(os.getenv("MAX_BACKOFF_SECONDS", "60.0"))
DEFAULT_PAGE_LIMIT = min(max(int(os.getenv("PAGE_LIMIT", "1000")), 1), 1000)
DEFAULT_ENRICHMENT_BATCH_LIMIT = min(max(int(os.getenv("SAM_ENRICHMENT_BATCH_LIMIT", "10")), 1), 100)
DEFAULT_DOCUMENT_FETCH_TIMEOUT_SECONDS = float(os.getenv("SAM_DOCUMENT_FETCH_TIMEOUT_SECONDS", "4"))
DEFAULT_DOCUMENT_FETCH_MAX_BYTES = min(max(int(os.getenv("SAM_DOCUMENT_FETCH_MAX_BYTES", "200000")), 10_000), 1_000_000)
DEFAULT_DOCUMENTS_PER_OPPORTUNITY = min(max(int(os.getenv("SAM_DOCUMENTS_PER_OPPORTUNITY", "1")), 0), 5)
DEFAULT_ENRICHMENT_MIN_TEXT_CHARS = min(max(int(os.getenv("SAM_ENRICHMENT_MIN_TEXT_CHARS", "80")), 20), 1000)
DEFAULT_ENRICHMENT_MAX_TEXT_CHARS = min(max(int(os.getenv("SAM_ENRICHMENT_MAX_TEXT_CHARS", "12000")), 1000), 60_000)
VECTOR_DIMENSION = int(os.getenv("VECTOR_DIMENSION", "1536"))
PREFER_IPV6_EGRESS = os.getenv("PREFER_IPV6_EGRESS", "true").strip().lower() in {"1", "true", "yes", "on"}
TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}
DIRECT_FILTER_KEYS = {
    "ptype",
    "solnum",
    "noticeid",
    "title",
    "state",
    "zip",
    "status",
    "organizationCode",
    "organizationName",
    "typeOfSetAside",
    "typeOfSetAsideDescription",
    "ncode",
    "ccode",
}
DATE_FILTER_KEYS = {"rdlfrom", "rdlto"}
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_:+.-]{1,80}")
_ALLOWED_DOCUMENT_HOSTS = ("sam.gov", "gsa.gov")


def _install_ipv6_preference() -> None:
    if not PREFER_IPV6_EGRESS or getattr(socket.getaddrinfo, "_captureos_ipv6_preferred", False):
        return

    def prefer_ipv6_getaddrinfo(*args: Any, **kwargs: Any) -> List[Any]:
        results = list(_ORIGINAL_GETADDRINFO(*args, **kwargs))
        return sorted(results, key=lambda item: 0 if item[0] == socket.AF_INET6 else 1)

    prefer_ipv6_getaddrinfo._captureos_ipv6_preferred = True  # type: ignore[attr-defined]
    socket.getaddrinfo = prefer_ipv6_getaddrinfo


_install_ipv6_preference()


class IngestError(Exception):
    """Base class for ingestion failures that should be visible to SQS retry/DLQ handling."""


class HttpStatusError(IngestError):
    def __init__(self, status_code: int, headers: Mapping[str, str], body: str) -> None:
        super().__init__(f"SAM.gov request failed with HTTP {status_code}: {body[:500]}")
        self.status_code = status_code
        self.headers = headers
        self.body = body


class RetryBudgetExceeded(IngestError):
    """Raised when Lambda cannot complete a throttled request within its retry budget."""


def lambda_handler(event: Mapping[str, Any], context: Any) -> Dict[str, Any]:
    if event.get("mode") == "upsert_sam_records":
        return upsert_sam_records_event(event)

    if event.get("mode") == "enrich_sam_opportunity_embeddings":
        return enrich_sam_opportunity_embeddings_event(event, context=context)

    if "Records" not in event:
        return ingest_direct_event(event, context=context)

    failures: List[Dict[str, str]] = []
    processed = 0

    for record in event.get("Records", []):
        message_id = str(record.get("messageId", "unknown-message"))
        try:
            summary = ingest_sqs_record(record, context=context)
            processed += 1
            LOGGER.info("Processed SAM.gov ingest message %s: %s", message_id, summary)
        except Exception:
            LOGGER.exception("Failed SAM.gov ingest message %s", message_id)
            failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failures, "processedRecords": processed}


def upsert_sam_records_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    records = event.get("records") or []
    if not isinstance(records, list):
        raise IngestError("records must be a list of raw SAM.gov opportunity records.")

    ingest_window = event.get("ingest_window") if isinstance(event.get("ingest_window"), Mapping) else {}
    source_received_at = datetime.now(timezone.utc).isoformat()
    payloads = [normalize_opportunity(item, ingest_window, source_received_at) for item in records]
    written_count = upsert_opportunities_to_database(payloads)
    update_data_freshness(
        source_system="SAM.gov",
        dataset_name="Opportunities",
        source_mode=str(event.get("source_mode") or "live_api"),
        record_count=int(event.get("total_records") or written_count),
        source_url=DEFAULT_ENDPOINT,
    )
    return {"normalizedRecords": len(payloads), "writtenRecords": written_count}


def enrich_sam_opportunity_embeddings_event(event: Mapping[str, Any], context: Any = None) -> Dict[str, Any]:
    limit = min(max(int(event.get("limit") or DEFAULT_ENRICHMENT_BATCH_LIMIT), 1), 100)
    force = _truthy(event.get("force", False))
    fetch_documents = _truthy(event.get("fetch_documents", os.getenv("SAM_ENRICHMENT_FETCH_DOCUMENTS", "true")))
    embedding_provider = str(event.get("embedding_provider") or os.getenv("SAM_EMBEDDING_PROVIDER", "deterministic")).strip().lower()
    document_limit = min(max(int(event.get("documents_per_opportunity") or DEFAULT_DOCUMENTS_PER_OPPORTUNITY), 0), 5)
    notice_ids = _string_list(event.get("notice_ids") or event.get("notice_id"))

    rows = fetch_sam_enrichment_candidates(limit=limit, notice_ids=notice_ids, force=force)
    api_key = _resolve_sam_api_key() if fetch_documents else None
    results: List[Dict[str, Any]] = []

    for row in rows:
        if not _lambda_time_available(context, reserve_seconds=3.0):
            results.append({"status": "deferred", "reason": "lambda_time_remaining"})
            break
        try:
            results.append(
                enrich_sam_opportunity_row(
                    row,
                    embedding_provider=embedding_provider,
                    fetch_documents=fetch_documents,
                    api_key=api_key,
                    document_limit=document_limit,
                )
            )
        except Exception as exc:
            LOGGER.exception("Failed SAM.gov enrichment for notice %s", row.get("notice_id"))
            results.append({"notice_id": row.get("notice_id"), "status": "failed", "error": str(exc)[:300]})

    enriched = sum(1 for item in results if item.get("status") == "enriched")
    skipped = sum(1 for item in results if item.get("status") == "skipped")
    failed = sum(1 for item in results if item.get("status") == "failed")
    deferred = sum(1 for item in results if item.get("status") == "deferred")

    if rows:
        update_data_freshness(
            source_system="SAM.gov",
            dataset_name="Opportunity Document Enrichment",
            source_mode="live_api",
            record_count=count_enriched_sam_opportunities(),
            source_url="https://sam.gov",
            freshness_sla_hours=24,
            notes=f"Document extraction and {embedding_provider} embeddings completed for {enriched} opportunities.",
        )

    return {
        "candidateRecords": len(rows),
        "enrichedRecords": enriched,
        "skippedRecords": skipped,
        "failedRecords": failed,
        "deferredRecords": deferred,
        "embeddingProvider": embedding_provider,
        "fetchedDocuments": fetch_documents,
        "results": results[:25],
    }


def ingest_direct_event(event: Mapping[str, Any], context: Any = None) -> Dict[str, Any]:
    body = _scheduled_body(event)
    output_queue_url = body.get("output_queue_url") or os.getenv("UPSERT_QUEUE_URL")
    upsert_lambda_name = body.get("upsert_lambda_name") or os.getenv("UPSERT_LAMBDA_NAME")
    direct_db_upsert = _truthy(body.get("direct_db_upsert", os.getenv("DIRECT_DB_UPSERT", "true")))
    if not output_queue_url and not upsert_lambda_name and not direct_db_upsert and not body.get("dry_run"):
        raise IngestError("Set DIRECT_DB_UPSERT=true, UPSERT_LAMBDA_NAME, UPSERT_QUEUE_URL, or dry_run=true for direct ingestion.")

    record = {
        "messageId": str(event.get("id") or f"direct-{int(time.time())}"),
        "body": body,
        "attributes": {"MessageGroupId": "sam-opportunities-scheduled"},
    }

    run_id = None
    if direct_db_upsert:
        LOGGER.info("Starting SAM.gov direct DB ingest run.")
        run_id = _start_ingest_run(body)

    try:
        if direct_db_upsert:
            summary = ingest_direct_to_database(record, context=context)
        elif upsert_lambda_name:
            summary = ingest_direct_to_upsert_lambda(record, str(upsert_lambda_name), context=context)
        else:
            summary = ingest_sqs_record(record, context=context)
        if run_id:
            _finish_ingest_run(run_id, "succeeded", summary.get("normalizedRecords", 0), summary.get("writtenRecords", 0))
        return summary
    except Exception as exc:
        if run_id:
            _finish_ingest_run(run_id, "failed", 0, 0, str(exc))
        raise


def ingest_direct_to_database(record: Mapping[str, Any], context: Any = None) -> Dict[str, Any]:
    body = _json_object(record.get("body"))
    config = _build_request_config(body)
    dry_run = bool(body.get("dry_run", False))

    normalized_count = 0
    written_count = 0
    dry_run_records: List[Dict[str, Any]] = []
    for page_response, records in iter_opportunity_pages(config, str(record.get("messageId", "direct")), context):
        source_received_at = datetime.now(timezone.utc).isoformat()
        payloads = [normalize_opportunity(item, config["ingest_window"], source_received_at) for item in records]
        normalized_count += len(payloads)
        if dry_run:
            remaining = max(0, int(body.get("dry_run_max_records", 25)) - len(dry_run_records))
            dry_run_records.extend(payloads[:remaining])
        else:
            written_count += upsert_opportunities_to_database(payloads)
        LOGGER.info(
            "Fetched SAM.gov direct page offset=%s limit=%s totalRecords=%s pageRecords=%s",
            page_response.get("offset"),
            page_response.get("limit"),
            page_response.get("totalRecords"),
            len(records),
        )

    if not dry_run:
        update_data_freshness(
            source_system="SAM.gov",
            dataset_name="Opportunities",
            source_mode="live_api",
            record_count=written_count,
            source_url=config["endpoint"],
        )

    summary: Dict[str, Any] = {
        "normalizedRecords": normalized_count,
        "writtenRecords": written_count,
        "postedFrom": config["params"]["postedFrom"],
        "postedTo": config["params"]["postedTo"],
        "directDbUpsert": not dry_run,
    }
    if dry_run:
        summary["records"] = dry_run_records
    return summary


def ingest_direct_to_upsert_lambda(record: Mapping[str, Any], upsert_lambda_name: str, context: Any = None) -> Dict[str, Any]:
    body = _json_object(record.get("body"))
    config = _build_request_config(body)
    dry_run = bool(body.get("dry_run", False))
    upsert_chunk_size = min(max(int(body.get("upsert_chunk_size", 100)), 1), 250)

    normalized_count = 0
    written_count = 0
    dry_run_records: List[Dict[str, Any]] = []
    for page_response, records in iter_opportunity_pages(config, str(record.get("messageId", "direct")), context):
        normalized_count += len(records)
        if dry_run:
            remaining = max(0, int(body.get("dry_run_max_records", 25)) - len(dry_run_records))
            dry_run_records.extend(records[:remaining])
        else:
            for chunk in _chunk_by_count(records, upsert_chunk_size):
                written_count += invoke_upsert_lambda(
                    upsert_lambda_name,
                    chunk,
                    total_records=int(page_response.get("totalRecords") or len(records)),
                    ingest_window=config["ingest_window"],
                )
        LOGGER.info(
            "Fetched SAM.gov bridge page offset=%s limit=%s totalRecords=%s pageRecords=%s",
            page_response.get("offset"),
            page_response.get("limit"),
            page_response.get("totalRecords"),
            len(records),
        )

    summary: Dict[str, Any] = {
        "normalizedRecords": normalized_count,
        "writtenRecords": written_count,
        "postedFrom": config["params"]["postedFrom"],
        "postedTo": config["params"]["postedTo"],
        "upsertLambda": upsert_lambda_name,
    }
    if dry_run:
        summary["records"] = dry_run_records
    return summary


def ingest_sqs_record(record: Mapping[str, Any], context: Any = None) -> Dict[str, Any]:
    body = _json_object(record.get("body"))
    config = _build_request_config(body)
    output_queue_url = body.get("output_queue_url") or os.getenv("UPSERT_QUEUE_URL")
    dry_run = bool(body.get("dry_run", False))

    if not output_queue_url and not dry_run:
        raise IngestError("UPSERT_QUEUE_URL must be configured unless the event sets dry_run=true.")

    message_id = str(record.get("messageId", "manual"))
    group_id = _message_group_id(record)
    normalized_count = 0
    emitted_batches = 0
    dry_run_records: List[Dict[str, Any]] = []

    for page_response, records in iter_opportunity_pages(config, message_id, context):
        source_received_at = datetime.now(timezone.utc).isoformat()
        payloads = [
            normalize_opportunity(item, config["ingest_window"], source_received_at)
            for item in records
        ]
        normalized_count += len(payloads)

        if dry_run:
            remaining = max(0, int(body.get("dry_run_max_records", 25)) - len(dry_run_records))
            dry_run_records.extend(payloads[:remaining])
        else:
            emitted_batches += emit_upsert_payloads(payloads, output_queue_url, group_id)

        LOGGER.info(
            "Fetched SAM.gov page offset=%s limit=%s totalRecords=%s pageRecords=%s",
            page_response.get("offset"),
            page_response.get("limit"),
            page_response.get("totalRecords"),
            len(records),
        )

    summary: Dict[str, Any] = {
        "normalizedRecords": normalized_count,
        "emittedBatches": emitted_batches,
        "postedFrom": config["params"]["postedFrom"],
        "postedTo": config["params"]["postedTo"],
    }
    if dry_run:
        summary["records"] = dry_run_records
    return summary


def iter_opportunity_pages(
    config: Mapping[str, Any],
    retry_seed: str,
    context: Any = None,
) -> Iterable[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    params = dict(config["params"])
    endpoint = str(config["endpoint"])
    limit = int(params["limit"])
    page_offset = int(config["start_offset"])
    max_pages = config.get("max_pages")
    pages_read = 0

    while True:
        params["offset"] = page_offset
        page_response = request_json_with_retry(
            endpoint,
            params,
            retry_seed=f"{retry_seed}:{page_offset}",
            context=context,
        )
        records = page_response.get("opportunitiesData") or []
        if not isinstance(records, list):
            raise IngestError("SAM.gov response field opportunitiesData was not a list.")

        yield page_response, records

        total_records = int(page_response.get("totalRecords") or 0)
        pages_read += 1
        next_page_starts_after = (page_offset + 1) * limit

        if not records or next_page_starts_after >= total_records:
            break
        if max_pages is not None and pages_read >= int(max_pages):
            break
        page_offset += 1


def request_json_with_retry(
    endpoint: str,
    params: Mapping[str, Any],
    retry_seed: str,
    context: Any = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Dict[str, Any]:
    last_error: Optional[BaseException] = None

    for attempt in range(max_retries + 1):
        try:
            return _http_get_json(endpoint, params)
        except HttpStatusError as exc:
            if exc.status_code == 404:
                LOGGER.info("SAM.gov returned 404/no-data for params=%s", _redacted(params))
                return {
                    "totalRecords": 0,
                    "limit": params.get("limit"),
                    "offset": params.get("offset"),
                    "opportunitiesData": [],
                }
            if exc.status_code not in TRANSIENT_HTTP_STATUSES:
                raise
            last_error = exc
            retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
        except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            retry_after = None

        if attempt >= max_retries:
            raise RetryBudgetExceeded(f"Retry budget exhausted after {max_retries} retries.") from last_error

        sleep_seconds = _backoff_seconds(
            attempt=attempt,
            retry_seed=retry_seed,
            retry_after_seconds=retry_after,
        )
        _sleep_with_lambda_deadline(sleep_seconds, context)

    raise RetryBudgetExceeded("Retry loop exited without returning a response.") from last_error


def normalize_opportunity(
    source: Mapping[str, Any],
    ingest_window: Mapping[str, Any],
    source_received_at: str,
) -> Dict[str, Any]:
    notice_id = _clean_str(source.get("noticeId"))
    if not notice_id:
        fingerprint = hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        notice_id = f"missing-notice-id-{fingerprint[:24]}"

    full_parent_name = _clean_str(source.get("fullParentPathName"))
    full_parent_code = _clean_str(source.get("fullParentPathCode"))
    name_parts = _split_path(full_parent_name)
    code_parts = _split_path(full_parent_code)

    award = source.get("award") if isinstance(source.get("award"), Mapping) else {}
    awardee = award.get("awardee") if isinstance(award.get("awardee"), Mapping) else {}

    opportunity = {
        "notice_id": notice_id,
        "solicitation_number": _clean_str(source.get("solicitationNumber")),
        "title": _clean_str(source.get("title")) or "Untitled SAM.gov notice",
        "opportunity_type": _clean_str(source.get("type")),
        "base_type": _clean_str(source.get("baseType")),
        "active_status": _active_status(source.get("active")),
        "posted_at": _parse_sam_datetime(source.get("postedDate")),
        "response_deadline": _parse_sam_datetime(source.get("responseDeadLine")),
        "archive_at": _parse_sam_datetime(source.get("archiveDate")),
        "naics_code": _clean_str(source.get("naicsCode")),
        "psc_code": _clean_str(source.get("classificationCode")),
        "set_aside_code": _clean_str(source.get("typeOfSetAside")) or _clean_str(source.get("setAsideCode")),
        "set_aside_description": _clean_str(source.get("typeOfSetAsideDescription")) or _clean_str(source.get("setAside")),
        "funding_agency_name": name_parts[0] if name_parts else _clean_str(source.get("department")),
        "funding_agency_code": code_parts[0] if code_parts else None,
        "subtier_name": name_parts[1] if len(name_parts) > 1 else _clean_str(source.get("subTier")),
        "office_name": name_parts[2] if len(name_parts) > 2 else _clean_str(source.get("office")),
        "full_parent_path_name": full_parent_name,
        "full_parent_path_code": full_parent_code,
        "organization_type": _clean_str(source.get("organizationType")),
        "place_of_performance": _json_dict(source.get("placeOfPerformance")),
        "office_address": _json_dict(source.get("officeAddress")),
        "estimated_value_min": None,
        "estimated_value_max": None,
        "currency_code": "USD",
        "description_url": _clean_str(source.get("description")),
        "ui_link": _clean_str(source.get("uiLink")),
        "resource_links": _string_list(source.get("resourceLinks")),
        "sow_text": None,
        "source_payload": dict(source),
        "source_updated_at": source_received_at,
    }

    related_award = None
    if award:
        related_award = {
            "award_number": _clean_str(award.get("number")),
            "award_amount": _money(award.get("amount")),
            "award_date": _parse_sam_datetime(award.get("date")),
            "awardee": {
                "legal_name": _clean_str(awardee.get("name")),
                "canonical_uei": _clean_str(awardee.get("ueiSAM")),
                "location": _json_dict(awardee.get("location")),
            },
        }

    return {
        "dataset": "sam_opportunities",
        "upsert": {
            "table": "capture.opportunities",
            "conflict_columns": ["notice_id"],
            "columns": list(opportunity.keys()),
        },
        "natural_key": {"notice_id": notice_id},
        "ingest_window": dict(ingest_window),
        "opportunity": opportunity,
        "related_award": related_award,
        "source_fingerprint": hashlib.sha256(
            json.dumps(source, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest(),
    }


def emit_upsert_payloads(records: List[Dict[str, Any]], queue_url: str, group_id: str) -> int:
    if not records:
        return 0

    sqs = _sqs_client()
    emitted = 0
    for chunk in _chunk_records(records):
        body = json.dumps(
            {
                "dataset": "sam_opportunities",
                "upsert_key": ["notice_id"],
                "records": chunk,
            },
            separators=(",", ":"),
            default=str,
        )
        send_args: Dict[str, Any] = {"QueueUrl": queue_url, "MessageBody": body}
        if queue_url.endswith(".fifo"):
            send_args["MessageGroupId"] = _sqs_safe_group_id(group_id)
            send_args["MessageDeduplicationId"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
        sqs.send_message(**send_args)
        emitted += 1
    return emitted


def _build_request_config(body: Mapping[str, Any]) -> Dict[str, Any]:
    LOGGER.info("Building SAM.gov request configuration.")
    api_key = body.get("api_key") or _resolve_sam_api_key()
    if not api_key:
        raise IngestError("SAM_API_KEY must be configured or provided in the SQS message body.")

    posted_from = body.get("posted_from") or body.get("postedFrom")
    posted_to = body.get("posted_to") or body.get("postedTo")
    if not posted_from or not posted_to:
        raise IngestError("SQS body must include posted_from/posted_to or postedFrom/postedTo.")

    params: Dict[str, Any] = {
        "api_key": api_key,
        "postedFrom": _format_sam_request_date(str(posted_from)),
        "postedTo": _format_sam_request_date(str(posted_to)),
        "limit": min(max(int(body.get("limit", DEFAULT_PAGE_LIMIT)), 1), 1000),
    }

    for key in DIRECT_FILTER_KEYS:
        if key in body and body[key] not in (None, ""):
            params[key] = body[key]

    for key in DATE_FILTER_KEYS:
        if key in body and body[key] not in (None, ""):
            params[key] = _format_sam_request_date(str(body[key]))

    extra_params = body.get("extra_params") or {}
    if not isinstance(extra_params, Mapping):
        raise IngestError("extra_params must be a JSON object when provided.")
    for key, value in extra_params.items():
        if value not in (None, ""):
            params[str(key)] = value

    return {
        "endpoint": body.get("endpoint") or os.getenv("SAM_OPPORTUNITIES_ENDPOINT", DEFAULT_ENDPOINT),
        "params": params,
        "start_offset": int(body.get("offset", 0)),
        "max_pages": body.get("max_pages"),
        "ingest_window": {
            "posted_from": params["postedFrom"],
            "posted_to": params["postedTo"],
            "filters": {k: v for k, v in params.items() if k not in {"api_key", "postedFrom", "postedTo", "limit"}},
        },
    }


def upsert_opportunities_to_database(records: List[Dict[str, Any]]) -> int:
    if not records:
        return 0
    import psycopg2
    from psycopg2.extras import Json, execute_values

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise IngestError("DATABASE_URL must be configured for direct DB upsert.")

    values = []
    for record in records:
        opp = record["opportunity"]
        values.append(
            (
                opp["notice_id"],
                opp["solicitation_number"],
                opp["title"],
                opp["opportunity_type"],
                opp["base_type"],
                opp["active_status"],
                opp["posted_at"],
                opp["response_deadline"],
                opp["archive_at"],
                opp["naics_code"],
                opp["psc_code"],
                opp["set_aside_code"],
                opp["set_aside_description"],
                opp["funding_agency_name"],
                opp["funding_agency_code"],
                opp["subtier_name"],
                opp["office_name"],
                opp["full_parent_path_name"],
                opp["full_parent_path_code"],
                opp["organization_type"],
                Json(opp["place_of_performance"]),
                Json(opp["office_address"]),
                opp["estimated_value_min"],
                opp["estimated_value_max"],
                opp["currency_code"],
                opp["description_url"],
                opp["ui_link"],
                opp["resource_links"],
                opp["sow_text"],
                Json(opp["source_payload"]),
                opp["source_updated_at"],
            )
        )

    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO capture.opportunities (
                  notice_id, solicitation_number, title, opportunity_type, base_type,
                  active_status, posted_at, response_deadline, archive_at, naics_code,
                  psc_code, set_aside_code, set_aside_description, funding_agency_name,
                  funding_agency_code, subtier_name, office_name, full_parent_path_name,
                  full_parent_path_code, organization_type, place_of_performance,
                  office_address, estimated_value_min, estimated_value_max, currency_code,
                  description_url, ui_link, resource_links, sow_text, source_payload,
                  source_updated_at
                )
                VALUES %s
                ON CONFLICT (notice_id)
                DO UPDATE SET
                  solicitation_number = EXCLUDED.solicitation_number,
                  title = EXCLUDED.title,
                  opportunity_type = EXCLUDED.opportunity_type,
                  base_type = EXCLUDED.base_type,
                  active_status = EXCLUDED.active_status,
                  posted_at = EXCLUDED.posted_at,
                  response_deadline = EXCLUDED.response_deadline,
                  archive_at = EXCLUDED.archive_at,
                  naics_code = EXCLUDED.naics_code,
                  psc_code = EXCLUDED.psc_code,
                  set_aside_code = EXCLUDED.set_aside_code,
                  set_aside_description = EXCLUDED.set_aside_description,
                  funding_agency_name = EXCLUDED.funding_agency_name,
                  funding_agency_code = EXCLUDED.funding_agency_code,
                  subtier_name = EXCLUDED.subtier_name,
                  office_name = EXCLUDED.office_name,
                  full_parent_path_name = EXCLUDED.full_parent_path_name,
                  full_parent_path_code = EXCLUDED.full_parent_path_code,
                  organization_type = EXCLUDED.organization_type,
                  place_of_performance = EXCLUDED.place_of_performance,
                  office_address = EXCLUDED.office_address,
                  estimated_value_min = EXCLUDED.estimated_value_min,
                  estimated_value_max = EXCLUDED.estimated_value_max,
                  description_url = EXCLUDED.description_url,
                  ui_link = EXCLUDED.ui_link,
                  resource_links = EXCLUDED.resource_links,
                  sow_text = COALESCE(EXCLUDED.sow_text, capture.opportunities.sow_text),
                  source_payload = EXCLUDED.source_payload,
                  source_updated_at = EXCLUDED.source_updated_at,
                  updated_at = now();
                """,
                values,
                page_size=100,
            )
    return len(records)


def fetch_sam_enrichment_candidates(limit: int, notice_ids: List[str], force: bool = False) -> List[Dict[str, Any]]:
    import psycopg2
    from psycopg2.extras import RealDictCursor, register_default_jsonb

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise IngestError("DATABASE_URL must be configured for SAM enrichment.")

    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        register_default_jsonb(conn, loads=json.loads)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  opportunity_id::text,
                  notice_id,
                  solicitation_number,
                  title,
                  opportunity_type,
                  posted_at,
                  response_deadline,
                  naics_code,
                  psc_code,
                  set_aside_code,
                  set_aside_description,
                  funding_agency_name,
                  funding_agency_code,
                  subtier_name,
                  office_name,
                  description_url,
                  ui_link,
                  resource_links,
                  sow_text,
                  source_payload,
                  source_updated_at
                FROM capture.opportunities
                WHERE active_status = 'active'
                  AND (%(force)s OR sow_embedding IS NULL OR sow_text IS NULL)
                  AND (%(notice_ids)s::text[] IS NULL OR notice_id = ANY(%(notice_ids)s::text[]))
                  AND notice_id NOT LIKE 'SAM-2026-%%'
                ORDER BY posted_at DESC NULLS LAST, source_updated_at DESC NULLS LAST
                LIMIT %(limit)s;
                """,
                {"force": force, "notice_ids": notice_ids or None, "limit": limit},
            )
            return [dict(row) for row in cur.fetchall()]


def enrich_sam_opportunity_row(
    row: Mapping[str, Any],
    embedding_provider: str,
    fetch_documents: bool,
    api_key: Optional[str],
    document_limit: int,
) -> Dict[str, Any]:
    text, sources = build_sam_enrichment_text(row, fetch_documents, api_key, document_limit)
    if len(text) < DEFAULT_ENRICHMENT_MIN_TEXT_CHARS:
        patch = {
            "sam_enrichment": {
                "status": "skipped",
                "reason": "insufficient_text",
                "text_chars": len(text),
                "attempted_at": datetime.now(timezone.utc).isoformat(),
                "sources": sources,
            }
        }
        write_sam_enrichment_result(row["opportunity_id"], None, None, patch)
        return {"notice_id": row.get("notice_id"), "status": "skipped", "reason": "insufficient_text", "textChars": len(text)}

    embedding, provider_label = embed_enrichment_text(text, row, embedding_provider)
    patch = {
        "sam_enrichment": {
            "status": "enriched",
            "embedding_provider": provider_label,
            "text_chars": len(text),
            "source_count": len(sources),
            "enriched_at": datetime.now(timezone.utc).isoformat(),
            "sources": sources,
        }
    }
    write_sam_enrichment_result(row["opportunity_id"], text, embedding, patch)
    return {
        "notice_id": row.get("notice_id"),
        "status": "enriched",
        "textChars": len(text),
        "sourceCount": len(sources),
        "embeddingProvider": provider_label,
    }


def build_sam_enrichment_text(
    row: Mapping[str, Any],
    fetch_documents: bool,
    api_key: Optional[str],
    document_limit: int,
) -> Tuple[str, List[Dict[str, Any]]]:
    source_payload = row.get("source_payload") if isinstance(row.get("source_payload"), Mapping) else {}
    fragments: List[str] = []
    sources: List[Dict[str, Any]] = []

    metadata_text = _normalize_text(
        "\n".join(
            str(value)
            for value in [
                row.get("title"),
                row.get("solicitation_number"),
                row.get("funding_agency_name"),
                row.get("subtier_name"),
                row.get("office_name"),
                row.get("set_aside_description"),
                row.get("naics_code"),
                row.get("psc_code"),
                row.get("sow_text"),
                _payload_summary_text(source_payload),
            ]
            if value
        )
    )
    if metadata_text:
        fragments.append(metadata_text)
        sources.append({"type": "sam_metadata", "chars": len(metadata_text)})

    if fetch_documents and document_limit > 0:
        for url in _document_urls(row, source_payload)[:document_limit]:
            document = _fetch_document_text(url, api_key)
            sources.append(document["source"])
            if document["text"]:
                fragments.append(document["text"])

    combined = _normalize_text("\n\n".join(fragments))
    return combined[:DEFAULT_ENRICHMENT_MAX_TEXT_CHARS], sources


def embed_enrichment_text(
    text: str,
    row: Mapping[str, Any],
    provider: str,
) -> Tuple[List[float], str]:
    if provider == "bedrock":
        return _bedrock_embedding(text), os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")
    if provider in {"deterministic", "hash", "local"}:
        return _deterministic_text_embedding(text, row), "deterministic_text_hash_v1"
    raise IngestError(f"Unsupported SAM_EMBEDDING_PROVIDER '{provider}'. Use deterministic or bedrock.")


def write_sam_enrichment_result(
    opportunity_id: str,
    sow_text: Optional[str],
    embedding: Optional[List[float]],
    source_payload_patch: Mapping[str, Any],
) -> None:
    import psycopg2
    from psycopg2.extras import Json

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise IngestError("DATABASE_URL must be configured for SAM enrichment writes.")

    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            if embedding is not None and sow_text:
                cur.execute(
                    """
                    UPDATE capture.opportunities
                    SET sow_text = %(sow_text)s,
                        sow_embedding = %(embedding)s::vector,
                        source_payload = source_payload || %(source_payload_patch)s::jsonb,
                        updated_at = now()
                    WHERE opportunity_id = %(opportunity_id)s::uuid;
                    """,
                    {
                        "opportunity_id": opportunity_id,
                        "sow_text": sow_text,
                        "embedding": _vector_literal(embedding),
                        "source_payload_patch": Json(source_payload_patch),
                    },
                )
                cur.execute(
                    """
                    DELETE FROM capture.source_evidence
                    WHERE opportunity_id = %(opportunity_id)s::uuid
                      AND evidence_type = 'opportunity'
                      AND source_system = 'SAM.gov';

                    INSERT INTO capture.source_evidence (
                      opportunity_id, evidence_type, source_system, source_record_id,
                      source_title, source_url, source_record_date, source_amount,
                      agency_name, agency_code, naics_code, psc_code, explanation,
                      confidence, source_payload
                    )
                    SELECT
                      opportunity_id,
                      'opportunity',
                      'SAM.gov',
                      notice_id,
                      title,
                      COALESCE(ui_link, description_url),
                      posted_at::date,
                      COALESCE(estimated_value_max, estimated_value_min),
                      funding_agency_name,
                      funding_agency_code,
                      naics_code,
                      psc_code,
                      'Live SAM.gov opportunity enriched with extracted source text and a pgvector SOW embedding.',
                      0.8600,
                      %(source_payload_patch)s::jsonb
                    FROM capture.opportunities
                    WHERE opportunity_id = %(opportunity_id)s::uuid;
                    """,
                    {"opportunity_id": opportunity_id, "source_payload_patch": Json(source_payload_patch)},
                )
            else:
                cur.execute(
                    """
                    UPDATE capture.opportunities
                    SET source_payload = source_payload || %(source_payload_patch)s::jsonb,
                        updated_at = now()
                    WHERE opportunity_id = %(opportunity_id)s::uuid;
                    """,
                    {"opportunity_id": opportunity_id, "source_payload_patch": Json(source_payload_patch)},
                )


def count_enriched_sam_opportunities() -> int:
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return 0
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)::int
                FROM capture.opportunities
                WHERE sow_embedding IS NOT NULL
                  AND (
                    source_payload ? 'noticeId'
                    OR source_payload ? 'notice_id'
                    OR ui_link ILIKE '%%sam.gov%%'
                    OR description_url ILIKE '%%sam.gov%%'
                  );
                """
            )
            return int(cur.fetchone()[0])


def invoke_upsert_lambda(
    function_name: str,
    records: List[Dict[str, Any]],
    total_records: int,
    ingest_window: Mapping[str, Any],
) -> int:
    if not records:
        return 0
    payload = {
        "mode": "upsert_sam_records",
        "source_mode": "live_api",
        "total_records": total_records,
        "ingest_window": dict(ingest_window),
        "records": records,
    }
    response = _lambda_client().invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"),
    )
    response_payload = json.loads(response["Payload"].read().decode("utf-8") or "{}")
    if response.get("FunctionError"):
        raise IngestError(f"Upsert Lambda failed: {json.dumps(response_payload, default=str)[:1000]}")
    return int(response_payload.get("writtenRecords") or 0)


def update_data_freshness(
    source_system: str,
    dataset_name: str,
    source_mode: str,
    record_count: int,
    source_url: str,
    freshness_sla_hours: int = 6,
    notes: str = "Live scheduler completed.",
) -> None:
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO capture.data_freshness (
                  source_system, dataset_name, source_mode, last_successful_sync_at,
                  last_attempted_sync_at, sync_status, record_count, freshness_sla_hours,
                  source_url, notes
                )
                VALUES (%s, %s, %s, now(), now(), 'ready', %s, %s, %s, %s)
                ON CONFLICT (source_system, dataset_name)
                DO UPDATE SET
                  source_mode = EXCLUDED.source_mode,
                  last_successful_sync_at = EXCLUDED.last_successful_sync_at,
                  last_attempted_sync_at = EXCLUDED.last_attempted_sync_at,
                  sync_status = 'ready',
                  record_count = EXCLUDED.record_count,
                  freshness_sla_hours = EXCLUDED.freshness_sla_hours,
                  source_url = EXCLUDED.source_url,
                  notes = EXCLUDED.notes,
                  updated_at = now();
                """,
                (source_system, dataset_name, source_mode, record_count, freshness_sla_hours, source_url, notes),
            )


def _start_ingest_run(body: Mapping[str, Any]) -> Optional[str]:
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO capture.ingest_runs (source_system, dataset_name, run_status, run_config)
                VALUES ('SAM.gov', 'Opportunities', 'started', %s::jsonb)
                RETURNING ingest_run_id::text;
                """,
                (json.dumps(_redacted(body)),),
            )
            return str(cur.fetchone()[0])


def _finish_ingest_run(
    run_id: str,
    status_value: str,
    records_read: int,
    records_written: int,
    error_message: Optional[str] = None,
) -> None:
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE capture.ingest_runs
                SET run_status = %s,
                    finished_at = now(),
                    records_read = %s,
                    records_written = %s,
                    error_message = %s
                WHERE ingest_run_id = %s::uuid;
                """,
                (status_value, records_read, records_written, error_message, run_id),
            )


def _http_get_json(endpoint: str, params: Mapping[str, Any]) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params, doseq=True)
    LOGGER.info("Requesting SAM.gov opportunities page offset=%s limit=%s", params.get("offset"), params.get("limit"))
    request = urllib.request.Request(
        f"{endpoint}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "GovConCaptureOS/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise HttpStatusError(exc.code, dict(exc.headers.items()), body) from exc
    except json.JSONDecodeError as exc:
        raise IngestError("SAM.gov returned a non-JSON response.") from exc


def _backoff_seconds(attempt: int, retry_seed: str, retry_after_seconds: Optional[float]) -> float:
    exponential = min(DEFAULT_MAX_BACKOFF_SECONDS, DEFAULT_BASE_BACKOFF_SECONDS * (2 ** attempt))
    rng = random.Random(f"{retry_seed}:{attempt}")
    jitter = rng.uniform(0.0, exponential * 0.25)
    computed = min(DEFAULT_MAX_BACKOFF_SECONDS, exponential + jitter)
    if retry_after_seconds is None:
        return computed
    return min(DEFAULT_MAX_BACKOFF_SECONDS, max(computed, retry_after_seconds))


def _sleep_with_lambda_deadline(seconds: float, context: Any = None) -> None:
    if context is not None and hasattr(context, "get_remaining_time_in_millis"):
        remaining_seconds = context.get_remaining_time_in_millis() / 1000.0
        if remaining_seconds <= seconds + 1.5:
            raise RetryBudgetExceeded("Not enough Lambda time remains for another retry delay.")
    LOGGER.warning("Backing off for %.2f seconds before retrying SAM.gov request.", seconds)
    time.sleep(seconds)


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = email.utils.parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None


def _format_sam_request_date(value: str) -> str:
    value = value.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%m/%d/%Y")
    except ValueError as exc:
        raise IngestError(f"Invalid SAM.gov date '{value}'. Expected MM/DD/YYYY or ISO date.") from exc


def _parse_sam_datetime(value: Any) -> Optional[str]:
    text = _clean_str(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    return text


def _active_status(value: Any) -> str:
    text = (_clean_str(value) or "unknown").lower()
    if text in {"yes", "true", "active"}:
        return "active"
    if text in {"no", "false", "inactive", "archived"}:
        return "inactive"
    return text


def _money(value: Any) -> Optional[str]:
    text = _clean_str(value)
    if text is None:
        return None
    try:
        return str(Decimal(text.replace(",", "")).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return None


def _json_object(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if raw in (None, ""):
        return {}
    parsed = json.loads(str(raw))
    if not isinstance(parsed, Mapping):
        raise IngestError("SQS message body must be a JSON object.")
    return dict(parsed)


def _scheduled_body(event: Mapping[str, Any]) -> Dict[str, Any]:
    if "body" in event:
        return _json_object(event.get("body"))
    body = dict(event)
    lookback_days = int(body.get("lookback_days") or os.getenv("SAM_INGEST_LOOKBACK_DAYS", "1"))
    window_end = datetime.now(timezone.utc).date()
    window_start = window_end - timedelta(days=max(1, lookback_days))
    body.setdefault("posted_from", window_start.isoformat())
    body.setdefault("posted_to", window_end.isoformat())
    body.setdefault("limit", int(os.getenv("PAGE_LIMIT", "1000")))
    body.setdefault("max_pages", int(os.getenv("SCHEDULED_MAX_PAGES", "2")))
    body.setdefault("direct_db_upsert", os.getenv("DIRECT_DB_UPSERT", "true"))
    return body


def _resolve_sam_api_key() -> Optional[str]:
    direct = os.getenv("SAM_API_KEY")
    if direct:
        return direct
    secret_arn = os.getenv("SAM_API_KEY_SECRET_ARN")
    if not secret_arn:
        return None
    import boto3
    from botocore.config import Config

    LOGGER.info("Reading SAM.gov API key from Secrets Manager.")
    secret = boto3.client(
        "secretsmanager",
        config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2}),
    ).get_secret_value(SecretId=secret_arn)
    value = secret.get("SecretString")
    if not value:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, Mapping):
            return str(parsed.get("SAM_API_KEY") or parsed.get("api_key") or parsed.get("value") or "")
    except json.JSONDecodeError:
        return value
    return value


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _json_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in (_clean_str(v) for v in value) if item]
    cleaned = _clean_str(value)
    return [cleaned] if cleaned else []


def _split_path(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(".") if part.strip()]


def _message_group_id(record: Mapping[str, Any]) -> str:
    attributes = record.get("attributes") if isinstance(record.get("attributes"), Mapping) else {}
    return str(attributes.get("MessageGroupId") or "sam-opportunities")


def _sqs_safe_group_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._:-" else "-" for ch in value)
    return (safe or "sam-opportunities")[:128]


def _chunk_records(records: List[Dict[str, Any]], max_bytes: int = 220_000) -> Iterable[List[Dict[str, Any]]]:
    chunk: List[Dict[str, Any]] = []
    for record in records:
        candidate = chunk + [record]
        encoded = json.dumps({"records": candidate}, separators=(",", ":"), default=str).encode("utf-8")
        if len(encoded) > max_bytes and chunk:
            yield chunk
            chunk = [record]
        elif len(encoded) > max_bytes:
            key = record.get("natural_key", {})
            raise IngestError(f"Normalized record is too large for SQS delivery: {key}")
        else:
            chunk = candidate
    if chunk:
        yield chunk


def _sqs_client() -> Any:
    import boto3

    return boto3.client("sqs")


def _lambda_client() -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client("lambda", config=Config(connect_timeout=3, read_timeout=30, retries={"max_attempts": 2}))


def _chunk_by_count(records: List[Dict[str, Any]], size: int) -> Iterable[List[Dict[str, Any]]]:
    for index in range(0, len(records), size):
        yield records[index : index + size]


def _payload_summary_text(source_payload: Mapping[str, Any]) -> str:
    fragments: List[str] = []
    for key in (
        "descriptionText",
        "description_text",
        "synopsis",
        "summary",
        "requirements",
        "additionalInfo",
        "typeOfSetAsideDescription",
    ):
        value = source_payload.get(key)
        if isinstance(value, str) and not _looks_like_url(value):
            fragments.append(value)
    point_of_contact = source_payload.get("pointOfContact")
    if isinstance(point_of_contact, list):
        fragments.extend(str(item.get("fullName") or item.get("title") or "") for item in point_of_contact if isinstance(item, Mapping))
    return _normalize_text("\n".join(fragments))


def _document_urls(row: Mapping[str, Any], source_payload: Mapping[str, Any]) -> List[str]:
    candidates: List[Any] = [row.get("description_url")]
    candidates.extend(row.get("resource_links") or [])
    candidates.extend(_string_list(source_payload.get("resourceLinks")))
    candidates.extend(_string_list(source_payload.get("links")))

    urls: List[str] = []
    for candidate in candidates:
        url = _safe_document_url(candidate)
        if url and url not in urls:
            urls.append(url)
    return urls


def _fetch_document_text(url: str, api_key: Optional[str]) -> Dict[str, Any]:
    request_url = _append_api_key_for_sam_api(url, api_key)
    headers = {
        "Accept": "application/json, text/html, text/plain;q=0.9, */*;q=0.5",
        "User-Agent": "GovConCaptureOS/1.0",
    }
    if api_key:
        headers["X-Api-Key"] = api_key
    source = {"type": "document", "url": url, "status": "attempted"}
    try:
        request = urllib.request.Request(request_url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=DEFAULT_DOCUMENT_FETCH_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            body = response.read(DEFAULT_DOCUMENT_FETCH_MAX_BYTES + 1)
        truncated = len(body) > DEFAULT_DOCUMENT_FETCH_MAX_BYTES
        body = body[:DEFAULT_DOCUMENT_FETCH_MAX_BYTES]
        text = _decode_document_body(body, content_type)
        source.update({"status": "read", "content_type": content_type or "unknown", "chars": len(text), "truncated": truncated})
        return {"text": text[:DEFAULT_ENRICHMENT_MAX_TEXT_CHARS], "source": source}
    except Exception as exc:
        LOGGER.warning("Could not fetch SAM.gov document %s: %s", url, exc)
        source.update({"status": "failed", "error": str(exc)[:180]})
        return {"text": "", "source": source}


def _decode_document_body(body: bytes, content_type: str) -> str:
    if not body or body.startswith(b"%PDF"):
        return ""
    text = body.decode("utf-8", "replace")
    if content_type == "application/json" or text.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(text)
            return _normalize_text(" ".join(_json_text_fragments(parsed)))
        except json.JSONDecodeError:
            return _normalize_text(text)
    if content_type in {"text/html", "application/xhtml+xml"} or "<html" in text[:500].lower():
        return _normalize_text(_strip_html(text))
    if content_type.startswith("text/") or content_type in {"application/xml", "application/octet-stream", ""}:
        return _normalize_text(text)
    return ""


def _json_text_fragments(value: Any, depth: int = 0) -> List[str]:
    if depth > 5:
        return []
    if isinstance(value, str):
        return [] if _looks_like_url(value) else [value]
    if isinstance(value, list):
        fragments: List[str] = []
        for item in value[:50]:
            fragments.extend(_json_text_fragments(item, depth + 1))
        return fragments
    if isinstance(value, Mapping):
        fragments = []
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"url", "href", "filename", "resourceurl"}:
                continue
            fragments.extend(_json_text_fragments(item, depth + 1))
        return fragments
    return []


def _safe_document_url(value: Any) -> Optional[str]:
    url = _clean_str(value)
    if not url or not _looks_like_url(url):
        return None
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return None
    if not any(host == allowed or host.endswith(f".{allowed}") for allowed in _ALLOWED_DOCUMENT_HOSTS):
        return None
    return url


def _append_api_key_for_sam_api(url: str, api_key: Optional[str]) -> str:
    if not api_key:
        return url
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname != "api.sam.gov":
        return url
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if any(key == "api_key" for key, _ in query):
        return url
    query.append(("api_key", api_key))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


class _HTMLTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "dl",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._fragments: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_name = tag.lower()
        if tag_name in {"script", "style", "noscript"}:
            self._skip_depth += 1
        elif tag_name in self._BLOCK_TAGS:
            self._fragments.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag_name in self._BLOCK_TAGS:
            self._fragments.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data:
            self._fragments.append(data)

    def text(self) -> str:
        return html.unescape(" ".join(self._fragments))


def _strip_html(text: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(str(text))
        parser.close()
        return parser.text()
    except Exception:
        LOGGER.debug("Falling back to entity unescape after HTML parser failure.", exc_info=True)
        return html.unescape(str(text))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(text))).strip()


def _looks_like_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


def _deterministic_text_embedding(text: str, row: Mapping[str, Any]) -> List[float]:
    values = [0.0] * VECTOR_DIMENSION
    tokens = _TOKEN_RE.findall(text.lower())
    tokens.extend(
        f"{label}:{value}".lower()
        for label, value in (
            ("naics", row.get("naics_code")),
            ("psc", row.get("psc_code")),
            ("agency", row.get("funding_agency_code")),
            ("setaside", row.get("set_aside_code")),
        )
        if value
    )
    if not tokens:
        raise IngestError("Cannot build embedding from empty enrichment text.")
    for token in tokens[:8000]:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_DIMENSION
        sign = -1.0 if digest[4] & 1 else 1.0
        weight = 1.8 if ":" in token else 1.0
        values[index] += sign * weight
    return _normalize_vector(values)


def _bedrock_embedding(text: str) -> List[float]:
    import boto3
    from botocore.config import Config

    model_id = os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")
    client = boto3.client("bedrock-runtime", config=Config(connect_timeout=3, read_timeout=20, retries={"max_attempts": 2}))
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"inputText": text[:DEFAULT_ENRICHMENT_MAX_TEXT_CHARS]}).encode("utf-8"),
    )
    payload = json.loads(response["body"].read().decode("utf-8"))
    embedding = payload.get("embedding")
    if not isinstance(embedding, list):
        raise IngestError(f"Bedrock embedding model {model_id} returned no embedding.")
    if len(embedding) != VECTOR_DIMENSION:
        raise IngestError(f"Bedrock embedding dimension {len(embedding)} does not match pgvector dimension {VECTOR_DIMENSION}.")
    return [float(value) for value in embedding]


def _normalize_vector(values: List[float]) -> List[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise IngestError("Cannot normalize zero embedding vector.")
    return [value / norm for value in values]


def _vector_literal(values: List[float]) -> str:
    if len(values) != VECTOR_DIMENSION:
        raise IngestError(f"Embedding dimension {len(values)} does not match pgvector dimension {VECTOR_DIMENSION}.")
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def _lambda_time_available(context: Any, reserve_seconds: float) -> bool:
    if context is None or not hasattr(context, "get_remaining_time_in_millis"):
        return True
    return context.get_remaining_time_in_millis() / 1000.0 > reserve_seconds


def _redacted(params: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: ("***" if key == "api_key" else value) for key, value in params.items()}
