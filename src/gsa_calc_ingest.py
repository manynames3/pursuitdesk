from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import statistics
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

DEFAULT_ENDPOINT = "https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/"
DEFAULT_PAGE_SIZE = min(max(int(os.getenv("GSA_CALC_PAGE_SIZE", "100")), 1), 300)
DEFAULT_MAX_PAGES = min(max(int(os.getenv("GSA_CALC_MAX_PAGES", "2")), 1), 20)
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("GSA_CALC_REQUEST_TIMEOUT_SECONDS", "20"))
DEFAULT_KEYWORDS = [
    "program manager",
    "project manager",
    "business analyst",
    "systems engineer",
    "data scientist",
    "cloud architect",
    "cyber security",
    "devsecops",
    "logistics analyst",
    "construction manager",
    "estimator",
]


class GSACalcIngestError(Exception):
    pass


def lambda_handler(event: Mapping[str, Any], context: Any) -> Dict[str, Any]:
    if event.get("mode") == "upsert_gsa_calc_labor_rates":
        return upsert_gsa_calc_labor_rates_event(event)
    return ingest_gsa_calc_labor_rates_event(event, context=context)


def ingest_gsa_calc_labor_rates_event(event: Mapping[str, Any], context: Any = None) -> Dict[str, Any]:
    body = dict(event)
    dry_run = _truthy(body.get("dry_run", False))
    upsert_lambda_name = body.get("upsert_lambda_name") or os.getenv("GSA_CALC_UPSERT_LAMBDA_NAME")
    if not upsert_lambda_name and not dry_run:
        raise GSACalcIngestError("Set GSA_CALC_UPSERT_LAMBDA_NAME or pass upsert_lambda_name unless dry_run=true.")

    config = _build_request_config(body)
    fetched_by_id: Dict[str, Dict[str, Any]] = {}

    for keyword in config["keywords"]:
        for page in range(1, int(config["max_pages"]) + 1):
            if not _lambda_time_available(context, reserve_seconds=5):
                break
            response = _http_get_json(_build_url(config, keyword=keyword, page=page))
            rows = _extract_hits(response)
            if not rows:
                break
            for row in rows:
                source = _source(row)
                source["_captureos_keyword"] = keyword
                fetched_by_id[_record_key(row, source)] = source
            if len(rows) < int(config["page_size"]):
                break

    records = list(fetched_by_id.values())
    written = 0 if dry_run else _invoke_upsert_lambda(str(upsert_lambda_name), records, config)
    return {
        "sourceSystem": "GSA CALC+",
        "dataset": "Labor Rate Benchmarks",
        "fetchedRecords": len(records),
        "writtenRecords": written,
        "dryRun": dry_run,
        "records": records[:25] if dry_run else [],
    }


def upsert_gsa_calc_labor_rates_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    records = event.get("records") or []
    if not isinstance(records, list):
        raise GSACalcIngestError("records must be a list.")
    written = upsert_calc_labor_rates_to_database(records)
    live_count = count_live_gsa_calc_rates()
    update_data_freshness(live_count)
    return {"normalizedRecords": len(records), "writtenRecords": written, "liveCalcRateRecords": live_count}


def _build_request_config(body: Mapping[str, Any]) -> Dict[str, Any]:
    keywords = _string_list(body.get("keywords") or os.getenv("GSA_CALC_KEYWORDS"))
    if not keywords:
        keywords = DEFAULT_KEYWORDS
    return {
        "endpoint": str(body.get("endpoint") or os.getenv("GSA_CALC_ENDPOINT", DEFAULT_ENDPOINT)),
        "keywords": keywords[:25],
        "filters": _string_list(body.get("filters") or body.get("filter") or ["price_range:15,500", "experience_range:0,45"]),
        "page_size": min(max(int(body.get("page_size") or DEFAULT_PAGE_SIZE), 1), 300),
        "max_pages": min(max(int(body.get("max_pages") or DEFAULT_MAX_PAGES), 1), 20),
        "ordering": str(body.get("ordering") or "current_price"),
        "sort": str(body.get("sort") or "asc"),
    }


def _build_url(config: Mapping[str, Any], keyword: str, page: int) -> str:
    query: List[Tuple[str, str]] = [
        ("keyword", keyword),
        ("page", str(page)),
        ("page_size", str(config["page_size"])),
        ("ordering", str(config["ordering"])),
        ("sort", str(config["sort"])),
    ]
    query.extend(("filter", item) for item in config.get("filters", []))
    return f"{config['endpoint']}?{urllib.parse.urlencode(query)}"


