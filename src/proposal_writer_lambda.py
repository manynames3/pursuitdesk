from __future__ import annotations

import base64
import json
import os
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from .api_v1_endpoints import (
    AUTH_REQUIRED,
    DEFAULT_TENANT_SLUG,
    ProposalWriterRequest,
    _generate_proposal_writer_response,
    _json_safe,
    _procurement_decision_disclaimer,
)

PROPOSAL_JOBS_TABLE = os.getenv("PROPOSAL_JOBS_TABLE", "")
PROPOSAL_JOB_TTL_SECONDS = int(os.getenv("PROPOSAL_JOB_TTL_SECONDS", "2592000"))


def lambda_handler(event: Mapping[str, Any], _context: Any) -> Dict[str, Any]:
    """Standalone non-VPC Proposal Writer endpoint for Bedrock model access."""
    if event.get("action") == "run_proposal_writer_job":
        return _run_proposal_writer_job(str(event.get("job_id") or ""))

    if _request_method(event) == "OPTIONS":
        return _response(204, {})

    if _request_method(event) == "GET":
        if _is_jobs_collection_request(event):
            return _list_proposal_writer_jobs(event)
        return _get_proposal_writer_job(event)

    try:
        payload = ProposalWriterRequest(**_json_body(event))
    except Exception as exc:
        return _response(400, {"detail": "Invalid proposal writer request.", "error": type(exc).__name__})

    if PROPOSAL_JOBS_TABLE:
        return _submit_proposal_writer_job(event, payload)

    result = _generate_proposal_writer_response(payload, _request_context(event))
    body = {
        **result,
        "target_section": payload.target_section,
        "opportunity_id": payload.opportunity_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "legal_disclaimer": _procurement_decision_disclaimer(),
    }
    return _response(200, body)


def _submit_proposal_writer_job(event: Mapping[str, Any], payload: ProposalWriterRequest) -> Dict[str, Any]:
    job_id = uuid4().hex
    now = _now_iso()
    context = _request_context(event)
    item = {
        "job_id": job_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "expires_at": _ttl_epoch(),
        "target_section": payload.target_section,
        "opportunity_id": payload.opportunity_id,
        "opportunity_title": payload.opportunity_title,
        "tenant_slug": context.get("tenant_slug"),
        "payload_json": payload.model_dump_json(),
        "context_json": json.dumps(context, default=str),
    }
    _jobs_table().put_item(Item=item)
    _invoke_job_worker(job_id)
    return _response(
        202,
        {
            "job_id": job_id,
            "status": "queued",
            "generation_mode": "async_bedrock_proposal_job",
            "target_section": payload.target_section,
            "opportunity_id": payload.opportunity_id,
            "poll_url": f"/api/v1/proposal-writer/jobs/{job_id}",
            "submitted_at": now,
            "legal_disclaimer": _procurement_decision_disclaimer(),
        },
    )


def _get_proposal_writer_job(event: Mapping[str, Any]) -> Dict[str, Any]:
    job_id = _job_id_from_event(event)
    if not job_id:
        return _response(404, {"detail": "Proposal Writer job not found."})
    item = _load_job(job_id)
    if not item:
        return _response(404, {"detail": "Proposal Writer job not found.", "job_id": job_id})
    context = _request_context(event)
    if item.get("tenant_slug") and item.get("tenant_slug") != context.get("tenant_slug"):
        return _response(404, {"detail": "Proposal Writer job not found.", "job_id": job_id})
    return _response(200, _job_public_payload(item))


def _list_proposal_writer_jobs(event: Mapping[str, Any]) -> Dict[str, Any]:
    if not PROPOSAL_JOBS_TABLE:
        return _response(200, {"items": [], "count": 0, "tenant_slug": _request_context(event).get("tenant_slug")})

    from boto3.dynamodb.conditions import Attr, Key

    context = _request_context(event)
    params = _query_params(event)
    tenant_slug = str(context.get("tenant_slug") or DEFAULT_TENANT_SLUG)
    opportunity_id = str(params.get("opportunity_id") or "").strip()
    limit = _bounded_limit(params.get("limit"), default=20, maximum=50)
    items = []
    response: Dict[str, Any] = {}
    query_kwargs: Dict[str, Any] = {
        "IndexName": "tenant-created-at-index",
        "KeyConditionExpression": Key("tenant_slug").eq(tenant_slug),
        "ScanIndexForward": False,
        "Limit": min(max(limit * 3, limit), 100),
    }
    if opportunity_id:
        query_kwargs["FilterExpression"] = Attr("opportunity_id").eq(opportunity_id)

    try:
        while len(items) < limit:
            if response.get("LastEvaluatedKey"):
                query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = _jobs_table().query(**query_kwargs)
            items.extend(response.get("Items") or [])
            if not response.get("LastEvaluatedKey"):
                break
    except Exception as exc:
        return _response(
            503,
            {
                "detail": "Proposal history is not available yet.",
                "error": type(exc).__name__,
            },
        )

    summaries = [_job_summary_payload(item) for item in items[:limit]]
    return _response(
        200,
        {
            "items": summaries,
            "count": len(summaries),
            "tenant_slug": tenant_slug,
            "opportunity_id": opportunity_id or None,
        },
    )


