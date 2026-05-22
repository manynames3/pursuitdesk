from __future__ import annotations

import json
import hashlib
import hmac
import os
import urllib.error
import urllib.parse
import urllib.request
import threading
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Generator, Iterable, List, Mapping, Optional, Sequence
from uuid import UUID

import psycopg2
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor, register_default_jsonb
from psycopg2.pool import ThreadedConnectionPool

try:
    from .partner_matching import find_best_teaming_partners
    from .auth import AUTH_REQUIRED, authenticate_request
except ImportError:  # pragma: no cover - supports direct module execution during local development.
    from partner_matching import find_best_teaming_partners
    from auth import AUTH_REQUIRED, authenticate_request


DATABASE_URL = os.getenv("DATABASE_URL")
POOL_MIN_CONN = int(os.getenv("DB_POOL_MIN_CONN", "1"))
POOL_MAX_CONN = int(os.getenv("DB_POOL_MAX_CONN", "8"))
ACTIVE_QUERY_TIMEOUT_MS = int(os.getenv("ACTIVE_QUERY_TIMEOUT_MS", "900"))
ANALYSIS_QUERY_TIMEOUT_MS = int(os.getenv("ANALYSIS_QUERY_TIMEOUT_MS", "2500"))
DEFAULT_TENANT_SLUG = os.getenv("CAPTUREOS_DEFAULT_TENANT", "demo-growth")
DEFAULT_USER_EMAIL = os.getenv("CAPTUREOS_DEFAULT_USER", "capture.lead@example.com")
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "")
STRIPE_API_KEY_SECRET_ARN = os.getenv("STRIPE_API_KEY_SECRET_ARN", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_WEBHOOK_SECRET_ARN = os.getenv("STRIPE_WEBHOOK_SECRET_ARN", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
APP_PUBLIC_URL = os.getenv("APP_PUBLIC_URL", "https://govcon-captureos.pages.dev")

router = APIRouter(prefix="/api/v1", tags=["GovCon CaptureOS v1"])
app = FastAPI(title="GovCon CaptureOS Presentation API", version="1.0.0")

_pool_lock = threading.Lock()
_pool: Optional[ThreadedConnectionPool] = None


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("x-content-type-options", "nosniff")
    response.headers.setdefault("x-frame-options", "DENY")
    response.headers.setdefault("referrer-policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("permissions-policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "content-security-policy",
        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
    )
    response.headers.setdefault("x-captureos-auth-required", "true" if AUTH_REQUIRED else "false")
    return response


class WorkflowUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(tracking|qualifying|bid|no_bid|submitted|won|lost)$")
    go_no_go: Optional[str] = Field(None, pattern="^(go|no_go|undecided)$")
    priority: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    stage: Optional[str] = Field(None, min_length=2, max_length=80)
    owner_user_id: Optional[UUID] = None
    next_review_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    tags: Optional[List[str]] = Field(None, max_length=12)
    notes: Optional[str] = Field(None, max_length=4000)
    decision_rationale: Optional[str] = Field(None, max_length=4000)


class PastPerformanceRow(BaseModel):
    contract_number: str = Field(..., min_length=3, max_length=80)
    role: str = Field(..., pattern="^(prime|subcontractor|mentor_protege|joint_venture)$")
    title: str = Field(..., min_length=3, max_length=240)
    description: str = Field("", max_length=4000)
    prime_name: Optional[str] = Field(None, max_length=240)
    agency_name: Optional[str] = Field(None, max_length=240)
    agency_code: Optional[str] = Field(None, max_length=20)
    naics_code: Optional[str] = Field(None, pattern="^[0-9]{2,6}$")
    psc_code: Optional[str] = Field(None, max_length=4)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    obligated_amount: Optional[Decimal] = Field(None, ge=0)
    contract_vehicles: List[str] = Field(default_factory=list, max_length=12)
    clearance_required: Optional[str] = Field(None, max_length=80)
    customer_rating: Optional[str] = Field(None, max_length=80)


class PastPerformanceImport(BaseModel):
    customer_profile_id: Optional[UUID] = None
    source: str = Field("customer_import", min_length=3, max_length=80)
    rows: List[PastPerformanceRow] = Field(..., min_length=1, max_length=250)


class BillingCheckoutRequest(BaseModel):
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


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
    return _build_capture_analysis_response(request, conn, opportunity_id, our_entity_id)


@router.get("/capture-analysis/{opportunity_id}/brief.md")
def get_capture_brief_markdown(
    request: Request,
    opportunity_id: str = Path(..., min_length=1, max_length=128),
    our_entity_id: Optional[UUID] = Query(None),
    conn=Depends(get_db_connection),
) -> Response:
    analysis = _build_capture_analysis_response(request, conn, opportunity_id, our_entity_id)
    markdown = _render_capture_brief_markdown(analysis)
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"content-disposition": f"attachment; filename=capture-brief-{opportunity_id}.md"},
    )


@router.get("/workspace")
def get_workspace_summary(request: Request, conn=Depends(get_db_connection)) -> Dict[str, Any]:
    context = _load_request_context(conn, request)
    tenant_id = context.get("tenant_id")
    profile = _fetch_customer_profile(conn, tenant_id)
    return {
        "security_context": context,
        "customer_profile": profile,
        "data_freshness": _fetch_data_freshness(conn),
        "competitor_watchlist": _fetch_competitor_watchlist(conn, tenant_id),
        "pipeline": _fetch_pipeline_summary(conn, tenant_id),
        "past_performance": _fetch_past_performance(conn, tenant_id, limit=20),
        "billing": _fetch_billing_account(conn, tenant_id),
        "compliance_controls": _fetch_compliance_controls(conn),
        "privacy_posture": {
            "tenant_isolation": "tenant_id scoped queries",
            "rbac": "admin, capture_manager, analyst, viewer",
            "audit_events": "workflow mutations are recorded",
            "auth_mode": "JWT enforced when AUTH_REQUIRED=true; demo headers remain available only when disabled",
        },
    }


@router.get("/health")
def get_health(conn=Depends(get_db_connection)) -> Dict[str, Any]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT now() AS checked_at, current_database() AS database_name;")
        row = cur.fetchone()
    return {
        "status": "ok",
        "checked_at": _json_safe(row["checked_at"]),
        "database": row["database_name"],
        "auth_required": AUTH_REQUIRED,
        "vector_store": "pgvector",
    }


