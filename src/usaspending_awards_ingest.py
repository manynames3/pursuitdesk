from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .gsa_api_ingest import _deterministic_text_embedding, _vector_literal


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

DEFAULT_ENDPOINT = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
DEFAULT_LIMIT = min(max(int(os.getenv("USASPENDING_PAGE_LIMIT", "100")), 1), 100)
DEFAULT_MAX_PAGES = min(max(int(os.getenv("USASPENDING_MAX_PAGES", "5")), 1), 25)
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("USASPENDING_REQUEST_TIMEOUT_SECONDS", "20"))
CONTRACT_AWARD_TYPE_CODES = [
    "A",
    "B",
    "C",
    "D",
    "IDV_A",
    "IDV_B",
    "IDV_B_A",
    "IDV_B_B",
    "IDV_B_C",
    "IDV_C",
    "IDV_D",
]
AWARD_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Start Date",
    "End Date",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Award Type",
    "Funding Agency",
    "Funding Sub Agency",
    "Description",
    "NAICS",
    "PSC",
]


class USAspendingIngestError(Exception):
    pass


def lambda_handler(event: Mapping[str, Any], context: Any) -> Dict[str, Any]:
    if event.get("mode") == "upsert_usaspending_awards":
        return upsert_usaspending_awards_event(event)
    return ingest_usaspending_awards_event(event, context=context)


def ingest_usaspending_awards_event(event: Mapping[str, Any], context: Any = None) -> Dict[str, Any]:
    body = dict(event)
    dry_run = _truthy(body.get("dry_run", False))
    upsert_lambda_name = body.get("upsert_lambda_name") or os.getenv("USASPENDING_UPSERT_LAMBDA_NAME")
    if not upsert_lambda_name and not dry_run:
        raise USAspendingIngestError("Set USASPENDING_UPSERT_LAMBDA_NAME or pass upsert_lambda_name unless dry_run=true.")

    config = _build_request_config(body)
    fetched = 0
    written = 0
    dry_run_records: List[Dict[str, Any]] = []

    for page in range(1, int(config["max_pages"]) + 1):
        payload = {**config["payload"], "page": page}
        response = _http_post_json(config["endpoint"], payload)
        rows = response.get("results") or []
        if not isinstance(rows, list) or not rows:
            break
        fetched += len(rows)
        if dry_run:
            dry_run_records.extend(rows[: max(0, 25 - len(dry_run_records))])
        else:
            written += _invoke_upsert_lambda(upsert_lambda_name, rows, config)
        if not response.get("page_metadata", {}).get("hasNext"):
            break
        if not _lambda_time_available(context, reserve_seconds=5):
            break

    return {
        "sourceSystem": "USAspending",
        "dataset": "Contract Awards",
        "fetchedRecords": fetched,
        "writtenRecords": written,
        "dryRun": dry_run,
        "records": dry_run_records,
    }


def upsert_usaspending_awards_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    records = event.get("records") or []
    if not isinstance(records, list):
        raise USAspendingIngestError("records must be a list.")
    written = upsert_awards_to_database(records)
    update_data_freshness(written)
    return {"normalizedRecords": len(records), "writtenRecords": written}