def _http_get_json(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GovConCaptureOS/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise GSACalcIngestError(f"GSA CALC+ request failed with HTTP {exc.code}: {body[:500]}") from exc


def upsert_calc_labor_rates_to_database(records: List[Mapping[str, Any]]) -> int:
    rows = _aggregate_rate_rows(records)
    if not rows:
        return 0
    import psycopg2
    from psycopg2.extras import Json, execute_values

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise GSACalcIngestError("DATABASE_URL must be configured.")

    values = [
        (
            row["labor_rate_id"],
            row["labor_category"],
            row["normalized_labor_category"],
            row["education_level"],
            row["min_years_experience"],
            row["site"],
            row["schedule"],
            row.get("naics_code"),
            row.get("psc_code"),
            row["ceiling_hourly_rate"],
            row["percentile_50_hourly_rate"],
            row["percentile_75_hourly_rate"],
            row["source"],
            Json(row["source_payload"]),
            row["source_updated_at"],
        )
        for row in rows
    ]

    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO capture.calc_labor_rates (
                  labor_rate_id, labor_category, normalized_labor_category, education_level,
                  min_years_experience, site, schedule, naics_code, psc_code, ceiling_hourly_rate,
                  percentile_50_hourly_rate, percentile_75_hourly_rate, source, source_payload,
                  source_updated_at
                )
                VALUES %s
                ON CONFLICT (
                  normalized_labor_category,
                  education_level,
                  min_years_experience,
                  site,
                  schedule,
                  (coalesce(naics_code, ''::character varying)),
                  (coalesce(psc_code, ''::character varying))
                )
                DO UPDATE SET
                  labor_category = EXCLUDED.labor_category,
                  ceiling_hourly_rate = EXCLUDED.ceiling_hourly_rate,
                  percentile_50_hourly_rate = EXCLUDED.percentile_50_hourly_rate,
                  percentile_75_hourly_rate = EXCLUDED.percentile_75_hourly_rate,
                  source = EXCLUDED.source,
                  source_payload = EXCLUDED.source_payload,
                  source_updated_at = EXCLUDED.source_updated_at,
                  updated_at = now();
                """,
                values,
                template="(%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                page_size=100,
            )
    return len(rows)


def _aggregate_rate_rows(records: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str, int, str, str], Dict[str, Any]] = {}
    for raw in records:
        price = _money(raw.get("current_price"))
        if price is None:
            continue
        labor_category = _clean_text(raw.get("labor_category")) or "Unspecified Labor Category"
        normalized = _canonical_labor_category(labor_category)
        education = _education_level(raw.get("education_level"))
        experience = _int_value(raw.get("min_years_experience"), default=0)
        site = _site(raw.get("worksite"))
        schedule = _clean_text(raw.get("schedule")) or "GSA MAS"
        key = (normalized, education, experience, site, schedule)
        group = groups.setdefault(
            key,
            {
                "labor_category": _title_category(normalized),
                "normalized_labor_category": normalized,
                "education_level": education,
                "min_years_experience": experience,
                "site": site,
                "schedule": schedule,
                "prices": [],
                "sample_ids": [],
                "sample_vendors": [],
                "keywords": set(),
                "latest_source_updated_at": None,
            },
        )
        group["prices"].append(price)
        if raw.get("id") is not None:
            group["sample_ids"].append(str(raw.get("id")))
        if raw.get("vendor_name"):
            group["sample_vendors"].append(str(raw.get("vendor_name")))
        if raw.get("_captureos_keyword"):
            group["keywords"].add(str(raw.get("_captureos_keyword")))
        source_updated_at = _parse_datetime(raw.get("_timestamp"))
        if source_updated_at and (not group["latest_source_updated_at"] or source_updated_at > group["latest_source_updated_at"]):
            group["latest_source_updated_at"] = source_updated_at

    rows: List[Dict[str, Any]] = []
    for key, group in groups.items():
        prices = sorted(group["prices"])
        labor_rate_id = _stable_uuid(f"gsa-calc:{'|'.join(str(part) for part in key)}")
        rows.append(
            {
                "labor_rate_id": labor_rate_id,
                "labor_category": group["labor_category"],
                "normalized_labor_category": group["normalized_labor_category"],
                "education_level": group["education_level"],
                "min_years_experience": group["min_years_experience"],
                "site": group["site"],
                "schedule": group["schedule"],
                "naics_code": None,
                "psc_code": None,
                "ceiling_hourly_rate": _decimal_string(max(prices)),
                "percentile_50_hourly_rate": _decimal_string(statistics.median(prices)),
                "percentile_75_hourly_rate": _decimal_string(_percentile(prices, 0.75)),
                "source": "GSA CALC+ live API",
                "source_payload": {
                    "source_system": "GSA CALC+",
                    "source_url": DEFAULT_ENDPOINT,
                    "sample_size": len(prices),
                    "sample_record_ids": group["sample_ids"][:20],
                    "sample_vendors": sorted(set(group["sample_vendors"]))[:10],
                    "keywords": sorted(group["keywords"]),
                },
                "source_updated_at": group["latest_source_updated_at"] or datetime.now(timezone.utc),
            }
        )
    return rows


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
                  'GSA CALC+', 'Labor Rate Benchmarks', 'live_api', now(), now(), 'ready',
                  %(record_count)s, 24, %(source_url)s,
                  'Live GSA CALC+ ceiling-rate benchmarks grouped for opportunity pricing support.'
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


def count_live_gsa_calc_rates() -> int:
    import psycopg2

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return 0
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)::int
                FROM capture.calc_labor_rates
                WHERE source_payload->>'source_system' = 'GSA CALC+';
                """
            )
            return int(cur.fetchone()[0])