@router.post("/onboarding/past-performance/import")
def import_past_performance(
    request: Request,
    payload: PastPerformanceImport,
    conn=Depends(get_db_connection),
) -> Dict[str, Any]:
    context = _load_request_context(conn, request)
    if context.get("role") not in {"admin", "capture_manager", "analyst"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for onboarding import.")

    imported = _import_past_performance(conn, context, payload)
    _refresh_customer_profile_summary(conn, context["tenant_id"])
    _record_audit_event(
        conn,
        context=context,
        request=request,
        action="onboarding.past_performance_import",
        resource_type="customer_past_performance",
        resource_id=context["tenant_id"],
        metadata={"rows": len(payload.rows), "source": payload.source},
    )
    conn.commit()
    return {
        "imported": imported,
        "past_performance": _fetch_past_performance(conn, context["tenant_id"], limit=20),
        "customer_profile": _fetch_customer_profile(conn, context["tenant_id"]),
    }


@router.post("/billing/checkout")
def create_billing_checkout(
    request: Request,
    payload: BillingCheckoutRequest,
    conn=Depends(get_db_connection),
) -> Dict[str, Any]:
    context = _load_request_context(conn, request)
    if context.get("role") not in {"admin", "capture_manager"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins or capture managers can manage billing.")
    billing = _fetch_billing_account(conn, context.get("tenant_id"))
    stripe_api_key = _resolve_stripe_api_key()
    if not stripe_api_key or not STRIPE_PRICE_ID:
        return {
            "mode": "not_configured",
            "message": "Set STRIPE_API_KEY and STRIPE_PRICE_ID to enable hosted billing checkout.",
            "billing": billing,
        }
    checkout = _create_stripe_checkout_session(context, payload, stripe_api_key)
    _record_audit_event(
        conn,
        context=context,
        request=request,
        action="billing.checkout_created",
        resource_type="tenant",
        resource_id=context["tenant_id"],
        metadata={"checkout_session_id": checkout.get("id")},
    )
    conn.commit()
    return {"mode": "stripe_checkout", "checkout": checkout, "billing": billing}


@router.post("/billing/webhook")
async def receive_billing_webhook(request: Request, conn=Depends(get_db_connection)) -> Dict[str, Any]:
    body = await request.body()
    _verify_stripe_signature(body, request.headers.get("stripe-signature"))
    try:
        event = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook JSON.") from exc

    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "unknown")
    tenant_id = _tenant_id_from_billing_event(conn, event)
    _record_billing_event(conn, tenant_id, event_id, event_type, event)
    conn.commit()
    return {"received": True, "event_id": event_id, "event_type": event_type}


@router.post("/opportunities/{opportunity_id}/track")
def track_opportunity(
    request: Request,
    payload: WorkflowUpdate,
    opportunity_id: str = Path(..., min_length=1, max_length=128),
    conn=Depends(get_db_connection),
) -> Dict[str, Any]:
    context = _load_request_context(conn, request)
    if context.get("role") not in {"admin", "capture_manager", "analyst"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for workflow changes.")

    opportunity = _fetch_opportunity_identity(conn, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Opportunity was not found: {opportunity_id}")

    workflow = _upsert_workflow(conn, context, opportunity["opportunity_id"], payload)
    _record_audit_event(
        conn,
        context=context,
        request=request,
        action="workflow.upsert",
        resource_type="opportunity",
        resource_id=opportunity["opportunity_id"],
        metadata={"notice_id": opportunity["notice_id"], "payload": payload.model_dump(mode="json", exclude_none=True)},
    )
    conn.commit()
    return {"workflow": workflow, "security_context": context}


def _build_capture_analysis_response(
    request: Request,
    conn,
    opportunity_id: str,
    our_entity_id: Optional[UUID],
) -> Dict[str, Any]:
    context = _load_request_context(conn, request)
    customer_profile = _fetch_customer_profile(conn, context.get("tenant_id"))
    selected_entity_id = str(our_entity_id) if our_entity_id else customer_profile.get("entity_id")

    try:
        with _query_timeout(conn, ANALYSIS_QUERY_TIMEOUT_MS):
            analysis = find_best_teaming_partners(
                conn,
                opportunity_id=opportunity_id,
                our_entity_id=selected_entity_id,
                historical_limit=75,
                top_primes=3,
                subs_per_prime=5,
                team_sub_limit=5,
            )
            market_baseline = find_best_teaming_partners(
                conn,
                opportunity_id=opportunity_id,
                our_entity_id=None,
                historical_limit=75,
                top_primes=3,
                subs_per_prime=5,
                team_sub_limit=5,
            )
            benchmarks = _fetch_calc_benchmarks(conn, opportunity_id=opportunity_id, max_rows=12)
    except ValueError as exc:
        if "has no sow_embedding" in str(exc):
            return _build_structural_capture_response(
                request=request,
                conn=conn,
                opportunity_id=opportunity_id,
                context=context,
                customer_profile=customer_profile,
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except psycopg2.errors.QueryCanceled as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Capture analysis query timed out.") from exc

    response = _json_safe(analysis)
    response["market_baseline"] = _json_safe(market_baseline.get("competitive_baseline", {}))
    response["calc_plus_benchmarks"] = benchmarks
    response["customer_profile"] = customer_profile
    response["customer_score"] = _customer_score_breakdown(
        customer_profile,
        response.get("opportunity", {}),
        response.get("competitive_baseline", {}),
        response["market_baseline"],
    )
    response["workflow"] = _fetch_workflow(conn, context.get("tenant_id"), response["opportunity"]["opportunity_id"])
    response["notes"] = _fetch_notes(conn, context.get("tenant_id"), response["opportunity"]["opportunity_id"], limit=5)
    response["past_performance"] = _fetch_past_performance(conn, context.get("tenant_id"), limit=8)
    response["billing"] = _fetch_billing_account(conn, context.get("tenant_id"))
    response["compliance_controls"] = _fetch_compliance_controls(conn)
    response["evidence"] = _fetch_evidence_bundle(conn, response, benchmarks)
    response["data_freshness"] = _fetch_data_freshness(conn)
    response["security_context"] = context
    response["metadata"] = {
        "api_version": "v1",
        "request_id": request.headers.get("x-request-id"),
        "limits": {"top_primes": 3, "top_subcontractors": 5, "calc_benchmarks": 12},
    }
    return response


def _build_structural_capture_response(
    request: Request,
    conn,
    opportunity_id: str,
    context: Mapping[str, Any],
    customer_profile: Mapping[str, Any],
) -> Dict[str, Any]:
    opportunity = _fetch_opportunity_detail(conn, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Opportunity was not found: {opportunity_id}")

    benchmarks = _fetch_calc_benchmarks(conn, opportunity_id=opportunity_id, max_rows=12)
    baseline = _structural_opportunity_baseline(customer_profile, opportunity)
    market_baseline = {
        "estimated_p_win": 0.18,
        "confidence": "low",
        "model_scope": "live_sam_structural_only",
        "historical_match_count": 0,
        "total_matched_obligation": 0,
    }
    response: Dict[str, Any] = {
        "opportunity": opportunity,
        "competing_primes": [],
        "target_teaming_subs": [],
        "competitive_baseline": baseline,
        "market_baseline": market_baseline,
        "calc_plus_benchmarks": benchmarks,
        "customer_profile": customer_profile,
        "customer_score": _customer_score_breakdown(customer_profile, opportunity, baseline, market_baseline),
        "workflow": _fetch_workflow(conn, context.get("tenant_id"), opportunity["opportunity_id"]),
        "notes": _fetch_notes(conn, context.get("tenant_id"), opportunity["opportunity_id"], limit=5),
        "past_performance": _fetch_past_performance(conn, context.get("tenant_id"), limit=8),
        "billing": _fetch_billing_account(conn, context.get("tenant_id")),
        "compliance_controls": _fetch_compliance_controls(conn),
        "evidence": _live_opportunity_evidence(opportunity, baseline),
        "data_freshness": _fetch_data_freshness(conn),
        "security_context": context,
        "metadata": {
            "api_version": "v1",
            "request_id": request.headers.get("x-request-id"),
            "limits": {"top_primes": 3, "top_subcontractors": 5, "calc_benchmarks": 12},
            "analysis_mode": "structural_only_pending_embedding",
        },
    }
    return _json_safe(response)


def _load_request_context(conn, request: Request) -> Dict[str, Any]:
    auth_context = authenticate_request(request)
    if AUTH_REQUIRED and auth_context.get("auth_mode") == "jwt" and not auth_context.get("tenant_slug"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="JWT tenant claim is required.")
    tenant_slug = (
        auth_context.get("tenant_slug")
        or request.headers.get("x-captureos-tenant")
        or DEFAULT_TENANT_SLUG
    ).strip()
    user_email = (
        auth_context.get("email")
        or request.headers.get("x-captureos-user")
        or DEFAULT_USER_EMAIL
    ).strip().lower()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH target_tenant AS (
                  SELECT tenant_id, tenant_slug, tenant_name, plan_tier, data_region
                  FROM capture.tenants
                  WHERE tenant_slug = %(tenant_slug)s
                  LIMIT 1
                ),
                requested_user AS (
                  SELECT u.*
                  FROM capture.tenant_users u
                  JOIN target_tenant t ON t.tenant_id = u.tenant_id
                  WHERE lower(u.email) = %(user_email)s
                    AND u.status = 'active'
                  LIMIT 1
                ),
                fallback_user AS (
                  SELECT u.*
                  FROM capture.tenant_users u
                  JOIN target_tenant t ON t.tenant_id = u.tenant_id
                  WHERE u.status = 'active'
                  ORDER BY
                    CASE u.role
                      WHEN 'admin' THEN 1
                      WHEN 'capture_manager' THEN 2
                      WHEN 'analyst' THEN 3
                      ELSE 4
                    END,
                    u.created_at
                  LIMIT 1
                )
                SELECT
                  t.tenant_id::text,
                  t.tenant_slug,
                  t.tenant_name,
                  t.plan_tier,
                  t.data_region,
                  COALESCE(ru.user_id, fu.user_id)::text AS user_id,
                  COALESCE(ru.email, fu.email) AS email,
                  COALESCE(ru.display_name, fu.display_name) AS display_name,
                  COALESCE(ru.role, fu.role, 'viewer') AS role,
                  (ru.user_id IS NOT NULL) AS requested_user_found
                FROM target_tenant t
                LEFT JOIN requested_user ru ON true
                LEFT JOIN fallback_user fu ON ru.user_id IS NULL;
                """,
                {"tenant_slug": tenant_slug, "user_email": user_email},
            )
            row = cur.fetchone()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return {
                "tenant_id": None,
                "tenant_slug": tenant_slug,
                "tenant_name": "Uninitialized demo tenant",
                "plan_tier": "demo",
                "data_region": "us-east-1",
                "user_id": None,
                "email": user_email,
                "display_name": "Demo User",
                "role": "viewer",
                "auth_mode": "uninitialized",
            }
        raise

    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unknown or inactive tenant context.")
    if auth_context.get("auth_mode") == "jwt" and not row.get("requested_user_found"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authenticated user is not active in this tenant.")
    context = _json_safe(dict(row))
    context.pop("requested_user_found", None)
    context["auth_mode"] = auth_context.get("auth_mode", "demo_header_context")
    context["subject"] = auth_context.get("subject")
    context["rbac_scopes"] = _role_scopes(context.get("role"))
    return context


def _role_scopes(role: Optional[str]) -> List[str]:
    scopes = {
        "admin": ["read", "write", "admin", "audit"],
        "capture_manager": ["read", "write", "audit"],
        "analyst": ["read", "write"],
        "viewer": ["read"],
    }
    return scopes.get(role or "viewer", ["read"])


def _fetch_customer_profile(conn, tenant_id: Optional[str]) -> Dict[str, Any]:
    if not tenant_id:
        return {}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  cp.customer_profile_id::text,
                  cp.tenant_id::text,
                  cp.entity_id::text,
                  cp.company_name,
                  e.legal_name AS resolved_entity_name,
                  e.canonical_uei,
                  e.cage_code,
                  cp.target_naics_codes,
                  cp.target_psc_codes,
                  cp.target_agency_codes,
                  cp.contract_vehicles,
                  cp.set_aside_eligibilities,
                  cp.clearance_levels,
                  cp.socioeconomic_tags,
                  cp.incumbent_agency_codes,
                  cp.past_performance_summary,
                  cp.pricing_strategy,
                  cp.risk_preferences,
                  cp.updated_at
                FROM capture.customer_profiles cp
                LEFT JOIN capture.entities e ON e.entity_id = cp.entity_id
                WHERE cp.tenant_id = %(tenant_id)s::uuid
                ORDER BY cp.updated_at DESC
                LIMIT 1;
                """,
                {"tenant_id": tenant_id},
            )
            row = cur.fetchone()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return {}
        raise
    return _json_safe(dict(row)) if row else {}


def _fetch_workflow(conn, tenant_id: Optional[str], opportunity_id: str) -> Dict[str, Any]:
    if not tenant_id:
        return {"status": "untracked", "go_no_go": "undecided"}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  w.workflow_id::text,
                  w.tenant_id::text,
                  w.opportunity_id::text,
                  w.owner_user_id::text,
                  u.display_name AS owner_name,
                  u.email AS owner_email,
                  w.status,
                  w.go_no_go,
                  w.priority,
                  w.stage,
                  w.next_review_at,
                  w.due_at,
                  w.tags,
                  w.notes,
                  w.decision_rationale,
                  w.updated_at
                FROM capture.capture_opportunity_workflow w
                LEFT JOIN capture.tenant_users u ON u.user_id = w.owner_user_id
                WHERE w.tenant_id = %(tenant_id)s::uuid
                  AND w.opportunity_id = %(opportunity_id)s::uuid
                LIMIT 1;
                """,
                {"tenant_id": tenant_id, "opportunity_id": opportunity_id},
            )
            row = cur.fetchone()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return {"status": "untracked", "go_no_go": "undecided"}
        raise
    return _json_safe(dict(row)) if row else {"status": "untracked", "go_no_go": "undecided"}


def _fetch_notes(conn, tenant_id: Optional[str], opportunity_id: str, limit: int) -> List[Dict[str, Any]]:
    if not tenant_id:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  n.note_id::text,
                  n.note_type,
                  n.body,
                  n.created_at,
                  u.display_name AS author_name,
                  u.email AS author_email
                FROM capture.opportunity_notes n
                LEFT JOIN capture.tenant_users u ON u.user_id = n.author_user_id
                WHERE n.tenant_id = %(tenant_id)s::uuid
                  AND n.opportunity_id = %(opportunity_id)s::uuid
                ORDER BY n.created_at DESC
                LIMIT %(limit)s;
                """,
                {"tenant_id": tenant_id, "opportunity_id": opportunity_id, "limit": limit},
            )
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return []
        raise
    return [_json_safe(dict(row)) for row in rows]


def _fetch_data_freshness(conn) -> List[Dict[str, Any]]:
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  freshness_id::text,
                  source_system,
                  dataset_name,
                  source_mode,
                  last_successful_sync_at,
                  last_attempted_sync_at,
                  sync_status,
                  record_count,
                  freshness_sla_hours,
                  source_url,
                  notes,
                  CASE
                    WHEN last_successful_sync_at IS NULL THEN 'unknown'
                    WHEN now() - last_successful_sync_at <= make_interval(hours => freshness_sla_hours) THEN 'fresh'
                    ELSE 'stale'
                  END AS freshness_state
                FROM capture.data_freshness
                ORDER BY source_system, dataset_name;
                """
            )
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return []
        raise
    return [_json_safe(dict(row)) for row in rows]


def _fetch_competitor_watchlist(conn, tenant_id: Optional[str]) -> List[Dict[str, Any]]:
    if not tenant_id:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  cw.watchlist_id::text,
                  cw.priority,
                  cw.reason,
                  cw.updated_at,
                  e.entity_id::text,
                  e.legal_name,
                  e.canonical_uei,
                  e.cage_code
                FROM capture.competitor_watchlist cw
                JOIN capture.entities e ON e.entity_id = cw.entity_id
                WHERE cw.tenant_id = %(tenant_id)s::uuid
                ORDER BY
                  CASE cw.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                  e.legal_name;
                """,
                {"tenant_id": tenant_id},
            )
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return []
        raise
    return [_json_safe(dict(row)) for row in rows]


def _fetch_pipeline_summary(conn, tenant_id: Optional[str]) -> Dict[str, Any]:
    if not tenant_id:
        return {"by_status": [], "high_priority": 0}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  COALESCE(
                    JSONB_AGG(
                      JSONB_BUILD_OBJECT('status', status, 'count', status_count)
                      ORDER BY status
                    ),
                    '[]'::jsonb
                  ) AS by_status,
                  COALESCE(SUM(status_count) FILTER (WHERE priority = 'high'), 0)::int AS high_priority,
                  MIN(due_at) FILTER (WHERE status NOT IN ('no_bid', 'won', 'lost')) AS next_due_at
                FROM (
                  SELECT status, priority, COUNT(*)::int AS status_count, MIN(due_at) AS due_at
                  FROM capture.capture_opportunity_workflow
                  WHERE tenant_id = %(tenant_id)s::uuid
                  GROUP BY status, priority
                ) s;
                """,
                {"tenant_id": tenant_id},
            )
            row = cur.fetchone()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return {"by_status": [], "high_priority": 0}
        raise
    return _json_safe(dict(row)) if row else {"by_status": [], "high_priority": 0}


def _fetch_past_performance(conn, tenant_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
    if not tenant_id:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  past_performance_id::text,
                  contract_number,
                  role,
                  prime_name,
                  agency_name,
                  agency_code,
                  naics_code,
                  psc_code,
                  title,
                  description,
                  start_date,
                  end_date,
                  obligated_amount,
                  contract_vehicles,
                  clearance_required,
                  customer_rating,
                  updated_at
                FROM capture.customer_past_performance
                WHERE tenant_id = %(tenant_id)s::uuid
                ORDER BY obligated_amount DESC NULLS LAST, updated_at DESC
                LIMIT %(limit)s;
                """,
                {"tenant_id": tenant_id, "limit": limit},
            )
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return []
        raise
    return [_json_safe(dict(row)) for row in rows]


def _fetch_billing_account(conn, tenant_id: Optional[str]) -> Dict[str, Any]:
    if not tenant_id:
        return {}
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  billing_account_id::text,
                  tenant_id::text,
                  billing_provider,
                  provider_customer_id,
                  provider_subscription_id,
                  subscription_status,
                  price_id,
                  trial_ends_at,
                  current_period_ends_at,
                  billing_email,
                  updated_at
                FROM capture.billing_accounts
                WHERE tenant_id = %(tenant_id)s::uuid
                LIMIT 1;
                """,
                {"tenant_id": tenant_id},
            )
            row = cur.fetchone()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return {}
        raise
    return _json_safe(dict(row)) if row else {"subscription_status": "not_configured"}


def _fetch_compliance_controls(conn) -> List[Dict[str, Any]]:
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  control_id::text,
                  control_key,
                  control_family,
                  control_name,
                  implementation_status,
                  implementation_notes,
                  evidence_url,
                  owner,
                  updated_at
                FROM capture.compliance_controls
                ORDER BY control_family, control_key;
                """
            )
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            return []
        raise
    return [_json_safe(dict(row)) for row in rows]


