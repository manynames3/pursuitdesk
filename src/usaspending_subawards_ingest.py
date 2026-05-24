from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

DEFAULT_ENDPOINT = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
DEFAULT_LIMIT = min(max(int(os.getenv("USASPENDING_SUBAWARDS_PAGE_LIMIT", "100")), 1), 100)
DEFAULT_MAX_PAGES = min(max(int(os.getenv("USASPENDING_SUBAWARDS_MAX_PAGES", "5")), 1), 25)
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("USASPENDING_SUBAWARDS_REQUEST_TIMEOUT_SECONDS", "20"))
CONTRACT_AWARD_TYPE_CODES = ["A", "B", "C", "D"]
SUBAWARD_FIELDS = [
    "Prime Award ID",
    "Prime Recipient Name",
    "Sub-Award ID",
    "Sub-Awardee Name",
    "Sub-Award Date",
    "Sub-Award Amount",
    "Awarding Agency",
    "Funding Agency",
    "Description",
    "NAICS",
    "PSC",
]


class USAspendingSubawardIngestError(Exception):
    pass


def lambda_handler(event: Mapping[str, Any], context: Any) -> Dict[str, Any]:
    if event.get("mode") == "upsert_usaspending_subawards":
        return upsert_usaspending_subawards_event(event)
    return ingest_usaspending_subawards_event(event, context=context)


def ingest_usaspending_subawards_event(event: Mapping[str, Any], context: Any = None) -> Dict[str, Any]:
    body = dict(event)
    dry_run = _truthy(body.get("dry_run", False))
    upsert_lambda_name = body.get("upsert_lambda_name") or os.getenv("USASPENDING_SUBAWARDS_UPSERT_LAMBDA_NAME")
    if not upsert_lambda_name and not dry_run:
        raise USAspendingSubawardIngestError(
            "Set USASPENDING_SUBAWARDS_UPSERT_LAMBDA_NAME or pass upsert_lambda_name unless dry_run=true."
        )

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
            written += _invoke_upsert_lambda(str(upsert_lambda_name), rows, config)
        if not response.get("page_metadata", {}).get("hasNext"):
            break
        if not _lambda_time_available(context, reserve_seconds=5):
            break

    return {
        "sourceSystem": "FSRS",
        "dataset": "Subaward Reporting",
        "sourceVia": "USAspending",
        "fetchedRecords": fetched,
        "writtenRecords": written,
        "dryRun": dry_run,
        "records": dry_run_records,
    }


def upsert_usaspending_subawards_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    records = event.get("records") or []
    if not isinstance(records, list):
        raise USAspendingSubawardIngestError("records must be a list.")
    written = upsert_subawards_to_database(records)
    live_count = count_live_fsrs_subawards()
    update_data_freshness(live_count)
    return {"normalizedRecords": len(records), "writtenRecords": written, "liveSubawardRecords": live_count}


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
            "fields": body.get("fields") or SUBAWARD_FIELDS,
            "sort": body.get("sort") or "Sub-Award Amount",
            "order": body.get("order") or "desc",
            "limit": min(max(int(body.get("limit") or DEFAULT_LIMIT), 1), 100),
            "spending_level": "subawards",
        },
    }