def _invoke_upsert_lambda(function_name: str, rows: List[Mapping[str, Any]], config: Mapping[str, Any]) -> int:
    import boto3
    from botocore.config import Config

    payload = {
        "mode": "upsert_gsa_calc_labor_rates",
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
        raise GSACalcIngestError(f"GSA CALC+ upsert Lambda failed: {json.dumps(response_payload, default=str)[:1000]}")
    return int(response_payload.get("writtenRecords") or 0)


def _extract_hits(response: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    hits = response.get("hits")
    if not isinstance(hits, Mapping):
        return []
    rows = hits.get("hits")
    return rows if isinstance(rows, list) else []


def _source(row: Mapping[str, Any]) -> Dict[str, Any]:
    source = row.get("_source")
    if isinstance(source, Mapping):
        return dict(source)
    return dict(row)


def _record_key(row: Mapping[str, Any], source: Mapping[str, Any]) -> str:
    return str(source.get("id") or row.get("_id") or hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode("utf-8")).hexdigest())


def _canonical_labor_category(value: str) -> str:
    lowered = value.lower()
    patterns = {
        "construction manager": ("construction manager", "project superintendent", "foreman"),
        "cost estimator": ("cost estimator", "estimator"),
        "program manager": ("program manager", "project manager", "pmp"),
        "cloud architect": ("cloud architect", "solutions architect", "enterprise architect"),
        "cyber security engineer": ("cyber", "security engineer", "security analyst", "soc analyst"),
        "data scientist": ("data scientist", "machine learning", "ai/ml"),
        "devsecops engineer": ("devsecops", "devops", "platform engineer"),
        "systems engineer": ("systems engineer", "system engineer", "systems integration"),
        "logistics analyst": ("logistics", "supply chain", "sustainment"),
        "business analyst": ("business analyst", "requirements analyst", "management analyst"),
    }
    for category, needles in patterns.items():
        if any(needle in lowered for needle in needles):
            return category
    return " ".join(value.lower().replace("/", " ").replace("-", " ").split())[:120] or "unspecified labor category"


def _title_category(value: str) -> str:
    overrides = {"devsecops": "DevSecOps", "ai": "AI"}
    return " ".join(overrides.get(part, part.capitalize()) for part in value.split())


def _education_level(value: Any) -> str:
    text = _clean_text(value).upper()
    mapping = {
        "AA": "Associates",
        "ASSOCIATES": "Associates",
        "BA": "Bachelors",
        "BACHELORS": "Bachelors",
        "HS": "High School",
        "HIGH SCHOOL": "High School",
        "MA": "Masters",
        "MASTERS": "Masters",
        "PHD": "PhD",
        "NONE": "None",
        "N/A": "None",
    }
    return mapping.get(text, _clean_text(value) or "Not Specified")


def _site(value: Any) -> str:
    text = _clean_text(value).lower()
    if "remote" in text or "contractor" in text:
        return "Remote"
    if "oconus" in text:
        return "OCONUS"
    return "CONUS"


def _money(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        amount = Decimal(str(value).replace(",", "").replace("$", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount > 0 else None


def _decimal_string(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _percentile(values: List[Decimal], quantile: float) -> Decimal:
    if not values:
        return Decimal("0.00")
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[int(index)]
    return values[lower] + (values[upper] - values[lower]) * Decimal(str(index - lower))


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _int_value(value: Any, default: int) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _string_list(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


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