def _import_past_performance(conn, context: Mapping[str, Any], payload: PastPerformanceImport) -> Dict[str, Any]:
    tenant_id = context["tenant_id"]
    customer_profile_id = str(payload.customer_profile_id) if payload.customer_profile_id else _default_customer_profile_id(conn, tenant_id)
    rows = [
        (
            tenant_id,
            customer_profile_id,
            payload.source,
            row.contract_number.strip(),
            row.role,
            row.prime_name,
            row.agency_name,
            row.agency_code,
            row.naics_code,
            row.psc_code.upper() if row.psc_code else None,
            row.title,
            row.description,
            row.start_date,
            row.end_date,
            row.obligated_amount,
            [value.strip()[:80] for value in row.contract_vehicles if value.strip()],
            row.clearance_required,
            row.customer_rating,
            json.dumps(row.model_dump(mode="json")),
        )
        for row in payload.rows
    ]
    with conn.cursor() as cur:
        from psycopg2.extras import execute_values

        execute_values(
            cur,
            """
            INSERT INTO capture.customer_past_performance (
              tenant_id, customer_profile_id, source, contract_number, role, prime_name,
              agency_name, agency_code, naics_code, psc_code, title, description,
              start_date, end_date, obligated_amount, contract_vehicles, clearance_required,
              customer_rating, source_payload
            )
            VALUES %s
            ON CONFLICT (tenant_id, contract_number, role)
            DO UPDATE SET
              customer_profile_id = EXCLUDED.customer_profile_id,
              source = EXCLUDED.source,
              prime_name = EXCLUDED.prime_name,
              agency_name = EXCLUDED.agency_name,
              agency_code = EXCLUDED.agency_code,
              naics_code = EXCLUDED.naics_code,
              psc_code = EXCLUDED.psc_code,
              title = EXCLUDED.title,
              description = EXCLUDED.description,
              start_date = EXCLUDED.start_date,
              end_date = EXCLUDED.end_date,
              obligated_amount = EXCLUDED.obligated_amount,
              contract_vehicles = EXCLUDED.contract_vehicles,
              clearance_required = EXCLUDED.clearance_required,
              customer_rating = EXCLUDED.customer_rating,
              source_payload = EXCLUDED.source_payload,
              updated_at = now();
            """,
            rows,
            template="(%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::text[],%s,%s,%s::jsonb)",
            page_size=100,
        )
    return {"rows_received": len(rows), "customer_profile_id": customer_profile_id}