def _run_proposal_writer_job(job_id: str) -> Dict[str, Any]:
    if not job_id:
        return {"ok": False, "error": "missing_job_id"}
    item = _load_job(job_id)
    if not item:
        return {"ok": False, "error": "job_not_found", "job_id": job_id}
    if item.get("status") == "succeeded":
        return {"ok": True, "job_id": job_id, "status": "succeeded"}

    _update_job(
        job_id,
        {
            "status": "running",
            "started_at": _now_iso(),
            "updated_at": _now_iso(),
        },
    )
    try:
        payload = ProposalWriterRequest(**json.loads(str(item.get("payload_json") or "{}")))
        context = json.loads(str(item.get("context_json") or "{}"))
        result = _generate_proposal_writer_response(payload, context)
        completed_at = _now_iso()
        _update_job(
            job_id,
            {
                "status": "succeeded",
                "updated_at": completed_at,
                "completed_at": completed_at,
                "draft": result.get("draft", ""),
                "generation_mode": result.get("generation_mode", ""),
                "model_trace_json": json.dumps(_json_safe(result.get("model_trace") or []), default=str),
                "legal_disclaimer_json": json.dumps(_procurement_decision_disclaimer(), default=str),
            },
        )
        return {"ok": True, "job_id": job_id, "status": "succeeded"}
    except Exception as exc:
        failed_at = _now_iso()
        _update_job(
            job_id,
            {
                "status": "failed",
                "updated_at": failed_at,
                "completed_at": failed_at,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        return {"ok": False, "job_id": job_id, "status": "failed", "error": type(exc).__name__}


def _jobs_table():
    import boto3

    return boto3.resource("dynamodb").Table(PROPOSAL_JOBS_TABLE)


def _invoke_job_worker(job_id: str) -> None:
    import boto3

    boto3.client("lambda").invoke(
        FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps({"action": "run_proposal_writer_job", "job_id": job_id}).encode("utf-8"),
    )


def _load_job(job_id: str) -> Dict[str, Any]:
    response = _jobs_table().get_item(Key={"job_id": job_id}, ConsistentRead=True)
    return response.get("Item") or {}


def _update_job(job_id: str, values: Mapping[str, Any]) -> None:
    names: Dict[str, str] = {}
    expression_values: Dict[str, Any] = {}
    assignments = []
    for index, (key, value) in enumerate(values.items()):
        name_key = f"#k{index}"
        value_key = f":v{index}"
        names[name_key] = key
        expression_values[value_key] = value
        assignments.append(f"{name_key} = {value_key}")
    _jobs_table().update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET " + ", ".join(assignments),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=expression_values,
    )


def _job_public_payload(item: Mapping[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "job_id": item.get("job_id"),
        "status": item.get("status"),
        "target_section": item.get("target_section"),
        "opportunity_id": item.get("opportunity_id"),
        "opportunity_title": item.get("opportunity_title"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "started_at": item.get("started_at"),
        "completed_at": item.get("completed_at"),
        "generation_mode": item.get("generation_mode") or "async_bedrock_proposal_job",
        "has_draft": bool(str(item.get("draft") or "").strip()),
        "legal_disclaimer": _procurement_decision_disclaimer(),
    }
    if item.get("draft"):
        payload["draft"] = item.get("draft")
    if item.get("model_trace_json"):
        payload["model_trace"] = json.loads(str(item.get("model_trace_json")))
    if item.get("error"):
        payload["error"] = item.get("error")
    return payload


def _job_summary_payload(item: Mapping[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "job_id": item.get("job_id"),
        "status": item.get("status"),
        "target_section": item.get("target_section"),
        "opportunity_id": item.get("opportunity_id"),
        "opportunity_title": item.get("opportunity_title"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "started_at": item.get("started_at"),
        "completed_at": item.get("completed_at"),
        "generation_mode": item.get("generation_mode") or "async_bedrock_proposal_job",
        "has_draft": bool(str(item.get("draft") or "").strip()),
    }
    if item.get("error"):
        payload["error"] = item.get("error")
    return payload


def _is_jobs_collection_request(event: Mapping[str, Any]) -> bool:
    path_parameters = event.get("pathParameters") or {}
    if path_parameters.get("job_id"):
        return False
    path = str(event.get("rawPath") or event.get("path") or "").rstrip("/")
    return path == "/api/v1/proposal-writer/jobs"


def _query_params(event: Mapping[str, Any]) -> Dict[str, Any]:
    return dict(event.get("queryStringParameters") or {})


def _bounded_limit(value: Any, default: int, maximum: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, maximum))


def _job_id_from_event(event: Mapping[str, Any]) -> str:
    path_parameters = event.get("pathParameters") or {}
    if path_parameters.get("job_id"):
        return str(path_parameters["job_id"])
    path = str(event.get("rawPath") or event.get("path") or "")
    marker = "/api/v1/proposal-writer/jobs/"
    if marker in path:
        return path.split(marker, 1)[1].strip("/")
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp()) + PROPOSAL_JOB_TTL_SECONDS


def _json_body(event: Mapping[str, Any]) -> Dict[str, Any]:
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    value = json.loads(raw_body)
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object.")
    return value


def _request_context(event: Mapping[str, Any]) -> Dict[str, Any]:
    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items() if v is not None}
    tenant_slug = headers.get("x-captureos-tenant") or DEFAULT_TENANT_SLUG
    user_email = headers.get("x-captureos-user") or "proposal.writer@example.com"
    return {
        "tenant_slug": tenant_slug,
        "tenant_name": tenant_slug.replace("-", " ").title(),
        "email": user_email,
        "roles": ["consultant"],
        "auth_mode": "proposal_writer_lambda",
    }


def _request_method(event: Mapping[str, Any]) -> str:
    return str(event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod") or "").upper()


def _response(status_code: int, body: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "body": "" if status_code == 204 else json.dumps(_json_safe(body), default=str),
        "headers": {
            "content-type": "application/json",
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "strict-origin-when-cross-origin",
            "permissions-policy": "camera=(), microphone=(), geolocation=()",
            "content-security-policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
            "x-captureos-auth-required": "true" if AUTH_REQUIRED else "false",
        },
        "isBase64Encoded": False,
    }