def upsert_subawards_to_database(records: List[Mapping[str, Any]]) -> int:
    if not records:
        return 0
    import psycopg2
    from psycopg2.extras import Json, execute_values

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise USAspendingSubawardIngestError("DATABASE_URL must be configured.")

    normalized_rows = [normalize_usaspending_subaward(raw) for raw in records]
    normalized_rows = [row for row in normalized_rows if row["prime"]["legal_name"] != row["subcontractor"]["legal_name"]]
    if not normalized_rows:
        return 0

    entities_by_name: Dict[str, Dict[str, Any]] = {}
    for row in normalized_rows:
        entities_by_name[_entity_batch_key(row["prime"]["legal_name"])] = row["prime"]
        entities_by_name[_entity_batch_key(row["subcontractor"]["legal_name"])] = row["subcontractor"]

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
                  updated_at = now();
                """,
                [
                    (
                        row["legal_name"],
                        row.get("canonical_uei"),
                        row.get("cage_code"),
                        [],
                        row["source_system"],
                        Json(row["source_payload"]),
                    )
                    for row in entities_by_name.values()
                ],
                template="(%s,%s,%s,%s::text[],%s,%s)",
                page_size=100,
            )

            names = sorted({row["prime"]["legal_name"] for row in normalized_rows} | {row["subcontractor"]["legal_name"] for row in normalized_rows})
            cur.execute(
                """
                WITH entity_names(name) AS (
                  SELECT unnest(%(names)s::text[])
                )
                SELECT DISTINCT ON (name)
                  name,
                  e.entity_id::text AS entity_id
                FROM entity_names
                JOIN capture.entities e
                  ON e.normalized_legal_name = capture.normalize_entity_name(name)
                ORDER BY name, e.updated_at DESC;
                """,
                {"names": names},
            )
            entity_id_by_name = {str(row[0]): str(row[1]) for row in cur.fetchall()}

            award_rows = _parent_award_rows(normalized_rows, entity_id_by_name)
            execute_values(
                cur,
                """
                INSERT INTO capture.awards (
                  contract_award_unique_key, piid, prime_entity_id, award_number, award_type,
                  title, description, awarding_agency_name, funding_agency_name, naics_code,
                  psc_code, source_payload, source_updated_at
                )
                VALUES %s
                ON CONFLICT (contract_award_unique_key)
                DO UPDATE SET
                  prime_entity_id = COALESCE(capture.awards.prime_entity_id, EXCLUDED.prime_entity_id),
                  awarding_agency_name = COALESCE(capture.awards.awarding_agency_name, EXCLUDED.awarding_agency_name),
                  funding_agency_name = COALESCE(capture.awards.funding_agency_name, EXCLUDED.funding_agency_name),
                  naics_code = COALESCE(capture.awards.naics_code, EXCLUDED.naics_code),
                  psc_code = COALESCE(capture.awards.psc_code, EXCLUDED.psc_code),
                  source_payload = capture.awards.source_payload || EXCLUDED.source_payload,
                  updated_at = now();
                """,
                [
                    (
                        row["contract_award_unique_key"],
                        row["piid"],
                        row["prime_entity_id"],
                        row["award_number"],
                        row["award_type"],
                        row["title"],
                        row["description"],
                        row["awarding_agency_name"],
                        row["funding_agency_name"],
                        row["naics_code"],
                        row["psc_code"],
                        Json(row["source_payload"]),
                        row["source_updated_at"],
                    )
                    for row in award_rows
                ],
                template="(%s,%s,%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                page_size=100,
            )

            cur.execute(
                """
                WITH award_keys(key) AS (
                  SELECT unnest(%(keys)s::text[])
                )
                SELECT a.contract_award_unique_key, a.award_id::text
                FROM award_keys
                JOIN capture.awards a
                  ON a.contract_award_unique_key = award_keys.key;
                """,
                {"keys": [row["contract_award_unique_key"] for row in award_rows]},
            )
            award_id_by_key = {str(row[0]): str(row[1]) for row in cur.fetchall()}

            values_by_subaward_id: Dict[str, tuple[Any, ...]] = {}
            for row in normalized_rows:
                award_id = award_id_by_key.get(row["subaward"]["contract_award_unique_key"])
                prime_entity_id = entity_id_by_name.get(row["prime"]["legal_name"])
                subcontractor_entity_id = entity_id_by_name.get(row["subcontractor"]["legal_name"])
                if not award_id or not prime_entity_id or not subcontractor_entity_id or prime_entity_id == subcontractor_entity_id:
                    continue
                subaward = row["subaward"]
                values_by_subaward_id[subaward["sub_award_id"]] = (
                    subaward["sub_award_id"],
                    subaward["fsrs_report_id"],
                    award_id,
                    prime_entity_id,
                    subcontractor_entity_id,
                    None,
                    "{}",
                    1,
                    subaward["subaward_number"],
                    subaward["action_date"],
                    subaward["amount"],
                    subaward["description"],
                    subaward["naics_code"],
                    subaward["psc_code"],
                    Json(subaward["source_payload"]),
                    datetime.now(timezone.utc),
                )

            values = list(values_by_subaward_id.values())
            if not values:
                return 0

            execute_values(
                cur,
                """
                INSERT INTO capture.sub_awards (
                  sub_award_id, fsrs_report_id, award_id, prime_entity_id, subcontractor_entity_id,
                  parent_sub_award_id, relationship_path, tier, subaward_number, action_date, amount,
                  description, naics_code, psc_code, source_payload, source_updated_at
                )
                VALUES %s
                ON CONFLICT (sub_award_id)
                DO UPDATE SET
                  fsrs_report_id = EXCLUDED.fsrs_report_id,
                  action_date = EXCLUDED.action_date,
                  amount = EXCLUDED.amount,
                  description = EXCLUDED.description,
                  naics_code = EXCLUDED.naics_code,
                  psc_code = EXCLUDED.psc_code,
                  source_payload = EXCLUDED.source_payload,
                  source_updated_at = EXCLUDED.source_updated_at,
                  updated_at = now();
                """,
                values,
                template="(%s::uuid,%s,%s::uuid,%s::uuid,%s::uuid,%s::uuid,%s::uuid[],%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                page_size=100,
            )
    return len(values)


def normalize_usaspending_subaward(raw: Mapping[str, Any]) -> Dict[str, Any]:
    source = dict(raw)
    prime_key = _first(source, "prime_award_generated_internal_id", "generated_unique_award_id") or _fingerprint(source)
    prime_piid = _first(source, "Prime Award ID", "Award ID", "prime_award_id") or prime_key
    prime_name = _first(source, "Prime Recipient Name", "Recipient Name", "Prime Award Recipient Name") or "Unknown USAspending Prime"
    subcontractor_name = _first(source, "Sub-Awardee Name", "subawardee_name") or "Unknown USAspending Subcontractor"
    subaward_number = _first(source, "Sub-Award ID", "subaward_number", "internal_id") or _fingerprint(source)[:16]
    fsrs_report_id = _first(source, "FSRS Report ID", "Sub-Award ID", "internal_id") or subaward_number
    naics = _code(_first(source, "NAICS", "naics_code"), digits_only=True, max_len=6)
    psc = _code(_first(source, "PSC", "psc_code"), digits_only=False, max_len=4)
    description = _first(source, "Description", "Sub-Award Description") or f"Subaward to {subcontractor_name} under {prime_piid}"
    subaward_id = _stable_uuid(f"fsrs:{prime_key}:{fsrs_report_id}:{subaward_number}:{subcontractor_name}")
    source_payload = {"source_system": "FSRS", "source_via": "USAspending", "raw": source}
    return {
        "prime": {
            "legal_name": prime_name,
            "canonical_uei": None,
            "cage_code": None,
            "source_system": "USAspending",
            "source_payload": {"usaspending_fsrs_prime": source},
        },
        "subcontractor": {
            "legal_name": subcontractor_name,
            "canonical_uei": _code(_first(source, "Sub-Awardee UEI", "subawardee_uei"), digits_only=False, max_len=12),
            "cage_code": None,
            "source_system": "FSRS",
            "source_payload": {"fsrs_subawardee": source},
        },
        "subaward": {
            "sub_award_id": subaward_id,
            "contract_award_unique_key": str(prime_key),
            "fsrs_report_id": str(fsrs_report_id),
            "subaward_number": str(subaward_number),
            "action_date": _parse_date(_first(source, "Sub-Award Date", "subaward_date")),
            "amount": _money(_first(source, "Sub-Award Amount", "subaward_amount")),
            "description": description,
            "naics_code": naics,
            "psc_code": psc,
            "source_payload": source_payload,
        },
        "parent_award": {
            "contract_award_unique_key": str(prime_key),
            "piid": str(prime_piid),
            "award_number": str(prime_piid),
            "prime_name": prime_name,
            "award_type": "Contract",
            "title": f"Prime award {prime_piid}",
            "description": description,
            "awarding_agency_name": _first(source, "Awarding Agency", "awarding_agency_name"),
            "funding_agency_name": _first(source, "Funding Agency", "funding_agency_name"),
            "naics_code": naics,
            "psc_code": psc,
            "source_payload": {"source_system": "USAspending", "source_via": "FSRS subaward ingest", "raw": source},
        },
    }


def _parent_award_rows(rows: List[Mapping[str, Any]], entity_id_by_name: Mapping[str, str]) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        parent = row["parent_award"]
        prime_entity_id = entity_id_by_name.get(parent["prime_name"])
        if not prime_entity_id:
            continue
        by_key[parent["contract_award_unique_key"]] = {
            **parent,
            "prime_entity_id": prime_entity_id,
            "source_updated_at": datetime.now(timezone.utc),
        }
    return list(by_key.values())


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
                  'FSRS', 'Subaward Reporting', 'live_api', now(), now(), 'ready',
                  %(record_count)s, 24, %(source_url)s,
                  'Live FSRS-reported subawards surfaced through USAspending Advanced Award Search.'
                )
                ON CONFLICT (source_system, dataset_name)
                DO UPDATE SET
                  source_mode = 'live_api',
                  last_successful_sync_at = EXCLUDED.last_successful_sync_at,
                  last_attempted_sync_at = EXCLUDED.last_attempted_sync_at,
                  sync_status = 'ready',
                  record_count = EXCLUDED.record_count,
                  freshness_sla_hours = EXCLUDED.freshness_sla_hours,
                  source_url = EXCLUDED.source_url,
                  notes = EXCLUDED.notes,
                  updated_at = now();
                """,
                {"record_count": record_count, "source_url": DEFAULT_ENDPOINT},
            )