def _default_customer_profile_id(conn, tenant_id: str) -> str:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT customer_profile_id::text
            FROM capture.customer_profiles
            WHERE tenant_id = %(tenant_id)s::uuid
            ORDER BY updated_at DESC
            LIMIT 1;
            """,
            {"tenant_id": tenant_id},
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Create a customer profile before importing past performance.")
    return str(row["customer_profile_id"])


def _refresh_customer_profile_summary(conn, tenant_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH rollup AS (
              SELECT
                tenant_id,
                COUNT(*) FILTER (WHERE role = 'prime')::int AS prime_contracts,
                COUNT(*) FILTER (WHERE role <> 'prime')::int AS subcontracts,
                COALESCE(SUM(obligated_amount), 0)::numeric AS recent_relevant_obligation,
                ARRAY_AGG(DISTINCT naics_code) FILTER (WHERE naics_code IS NOT NULL) AS naics_codes,
                ARRAY_AGG(DISTINCT psc_code) FILTER (WHERE psc_code IS NOT NULL) AS psc_codes,
                ARRAY_AGG(DISTINCT agency_code) FILTER (WHERE agency_code IS NOT NULL) AS agency_codes
              FROM capture.customer_past_performance
              WHERE tenant_id = %(tenant_id)s::uuid
              GROUP BY tenant_id
            )
            UPDATE capture.customer_profiles cp
            SET
              past_performance_summary = jsonb_build_object(
                'prime_contracts', r.prime_contracts,
                'subcontracts', r.subcontracts,
                'recent_relevant_obligation', r.recent_relevant_obligation,
                'imported_naics_codes', COALESCE(r.naics_codes, ARRAY[]::text[]),
                'imported_psc_codes', COALESCE(r.psc_codes, ARRAY[]::text[]),
                'imported_agency_codes', COALESCE(r.agency_codes, ARRAY[]::text[])
              ),
              target_naics_codes = (
                SELECT ARRAY(SELECT DISTINCT unnest(cp.target_naics_codes || COALESCE(r.naics_codes, ARRAY[]::text[])))
              ),
              target_psc_codes = (
                SELECT ARRAY(SELECT DISTINCT unnest(cp.target_psc_codes || COALESCE(r.psc_codes, ARRAY[]::text[])))
              ),
              target_agency_codes = (
                SELECT ARRAY(SELECT DISTINCT unnest(cp.target_agency_codes || COALESCE(r.agency_codes, ARRAY[]::text[])))
              ),
              updated_at = now()
            FROM rollup r
            WHERE cp.tenant_id = r.tenant_id;
            """,
            {"tenant_id": tenant_id},
        )


