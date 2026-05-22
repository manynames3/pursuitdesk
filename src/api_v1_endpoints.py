from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Generator, Iterable, List, Mapping, Optional
from uuid import UUID

import psycopg2
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Request, status
from psycopg2.extras import RealDictCursor, register_default_jsonb
from psycopg2.pool import ThreadedConnectionPool

try:
    from .partner_matching import find_best_teaming_partners
except ImportError:  # pragma: no cover - supports direct module execution during local development.
    from partner_matching import find_best_teaming_partners


DATABASE_URL = os.getenv("DATABASE_URL")
POOL_MIN_CONN = int(os.getenv("DB_POOL_MIN_CONN", "1"))
POOL_MAX_CONN = int(os.getenv("DB_POOL_MAX_CONN", "8"))
ACTIVE_QUERY_TIMEOUT_MS = int(os.getenv("ACTIVE_QUERY_TIMEOUT_MS", "900"))
ANALYSIS_QUERY_TIMEOUT_MS = int(os.getenv("ANALYSIS_QUERY_TIMEOUT_MS", "2500"))

router = APIRouter(prefix="/api/v1", tags=["GovCon CaptureOS v1"])
app = FastAPI(title="GovCon CaptureOS Presentation API", version="1.0.0")

_pool_lock = threading.Lock()
_pool: Optional[ThreadedConnectionPool] = None


def get_db_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not configured.")
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(POOL_MIN_CONN, POOL_MAX_CONN, dsn=DATABASE_URL, connect_timeout=5)
    return _pool


def get_db_connection() -> Generator[Any, None, None]:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        register_default_jsonb(conn, loads=json.loads)
        yield conn
    finally:
        if not conn.closed:
            conn.rollback()
        pool.putconn(conn)


@router.get("/opportunities/active")
def list_active_opportunities(
    min_value: Optional[Decimal] = Query(None, ge=0),
    max_value: Optional[Decimal] = Query(None, ge=0),
    naics_codes: Optional[List[str]] = Query(None, description="Repeat or comma-separate NAICS codes."),
    psc_codes: Optional[List[str]] = Query(None, description="Repeat or comma-separate PSC codes."),
    q: Optional[str] = Query(None, min_length=2, max_length=180),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn=Depends(get_db_connection),
) -> Dict[str, Any]:
    if min_value is not None and max_value is not None and min_value > max_value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="min_value cannot exceed max_value.")

    naics = _clean_code_list(naics_codes, allowed_lengths={2, 3, 4, 5, 6}, digits_only=True)
    psc = _clean_code_list(psc_codes, allowed_lengths={1, 2, 3, 4}, digits_only=False)
    search_text = q.strip() if q else None

    sql = """
    WITH filtered AS (
      SELECT
        o.opportunity_id,
        o.notice_id,
        o.solicitation_number,
        o.title,
        o.opportunity_type,
        o.posted_at,
        o.response_deadline,
        o.naics_code,
        o.psc_code,
        o.set_aside_code,
        o.set_aside_description,
        o.funding_agency_name,
        o.funding_agency_code,
        o.estimated_value_min,
        o.estimated_value_max,
        o.currency_code,
        o.ui_link,
        (
          CASE WHEN o.sow_embedding IS NOT NULL THEN 0.28 ELSE 0 END
          + CASE WHEN o.response_deadline IS NOT NULL AND o.response_deadline >= now() THEN 0.22 ELSE 0 END
          + CASE WHEN o.estimated_value_max IS NOT NULL OR o.estimated_value_min IS NOT NULL THEN 0.14 ELSE 0 END
          + CASE WHEN %(naics_codes)s::text[] IS NOT NULL AND o.naics_code = ANY(%(naics_codes)s::text[]) THEN 0.18 ELSE 0 END
          + CASE WHEN %(psc_codes)s::text[] IS NOT NULL AND o.psc_code = ANY(%(psc_codes)s::text[]) THEN 0.12 ELSE 0 END
          + CASE
              WHEN o.posted_at IS NULL THEN 0.03
              ELSE LEAST(0.06, GREATEST(0, 0.06 - EXTRACT(day FROM now() - o.posted_at) * 0.002))
            END
        )::double precision AS dashboard_relevance_score,
        COUNT(*) OVER ()::int AS total_count
      FROM capture.opportunities o
      WHERE o.active_status = 'active'
        AND (o.response_deadline IS NULL OR o.response_deadline >= now())
        AND (%(min_value)s::numeric IS NULL OR o.estimated_value_max IS NULL OR o.estimated_value_max >= %(min_value)s::numeric)
        AND (%(max_value)s::numeric IS NULL OR o.estimated_value_min IS NULL OR o.estimated_value_min <= %(max_value)s::numeric)
        AND (%(naics_codes)s::text[] IS NULL OR o.naics_code = ANY(%(naics_codes)s::text[]))
        AND (%(psc_codes)s::text[] IS NULL OR o.psc_code = ANY(%(psc_codes)s::text[]))
        AND (
          %(search_text)s::text IS NULL
          OR o.search_tsv @@ websearch_to_tsquery('english', %(search_text)s::text)
          OR o.title ILIKE ('%%' || %(search_text)s::text || '%%')
        )
    )
    SELECT *
    FROM filtered
    ORDER BY dashboard_relevance_score DESC, response_deadline NULLS LAST, posted_at DESC NULLS LAST
    LIMIT %(limit)s
    OFFSET %(offset)s;
    """
    params = {
        "min_value": min_value,
        "max_value": max_value,
        "naics_codes": naics or None,
        "psc_codes": psc or None,
        "search_text": search_text,
        "limit": limit,
        "offset": offset,
    }

    with _query_timeout(conn, ACTIVE_QUERY_TIMEOUT_MS), conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    total = rows[0]["total_count"] if rows else 0
    return {
        "pagination": {"limit": limit, "offset": offset, "total": total},
        "filters": {
            "min_value": _json_safe(min_value),
            "max_value": _json_safe(max_value),
            "naics_codes": naics,
            "psc_codes": psc,
            "q": search_text,
        },
        "items": [_opportunity_row(row) for row in rows],
    }