def count_live_fsrs_subawards() -> int:
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return 0
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)::int
                FROM capture.sub_awards
                WHERE source_payload->>'source_system' = 'FSRS'
                  AND source_payload->>'source_via' = 'USAspending';
                """
            )
            return int(cur.fetchone()[0])


def _invoke_upsert_lambda(function_name: str, rows: List[Mapping[str, Any]], config: Mapping[str, Any]) -> int:
    import boto3
    from botocore.config import Config

    payload = {
        "mode": "upsert_usaspending_subawards",
        "records": rows,
        "source_url": config["endpoint"],
    }
    response = boto3.client("lambda", config=Config(connect_timeout=3, read_timeout=45, retries={"max_attempts": 2})).invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"),
    )
    response_payload = json.loads(response["Payload"].read().decode("utf-8") or "{}")
    if response.get("FunctionError"):
        raise USAspendingSubawardIngestError(
            f"USAspending subaward upsert Lambda failed: {json.dumps(response_payload, default=str)[:1000]}"
        )
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
        raise USAspendingSubawardIngestError(f"USAspending subaward request failed with HTTP {exc.code}: {body[:500]}") from exc


def _first(source: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, Mapping):
            value = value.get("code") or value.get("name") or value.get("description")
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
        amount = Decimal(str(value).replace(",", "").replace("$", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return str(amount) if amount >= 0 else None


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


def _entity_batch_key(name: str) -> str:
    normalized = "".join(ch for ch in str(name).lower() if ch.isalnum())
    return normalized or "unknown"


def _fingerprint(source: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _stable_uuid(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"captureos:{value}"))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _lambda_time_available(context: Any, reserve_seconds: float) -> bool:
    if context is None or not hasattr(context, "get_remaining_time_in_millis"):
        return True
    return context.get_remaining_time_in_millis() / 1000.0 > reserve_seconds