def _resolve_stripe_api_key() -> str:
    if STRIPE_API_KEY:
        return STRIPE_API_KEY
    return _resolve_secret_value(STRIPE_API_KEY_SECRET_ARN, ("STRIPE_API_KEY", "api_key", "value"))


def _resolve_stripe_webhook_secret() -> str:
    if STRIPE_WEBHOOK_SECRET:
        return STRIPE_WEBHOOK_SECRET
    return _resolve_secret_value(STRIPE_WEBHOOK_SECRET_ARN, ("STRIPE_WEBHOOK_SECRET", "webhook_secret", "value"))


def _resolve_secret_value(secret_arn: str, keys: Sequence[str]) -> str:
    if not secret_arn:
        return ""
    import boto3

    secret = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    value = secret.get("SecretString") or ""
    try:
        parsed = json.loads(value)
        if isinstance(parsed, Mapping):
            for key in keys:
                if parsed.get(key):
                    return str(parsed[key])
            return ""
    except json.JSONDecodeError:
        return value
    return value


def _verify_stripe_signature(body: bytes, signature_header: Optional[str]) -> None:
    webhook_secret = _resolve_stripe_webhook_secret()
    if not webhook_secret:
        return
    if not signature_header:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Stripe-Signature header.")

    parts = {}
    for item in signature_header.split(","):
        key, _, value = item.partition("=")
        if key and value:
            parts.setdefault(key, []).append(value)
    timestamp_values = parts.get("t") or []
    signatures = parts.get("v1") or []
    if not timestamp_values or not signatures:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe-Signature header.")

    signed_payload = f"{timestamp_values[0]}.".encode("utf-8") + body
    expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe webhook signature.")