@router.get("/capture-analysis/{opportunity_id}")
def get_capture_analysis(
    request: Request,
    opportunity_id: str = Path(..., min_length=1, max_length=128),
    our_entity_id: Optional[UUID] = Query(None),
    conn=Depends(get_db_connection),
) -> Dict[str, Any]:
    try:
        with _query_timeout(conn, ANALYSIS_QUERY_TIMEOUT_MS):
            analysis = find_best_teaming_partners(
                conn,
                opportunity_id=opportunity_id,
                our_entity_id=str(our_entity_id) if our_entity_id else None,
                historical_limit=75,
                top_primes=3,
                subs_per_prime=5,
                team_sub_limit=5,
            )
            benchmarks = _fetch_calc_benchmarks(conn, opportunity_id=opportunity_id, max_rows=12)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except psycopg2.errors.QueryCanceled as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Capture analysis query timed out.") from exc

    response = _json_safe(analysis)
    response["calc_plus_benchmarks"] = benchmarks
    response["metadata"] = {
        "api_version": "v1",
        "request_id": request.headers.get("x-request-id"),
        "limits": {"top_primes": 3, "top_subcontractors": 5, "calc_benchmarks": 12},
    }
    return response


def _fetch_calc_benchmarks(conn, opportunity_id: str, max_rows: int) -> List[Dict[str, Any]]:
    target_predicate, target_value = _opportunity_predicate(opportunity_id)
    target_sql = f"""
      SELECT opportunity_id, title, sow_text, naics_code, psc_code
      FROM capture.opportunities
      WHERE {target_predicate}
      LIMIT 1;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(target_sql, target_value)
        opportunity = cur.fetchone()
    if opportunity is None:
        raise ValueError(f"Opportunity was not found: {opportunity_id}")

    required_categories = _extract_labor_categories(
        f"{opportunity.get('title') or ''} {opportunity.get('sow_text') or ''}"
    )
    benchmark_sql = """
    SELECT
      labor_rate_id::text,
      labor_category,
      normalized_labor_category,
      education_level,
      min_years_experience,
      site,
      schedule,
      naics_code,
      psc_code,
      ceiling_hourly_rate,
      percentile_50_hourly_rate,
      percentile_75_hourly_rate,
      source_updated_at,
      (
        CASE WHEN normalized_labor_category = ANY(%(required_categories)s::text[]) THEN 0.55 ELSE 0 END
        + CASE WHEN naics_code IS NOT NULL AND naics_code = %(naics_code)s THEN 0.25 ELSE 0 END
        + CASE WHEN psc_code IS NOT NULL AND psc_code = %(psc_code)s THEN 0.15 ELSE 0 END
        + CASE WHEN site = 'CONUS' THEN 0.05 ELSE 0 END
      )::double precision AS benchmark_match_score
    FROM capture.calc_labor_rates
    WHERE
      normalized_labor_category = ANY(%(required_categories)s::text[])
      OR (%(naics_code)s IS NOT NULL AND naics_code = %(naics_code)s)
      OR (%(psc_code)s IS NOT NULL AND psc_code = %(psc_code)s)
    ORDER BY benchmark_match_score DESC, ceiling_hourly_rate DESC
    LIMIT %(max_rows)s;
    """
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                benchmark_sql,
                {
                    "required_categories": required_categories or _default_labor_categories(opportunity),
                    "naics_code": opportunity.get("naics_code"),
                    "psc_code": opportunity.get("psc_code"),
                    "max_rows": max_rows,
                },
            )
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return []
        raise

    return [_json_safe(row) for row in rows]


def _extract_labor_categories(text: str) -> List[str]:
    lowered = text.lower()
    category_patterns = {
        "program manager": ("program manager", "project manager", "pmp"),
        "cloud architect": ("cloud architect", "aws architect", "cloud migration"),
        "cyber security engineer": ("cyber", "zero trust", "soc analyst", "security engineer"),
        "data scientist": ("data scientist", "machine learning", "ai/ml", "predictive analytics"),
        "devsecops engineer": ("devsecops", "ci/cd", "platform engineer"),
        "systems engineer": ("systems engineer", "systems integration", "c5isr"),
        "logistics analyst": ("logistics", "sustainment", "supply chain"),
        "business analyst": ("business analyst", "requirements analyst"),
    }
    detected = [
        category
        for category, patterns in category_patterns.items()
        if any(pattern in lowered for pattern in patterns)
    ]
    return detected[:8]


def _default_labor_categories(opportunity: Mapping[str, Any]) -> List[str]:
    naics = opportunity.get("naics_code")
    psc = opportunity.get("psc_code")
    if naics in {"541511", "541512", "541519"} or psc in {"DA01", "DB10", "R425"}:
        return ["program manager", "cloud architect", "cyber security engineer", "devsecops engineer"]
    if naics == "541715" or psc in {"AC12", "AJ11"}:
        return ["program manager", "data scientist", "systems engineer"]
    if naics in {"541330", "541614"} or psc in {"R706", "J099"}:
        return ["program manager", "systems engineer", "logistics analyst"]
    return ["program manager", "business analyst", "systems engineer"]


def _opportunity_predicate(opportunity_id: str) -> tuple[str, Dict[str, str]]:
    try:
        parsed = UUID(str(opportunity_id))
        return "opportunity_id = %(opportunity_uuid)s::uuid", {"opportunity_uuid": str(parsed)}
    except ValueError:
        return "notice_id = %(notice_id)s", {"notice_id": opportunity_id}


@contextmanager
def _query_timeout(conn, timeout_ms: int):
    with conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = %s;", (f"{timeout_ms}ms",))
    yield


def _clean_code_list(
    values: Optional[Iterable[str]],
    allowed_lengths: set[int],
    digits_only: bool,
) -> List[str]:
    if not values:
        return []
    cleaned: List[str] = []
    for raw in values:
        for part in str(raw).split(","):
            code = part.strip().upper()
            if not code:
                continue
            if len(code) not in allowed_lengths:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid code length: {code}")
            if digits_only and not code.isdigit():
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid numeric code: {code}")
            if code not in cleaned:
                cleaned.append(code)
    return cleaned


def _opportunity_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "opportunity_id": str(row["opportunity_id"]),
        "notice_id": row["notice_id"],
        "solicitation_number": row["solicitation_number"],
        "title": row["title"],
        "opportunity_type": row["opportunity_type"],
        "posted_at": _json_safe(row["posted_at"]),
        "response_deadline": _json_safe(row["response_deadline"]),
        "naics_code": row["naics_code"],
        "psc_code": row["psc_code"],
        "set_aside_code": row["set_aside_code"],
        "set_aside_description": row["set_aside_description"],
        "funding_agency_name": row["funding_agency_name"],
        "funding_agency_code": row["funding_agency_code"],
        "estimated_value_min": _json_safe(row["estimated_value_min"]),
        "estimated_value_max": _json_safe(row["estimated_value_max"]),
        "currency_code": row["currency_code"],
        "ui_link": row["ui_link"],
        "dashboard_relevance_score": round(float(row["dashboard_relevance_score"]), 4),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items() if key != "total_count"}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


app.include_router(router)