def _build_request_config(body: Mapping[str, Any]) -> Dict[str, Any]:
    end_date = _parse_date(body.get("end_date")) or date.today()
    start_date = _parse_date(body.get("start_date")) or (end_date - timedelta(days=int(body.get("lookback_days") or 365)))
    filters: Dict[str, Any] = {
        "time_period": [{"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}],
        "award_type_codes": body.get("award_type_codes") or CONTRACT_AWARD_TYPE_CODES,
    }
    if body.get("naics_codes"):
        filters["naics_codes"] = _string_list(body["naics_codes"])
    if body.get("psc_codes"):
        filters["psc_codes"] = _string_list(body["psc_codes"])
    if body.get("keywords"):
        filters["keywords"] = _string_list(body["keywords"])

    return {
        "endpoint": body.get("endpoint") or os.getenv("USASPENDING_ENDPOINT", DEFAULT_ENDPOINT),
        "max_pages": min(max(int(body.get("max_pages") or DEFAULT_MAX_PAGES), 1), 25),
        "payload": {
            "filters": filters,
            "fields": body.get("fields") or AWARD_FIELDS,
            "sort": body.get("sort") or "Award Amount",
            "order": body.get("order") or "desc",
            "limit": min(max(int(body.get("limit") or DEFAULT_LIMIT), 1), 100),
            "subawards": False,
        },
    }


def upsert_awards_to_database(records: List[Mapping[str, Any]]) -> int:
    if not records:
        return 0
    import psycopg2
    from psycopg2.extras import Json, execute_values

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise USAspendingIngestError("DATABASE_URL must be configured.")

    entity_rows = []
    award_rows = []
    for raw in records:
        normalized = normalize_usaspending_award(raw)
        entity_rows.append(normalized["entity"])
        award_rows.append(normalized["award"])

    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO capture.entities (
                  legal_name, canonical_uei, cage_code, alias_names, source_system, source_payload
                )
                VALUES %s
                ON CONFLICT (normalized_legal_name)
                DO UPDATE SET
                  source_payload = capture.entities.source_payload || EXCLUDED.source_payload,
                  updated_at = now()
                RETURNING entity_id, legal_name;
                """,
                [
                    (
                        row["legal_name"],
                        row.get("canonical_uei"),
                        row.get("cage_code"),
                        [],
                        "USAspending",
                        Json(row["source_payload"]),
                    )
                    for row in entity_rows
                ],
                template="(%s,%s,%s,%s::text[],%s,%s)",
                page_size=100,
            )

            values = []
            for award in award_rows:
                cur.execute(
                    "SELECT entity_id FROM capture.entities WHERE normalized_legal_name = capture.normalize_entity_name(%s) LIMIT 1;",
                    (award["prime_name"],),
                )
                entity_id = cur.fetchone()[0]
                values.append(
                    (
                        award["contract_award_unique_key"],
                        award["piid"],
                        award["referenced_idv_piid"],
                        entity_id,
                        award["award_number"],
                        award["award_type"],
                        award["title"],
                        award["description"],
                        award["signed_date"],
                        award["period_of_performance_start"],
                        award["period_of_performance_end"],
                        award["awarding_agency_name"],
                        award["awarding_agency_code"],
                        award["funding_agency_name"],
                        award["funding_agency_code"],
                        award["contracting_office_name"],
                        award["contracting_office_code"],
                        award["naics_code"],
                        award["psc_code"],
                        award["set_aside_code"],
                        award["total_obligation"],
                        award["current_total_value"],
                        award["potential_total_value"],
                        award["description_embedding"],
                        Json(award["source_payload"]),
                        datetime.now(timezone.utc),
                    )
                )

            execute_values(
                cur,
                """
                INSERT INTO capture.awards (
                  contract_award_unique_key, piid, referenced_idv_piid, prime_entity_id,
                  award_number, award_type, title, description, signed_date,
                  period_of_performance_start, period_of_performance_end,
                  awarding_agency_name, awarding_agency_code, funding_agency_name,
                  funding_agency_code, contracting_office_name, contracting_office_code,
                  naics_code, psc_code, set_aside_code, total_obligation,
                  current_total_value, potential_total_value, description_embedding,
                  source_payload, source_updated_at
                )
                VALUES %s
                ON CONFLICT (contract_award_unique_key)
                DO UPDATE SET
                  prime_entity_id = EXCLUDED.prime_entity_id,
                  award_type = EXCLUDED.award_type,
                  title = EXCLUDED.title,
                  description = EXCLUDED.description,
                  signed_date = EXCLUDED.signed_date,
                  period_of_performance_start = EXCLUDED.period_of_performance_start,
                  period_of_performance_end = EXCLUDED.period_of_performance_end,
                  awarding_agency_name = EXCLUDED.awarding_agency_name,
                  awarding_agency_code = EXCLUDED.awarding_agency_code,
                  funding_agency_name = EXCLUDED.funding_agency_name,
                  funding_agency_code = EXCLUDED.funding_agency_code,
                  naics_code = EXCLUDED.naics_code,
                  psc_code = EXCLUDED.psc_code,
                  total_obligation = EXCLUDED.total_obligation,
                  current_total_value = EXCLUDED.current_total_value,
                  potential_total_value = EXCLUDED.potential_total_value,
                  description_embedding = COALESCE(EXCLUDED.description_embedding, capture.awards.description_embedding),
                  source_payload = EXCLUDED.source_payload,
                  source_updated_at = EXCLUDED.source_updated_at,
                  updated_at = now();
                """,
                values,
                template="(%s,%s,%s,%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s)",
                page_size=100,
            )
    return len(records)


def normalize_usaspending_award(raw: Mapping[str, Any]) -> Dict[str, Any]:
    source = dict(raw)
    award_id = _first(source, "generated_internal_id", "generated_unique_award_id", "Award ID", "award_id") or _fingerprint(source)
    piid = _first(source, "piid", "Award ID", "award_id") or award_id
    recipient_name = _first(source, "Recipient Name", "recipient_name", "prime_award_recipient_name") or "Unknown USAspending Recipient"
    description = _first(source, "Description", "description", "Award Description") or _first(source, "Award Type", "type_description") or ""
    title = description[:180] if description else f"USAspending award {piid}"
    naics = _code(_first(source, "NAICS", "naics_code"), digits_only=True, max_len=6)
    psc = _code(_first(source, "PSC", "psc_code"), digits_only=False, max_len=4)
    funding_agency = _first(source, "Funding Agency", "funding_agency_name")
    awarding_agency = _first(source, "Awarding Agency", "awarding_agency_name")
    signed = _parse_date(_first(source, "Start Date", "start_date", "period_of_performance_start_date"))
    end = _parse_date(_first(source, "End Date", "end_date", "period_of_performance_current_end_date"))
    amount = _money(_first(source, "Award Amount", "award_amount", "generated_pragmatic_obligation"))
    embedding_text = " ".join(str(value) for value in [title, description, recipient_name, naics, psc, funding_agency, awarding_agency] if value)
    embedding = _vector_literal(
        _deterministic_text_embedding(
            embedding_text or recipient_name,
            {"naics_code": naics, "psc_code": psc, "funding_agency_code": None, "set_aside_code": None},
        )
    )
    return {
        "entity": {
            "legal_name": recipient_name,
            "canonical_uei": _code(_first(source, "recipient_uei", "Recipient UEI"), digits_only=False, max_len=12),
            "cage_code": _code(_first(source, "recipient_cage_code", "CAGE Code"), digits_only=False, max_len=5),
            "source_payload": {"usaspending": source},
        },
        "award": {
            "contract_award_unique_key": str(award_id),
            "piid": str(piid),
            "referenced_idv_piid": _first(source, "parent_award_piid", "referenced_idv_piid"),
            "prime_name": recipient_name,
            "award_number": str(piid),
            "award_type": _first(source, "Award Type", "type_description"),
            "title": title,
            "description": description,
            "signed_date": signed,
            "period_of_performance_start": signed,
            "period_of_performance_end": end,
            "awarding_agency_name": awarding_agency,
            "awarding_agency_code": _first(source, "awarding_toptier_agency_code"),
            "funding_agency_name": funding_agency,
            "funding_agency_code": _first(source, "funding_toptier_agency_code"),
            "contracting_office_name": _first(source, "contracting_office_name"),
            "contracting_office_code": _first(source, "contracting_office_code"),
            "naics_code": naics,
            "psc_code": psc,
            "set_aside_code": _first(source, "type_set_aside"),
            "total_obligation": amount,
            "current_total_value": amount,
            "potential_total_value": amount,
            "description_embedding": embedding,
            "source_payload": {"source_system": "USAspending", "raw": source},
        },
    }


def update_data_freshness(record_count: int) -> None:
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
                VALUES (
                  'USAspending', 'Contract Awards', 'live_api', now(), now(), 'ready',
                  %(record_count)s, 24, %(source_url)s,
                  'Live USAspending Advanced Award Search records normalized into capture.awards.'
                )
                ON CONFLICT (source_system, dataset_name)
                DO UPDATE SET
                  source_mode = 'live_api',
                  last_successful_sync_at = EXCLUDED.last_successful_sync_at,
                  last_attempted_sync_at = EXCLUDED.last_attempted_sync_at,
                  sync_status = 'ready',
                  record_count = capture.data_freshness.record_count + EXCLUDED.record_count,
                  source_url = EXCLUDED.source_url,
                  notes = EXCLUDED.notes,
                  updated_at = now();
                """,
                {"record_count": record_count, "source_url": DEFAULT_ENDPOINT},
            )


def _invoke_upsert_lambda(function_name: str, rows: List[Mapping[str, Any]], config: Mapping[str, Any]) -> int:
    import boto3
    from botocore.config import Config

    payload = {
        "mode": "upsert_usaspending_awards",
        "records": rows,
        "source_url": config["endpoint"],
    }
    response = boto3.client("lambda", config=Config(connect_timeout=3, read_timeout=30, retries={"max_attempts": 2})).invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"),
    )
    response_payload = json.loads(response["Payload"].read().decode("utf-8") or "{}")
    if response.get("FunctionError"):
        raise USAspendingIngestError(f"USAspending upsert Lambda failed: {json.dumps(response_payload, default=str)[:1000]}")
    return int(response_payload.get("writtenRecords") or 0)


def _http_post_json(endpoint: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "GovConCaptureOS/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise USAspendingIngestError(f"USAspending request failed with HTTP {exc.code}: {body[:500]}") from exc


def _first(source: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = source.get(key)
        if value not in (None, "", "null"):
            return str(value).strip()
    return None


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _code(value: Optional[str], digits_only: bool, max_len: int) -> Optional[str]:
    if not value:
        return None
    cleaned = "".join(ch for ch in str(value).upper().strip() if ch.isalnum())
    if digits_only:
        cleaned = "".join(ch for ch in cleaned if ch.isdigit())
    return cleaned[:max_len] or None


def _money(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(Decimal(str(value).replace(",", "").replace("$", "")).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _fingerprint(source: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _lambda_time_available(context: Any, reserve_seconds: float) -> bool:
    if context is None or not hasattr(context, "get_remaining_time_in_millis"):
        return True
    return context.get_remaining_time_in_millis() / 1000.0 > reserve_seconds