def _create_stripe_checkout_session(
    context: Mapping[str, Any],
    payload: BillingCheckoutRequest,
    stripe_api_key: str,
) -> Dict[str, Any]:
    success_url = payload.success_url or f"{APP_PUBLIC_URL}/?billing=success"
    cancel_url = payload.cancel_url or f"{APP_PUBLIC_URL}/?billing=cancelled"
    data = {
        "mode": "subscription",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "line_items[0][price]": STRIPE_PRICE_ID,
        "line_items[0][quantity]": "1",
        "client_reference_id": str(context["tenant_id"]),
        "customer_email": str(context.get("email") or ""),
        "metadata[tenant_id]": str(context["tenant_id"]),
        "metadata[tenant_slug]": str(context["tenant_slug"]),
    }
    request = urllib.request.Request(
        "https://api.stripe.com/v1/checkout/sessions",
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers={
            "authorization": f"Bearer {stripe_api_key}",
            "content-type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1200]
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Stripe checkout failed: {detail}") from exc


def _tenant_id_from_billing_event(conn, event: Mapping[str, Any]) -> Optional[str]:
    obj = ((event.get("data") or {}).get("object") or {}) if isinstance(event.get("data"), Mapping) else {}
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), Mapping) else {}
    tenant_id = metadata.get("tenant_id") or obj.get("client_reference_id")
    if tenant_id:
        return str(tenant_id)
    customer_id = obj.get("customer")
    if not customer_id:
        return None
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT tenant_id::text FROM capture.billing_accounts WHERE provider_customer_id = %(customer_id)s LIMIT 1;",
            {"customer_id": customer_id},
        )
        row = cur.fetchone()
    return str(row["tenant_id"]) if row else None


def _record_billing_event(
    conn,
    tenant_id: Optional[str],
    event_id: str,
    event_type: str,
    event: Mapping[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO capture.billing_events (
              tenant_id, provider, provider_event_id, event_type, event_payload
            )
            VALUES (%(tenant_id)s::uuid, 'stripe', %(event_id)s, %(event_type)s, %(event_payload)s::jsonb)
            ON CONFLICT (provider_event_id)
            DO NOTHING;
            """,
            {
                "tenant_id": tenant_id,
                "event_id": event_id or None,
                "event_type": event_type,
                "event_payload": json.dumps(_json_safe(event)),
            },
        )


def _fetch_evidence_bundle(
    conn,
    analysis: Mapping[str, Any],
    benchmarks: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    opportunity_id = analysis.get("opportunity", {}).get("opportunity_id")
    award_ids: List[str] = []
    subaward_numbers: List[str] = []
    for prime in analysis.get("competing_primes", []):
        for award in prime.get("representative_awards", [])[:3]:
            if award.get("award_id"):
                award_ids.append(str(award["award_id"]))
        for sub in prime.get("frequent_subcontractors", []):
            subaward_numbers.extend(str(item) for item in sub.get("subaward_numbers", []) if item)
    labor_rate_ids = [str(rate["labor_rate_id"]) for rate in benchmarks if rate.get("labor_rate_id")]

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  evidence_id::text,
                  opportunity_id::text,
                  award_id::text,
                  sub_award_id::text,
                  labor_rate_id::text,
                  related_entity_id::text,
                  evidence_type,
                  source_system,
                  source_record_id,
                  source_title,
                  source_url,
                  source_record_date,
                  source_amount,
                  agency_name,
                  agency_code,
                  naics_code,
                  psc_code,
                  explanation,
                  confidence,
                  source_payload
                FROM capture.source_evidence
                WHERE
                  (%(opportunity_id)s::text IS NOT NULL AND opportunity_id::text = %(opportunity_id)s::text)
                  OR award_id::text = ANY(%(award_ids)s::text[])
                  OR source_record_id = ANY(%(subaward_numbers)s::text[])
                  OR labor_rate_id::text = ANY(%(labor_rate_ids)s::text[])
                ORDER BY
                  CASE evidence_type
                    WHEN 'opportunity' THEN 1
                    WHEN 'award' THEN 2
                    WHEN 'subaward' THEN 3
                    WHEN 'labor_rate' THEN 4
                    ELSE 5
                  END,
                  source_record_date DESC NULLS LAST,
                  source_amount DESC NULLS LAST
                LIMIT 80;
                """,
                {
                    "opportunity_id": opportunity_id,
                    "award_ids": award_ids,
                    "subaward_numbers": subaward_numbers,
                    "labor_rate_ids": labor_rate_ids,
                },
            )
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        if exc.pgcode == "42P01":
            conn.rollback()
            rows = []
        else:
            raise

    items = [_json_safe(dict(row)) for row in rows]
    by_type: Dict[str, int] = {}
    for item in items:
        by_type[item["evidence_type"]] = by_type.get(item["evidence_type"], 0) + 1
    return {
        "items": items,
        "coverage": by_type,
        "score_factors": _score_factor_evidence(analysis),
    }


def _score_factor_evidence(analysis: Mapping[str, Any]) -> List[Dict[str, Any]]:
    baseline = analysis.get("competitive_baseline", {})
    inputs = baseline.get("score_inputs", {})
    weights = baseline.get("score_weights", {})
    return [
        {
            "factor": "Semantic and structural fit",
            "score": inputs.get("avg_match_score"),
            "weight": weights.get("semantic_and_structural_fit"),
            "why": "Average similarity across historical awards after combining SOW vector distance, NAICS, PSC, agency, and recency.",
        },
        {
            "factor": "Agency match",
            "score": inputs.get("agency_match_rate"),
            "weight": weights.get("agency_match"),
            "why": "Share of historically similar awards funded by the same agency as the active opportunity.",
        },
        {
            "factor": "Available partner depth",
            "score": inputs.get("partner_depth_score"),
            "weight": weights.get("available_partner_depth"),
            "why": "Depth of subcontractors repeatedly attached to primes with similar wins.",
        },
        {
            "factor": "Incumbent concentration",
            "score": inputs.get("incumbent_concentration"),
            "weight": weights.get("incumbent_concentration_penalty"),
            "why": "Penalty when a small set of primes dominates comparable historical awards.",
        },
        {
            "factor": "Customer relevance",
            "score": inputs.get("our_relevance_signal"),
            "weight": weights.get("company_relevance_signal"),
            "why": "Customer-specific prime/subcontract history on comparable work.",
        },
    ]


def _customer_score_breakdown(
    profile: Mapping[str, Any],
    opportunity: Mapping[str, Any],
    company_baseline: Mapping[str, Any],
    market_baseline: Mapping[str, Any],
) -> Dict[str, Any]:
    if not profile:
        return {}
    target_naics = set(profile.get("target_naics_codes") or [])
    target_psc = set(profile.get("target_psc_codes") or [])
    target_agencies = set(profile.get("target_agency_codes") or [])
    incumbent_agencies = set(profile.get("incumbent_agency_codes") or [])
    opportunity_value = opportunity.get("estimated_value_max") or opportunity.get("estimated_value_min") or 0
    max_value = (profile.get("risk_preferences") or {}).get("max_single_award_value") or 0
    market_pwin = float(market_baseline.get("estimated_p_win") or 0)
    company_pwin = float(company_baseline.get("estimated_p_win") or market_pwin)
    factors = [
        {
            "label": "NAICS fit",
            "score": 1.0 if opportunity.get("naics_code") in target_naics else 0.35,
            "evidence": f"{opportunity.get('naics_code') or '--'} against profile targets {', '.join(sorted(target_naics)) or '--'}",
        },
        {
            "label": "PSC fit",
            "score": 1.0 if opportunity.get("psc_code") in target_psc else 0.4,
            "evidence": f"{opportunity.get('psc_code') or '--'} against profile targets {', '.join(sorted(target_psc)) or '--'}",
        },
        {
            "label": "Agency relationship",
            "score": 1.0 if opportunity.get("funding_agency_code") in incumbent_agencies else (0.75 if opportunity.get("funding_agency_code") in target_agencies else 0.35),
            "evidence": f"{opportunity.get('funding_agency_name') or '--'} relationship depth from customer profile.",
        },
        {
            "label": "Contract vehicle posture",
            "score": 0.85 if profile.get("contract_vehicles") else 0.25,
            "evidence": ", ".join(profile.get("contract_vehicles") or ["No vehicles configured"]),
        },
        {
            "label": "Clearance and eligibility",
            "score": 0.82 if profile.get("clearance_levels") or profile.get("set_aside_eligibilities") else 0.35,
            "evidence": ", ".join((profile.get("clearance_levels") or []) + (profile.get("set_aside_eligibilities") or [])) or "Not configured",
        },
        {
            "label": "Deal size fit",
            "score": 1.0 if max_value and opportunity_value and float(opportunity_value) <= float(max_value) else 0.55,
            "evidence": f"Opportunity ceiling {opportunity_value}; profile max single award {max_value or '--'}",
        },
    ]
    fit_score = sum(float(item["score"]) for item in factors) / len(factors)
    return {
        "company_adjusted_p_win": round(company_pwin, 3),
        "market_baseline_p_win": round(market_pwin, 3),
        "delta_vs_market": round(company_pwin - market_pwin, 3),
        "profile_fit_score": round(fit_score, 3),
        "model_scope": company_baseline.get("model_scope"),
        "factors": factors,
    }


def _structural_opportunity_baseline(
    profile: Mapping[str, Any],
    opportunity: Mapping[str, Any],
) -> Dict[str, Any]:
    target_naics = set(profile.get("target_naics_codes") or [])
    target_psc = set(profile.get("target_psc_codes") or [])
    target_agencies = set(profile.get("target_agency_codes") or [])
    incumbent_agencies = set(profile.get("incumbent_agency_codes") or [])
    naics_signal = 1.0 if opportunity.get("naics_code") in target_naics else 0.0
    psc_signal = 1.0 if opportunity.get("psc_code") in target_psc else 0.0
    agency_signal = (
        1.0
        if opportunity.get("funding_agency_code") in incumbent_agencies
        else (0.65 if opportunity.get("funding_agency_code") in target_agencies else 0.0)
    )
    source_signal = 1.0 if opportunity.get("ui_link") or opportunity.get("description_url") else 0.3
    estimate = 0.14 + 0.12 * naics_signal + 0.08 * psc_signal + 0.10 * agency_signal + 0.02 * source_signal
    return {
        "estimated_p_win": round(min(0.48, max(0.08, estimate)), 3),
        "confidence": "low",
        "model_scope": "live_sam_structural_only_pending_embedding",
        "historical_match_count": 0,
        "competing_prime_count": 0,
        "total_matched_obligation": 0,
        "score_inputs": {
            "naics_match_rate": naics_signal,
            "psc_match_rate": psc_signal,
            "agency_match_rate": agency_signal,
            "source_record_signal": source_signal,
            "avg_match_score": 0,
            "avg_semantic_similarity": 0,
            "partner_depth_score": 0,
            "incumbent_concentration": 0,
            "our_relevance_signal": round((naics_signal + psc_signal + agency_signal) / 3, 3),
        },
        "score_weights": {
            "naics_match": 0.12,
            "psc_match": 0.08,
            "agency_match": 0.10,
            "source_record_signal": 0.02,
            "semantic_and_structural_fit": 0,
            "available_partner_depth": 0,
            "incumbent_concentration_penalty": 0,
            "company_relevance_signal": 0,
        },
        "notes": [
            "Live SAM.gov record does not yet have a generated SOW embedding, so this analysis uses structural signals only.",
            "Run document parsing/embedding enrichment to unlock competitor and subcontractor graph matching.",
        ],
    }


def _fetch_opportunity_detail(conn, opportunity_id: str) -> Optional[Dict[str, Any]]:
    predicate, params = _opportunity_predicate(opportunity_id)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
              opportunity_id::text,
              notice_id,
              solicitation_number,
              title,
              opportunity_type,
              base_type,
              active_status,
              posted_at,
              response_deadline,
              archive_at,
              naics_code,
              psc_code,
              set_aside_code,
              set_aside_description,
              funding_agency_name,
              funding_agency_code,
              subtier_name,
              office_name,
              full_parent_path_name,
              full_parent_path_code,
              organization_type,
              place_of_performance,
              office_address,
              estimated_value_min,
              estimated_value_max,
              currency_code,
              description_url,
              ui_link,
              resource_links,
              sow_text,
              source_payload,
              source_updated_at
            FROM capture.opportunities
            WHERE {predicate}
            LIMIT 1;
            """,
            params,
        )
        row = cur.fetchone()
    return _json_safe(dict(row)) if row else None


def _live_opportunity_evidence(
    opportunity: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> Dict[str, Any]:
    item = {
        "evidence_id": f"live-sam-{opportunity.get('notice_id')}",
        "opportunity_id": opportunity.get("opportunity_id"),
        "evidence_type": "opportunity",
        "source_system": "SAM.gov",
        "source_record_id": opportunity.get("notice_id"),
        "source_title": opportunity.get("title"),
        "source_url": opportunity.get("ui_link") or opportunity.get("description_url"),
        "source_record_date": opportunity.get("posted_at"),
        "source_amount": opportunity.get("estimated_value_max") or opportunity.get("estimated_value_min"),
        "agency_name": opportunity.get("funding_agency_name"),
        "agency_code": opportunity.get("funding_agency_code"),
        "naics_code": opportunity.get("naics_code"),
        "psc_code": opportunity.get("psc_code"),
        "explanation": "Live SAM.gov source record for the selected opportunity. Competitor graph analysis is pending SOW embedding enrichment.",
        "confidence": 0.72,
        "source_payload": opportunity.get("source_payload") or {},
    }
    return {
        "items": [item],
        "coverage": {"opportunity": 1},
        "score_factors": _score_factor_evidence({"competitive_baseline": baseline}),
    }


def _fetch_opportunity_identity(conn, opportunity_id: str) -> Optional[Dict[str, Any]]:
    predicate, params = _opportunity_predicate(opportunity_id)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT opportunity_id::text, notice_id, title, response_deadline
            FROM capture.opportunities
            WHERE {predicate}
            LIMIT 1;
            """,
            params,
        )
        row = cur.fetchone()
    return _json_safe(dict(row)) if row else None


def _upsert_workflow(
    conn,
    context: Mapping[str, Any],
    opportunity_id: str,
    payload: WorkflowUpdate,
) -> Dict[str, Any]:
    tenant_id = context.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant context is required.")
    owner_user_id = str(payload.owner_user_id) if payload.owner_user_id else context.get("user_id")
    tags = [tag.strip()[:40] for tag in (payload.tags or []) if tag.strip()]
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO capture.capture_opportunity_workflow (
              tenant_id, opportunity_id, owner_user_id, status, go_no_go, priority,
              stage, next_review_at, due_at, tags, notes, decision_rationale
            )
            VALUES (
              %(tenant_id)s::uuid,
              %(opportunity_id)s::uuid,
              %(owner_user_id)s::uuid,
              COALESCE(%(status)s, 'tracking'),
              COALESCE(%(go_no_go)s, 'undecided'),
              COALESCE(%(priority)s, 'medium'),
              COALESCE(%(stage)s, 'Qualification'),
              %(next_review_at)s,
              %(due_at)s,
              %(tags)s::text[],
              COALESCE(%(notes)s, ''),
              COALESCE(%(decision_rationale)s, '')
            )
            ON CONFLICT (tenant_id, opportunity_id)
            DO UPDATE SET
              owner_user_id = COALESCE(EXCLUDED.owner_user_id, capture.capture_opportunity_workflow.owner_user_id),
              status = COALESCE(EXCLUDED.status, capture.capture_opportunity_workflow.status),
              go_no_go = COALESCE(EXCLUDED.go_no_go, capture.capture_opportunity_workflow.go_no_go),
              priority = COALESCE(EXCLUDED.priority, capture.capture_opportunity_workflow.priority),
              stage = COALESCE(EXCLUDED.stage, capture.capture_opportunity_workflow.stage),
              next_review_at = COALESCE(EXCLUDED.next_review_at, capture.capture_opportunity_workflow.next_review_at),
              due_at = COALESCE(EXCLUDED.due_at, capture.capture_opportunity_workflow.due_at),
              tags = CASE WHEN array_length(EXCLUDED.tags, 1) IS NULL THEN capture.capture_opportunity_workflow.tags ELSE EXCLUDED.tags END,
              notes = CASE WHEN EXCLUDED.notes = '' THEN capture.capture_opportunity_workflow.notes ELSE EXCLUDED.notes END,
              decision_rationale = CASE
                WHEN EXCLUDED.decision_rationale = '' THEN capture.capture_opportunity_workflow.decision_rationale
                ELSE EXCLUDED.decision_rationale
              END,
              updated_at = now()
            RETURNING workflow_id::text;
            """,
            {
                "tenant_id": tenant_id,
                "opportunity_id": opportunity_id,
                "owner_user_id": owner_user_id,
                "status": payload.status,
                "go_no_go": payload.go_no_go,
                "priority": payload.priority,
                "stage": payload.stage,
                "next_review_at": payload.next_review_at,
                "due_at": payload.due_at,
                "tags": tags,
                "notes": payload.notes,
                "decision_rationale": payload.decision_rationale,
            },
        )
    return _fetch_workflow(conn, tenant_id, opportunity_id)


def _record_audit_event(
    conn,
    context: Mapping[str, Any],
    request: Request,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: Mapping[str, Any],
) -> None:
    client_host = request.client.host if request.client else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO capture.audit_events (
              tenant_id, actor_user_id, actor_email, action, resource_type,
              resource_id, ip_address, user_agent, metadata
            )
            VALUES (
              %(tenant_id)s::uuid,
              %(actor_user_id)s::uuid,
              %(actor_email)s,
              %(action)s,
              %(resource_type)s,
              %(resource_id)s,
              %(ip_address)s::inet,
              %(user_agent)s,
              %(metadata)s::jsonb
            );
            """,
            {
                "tenant_id": context.get("tenant_id"),
                "actor_user_id": context.get("user_id"),
                "actor_email": context.get("email"),
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "ip_address": client_host,
                "user_agent": request.headers.get("user-agent"),
                "metadata": json.dumps(_json_safe(metadata)),
            },
        )


def _render_capture_brief_markdown(analysis: Mapping[str, Any]) -> str:
    opportunity = analysis.get("opportunity", {})
    baseline = analysis.get("competitive_baseline", {})
    market = analysis.get("market_baseline", {})
    customer = analysis.get("customer_profile", {})
    workflow = analysis.get("workflow", {})
    lines = [
        f"# Capture Brief: {opportunity.get('title', 'Opportunity')}",
        "",
        f"- Notice: {opportunity.get('notice_id', '--')}",
        f"- Agency: {opportunity.get('funding_agency_name', '--')}",
        f"- NAICS/PSC: {opportunity.get('naics_code', '--')} / {opportunity.get('psc_code', '--')}",
        f"- Estimated value: {opportunity.get('estimated_value_min', '--')} - {opportunity.get('estimated_value_max', '--')}",
        f"- Customer profile: {customer.get('company_name', '--')}",
        f"- Company-adjusted P-win: {baseline.get('estimated_p_win', '--')}",
        f"- Market baseline P-win: {market.get('estimated_p_win', '--')}",
        f"- Workflow: {workflow.get('status', 'untracked')} / {workflow.get('go_no_go', 'undecided')}",
        "",
        "## Competing Primes",
    ]
    for prime in analysis.get("competing_primes", [])[:3]:
        lines.append(
            f"- {prime.get('legal_name')} - {prime.get('similar_wins', 0)} similar wins, "
            f"{prime.get('matched_obligation', 0)} matched obligation"
        )
    lines.extend(["", "## Target Teaming Subs"])
    for sub in analysis.get("target_teaming_subs", [])[:5]:
        lines.append(
            f"- {sub.get('legal_name')} - {sub.get('total_engagements', 0)} engagements, "
            f"{sub.get('associated_prime_count', 0)} prime links"
        )
    lines.extend(["", "## Score Evidence"])
    for factor in analysis.get("evidence", {}).get("score_factors", []):
        lines.append(f"- {factor.get('factor')}: {factor.get('score')} - {factor.get('why')}")
    lines.extend(["", "## Source Links"])
    for item in analysis.get("evidence", {}).get("items", [])[:20]:
        url = item.get("source_url") or ""
        suffix = f" ({url})" if url else ""
        lines.append(f"- [{item.get('source_system')}] {item.get('source_title')}{suffix}")
    return "\n".join(lines) + "\n"


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
