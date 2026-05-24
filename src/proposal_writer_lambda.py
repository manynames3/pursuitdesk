from __future__ import annotations

import base64
import json
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


def lambda_handler(event: Mapping[str, Any], _context: Any) -> Dict[str, Any]:
    """Standalone non-VPC Proposal Writer endpoint for Bedrock model access."""
    if _request_method(event) == "OPTIONS":
        return _response(204, {})

    try:
        payload = ProposalWriterRequest(**_json_body(event))
    except Exception as exc:
        return _response(400, {"detail": "Invalid proposal writer request.", "error": type(exc).__name__})

    result = _generate_proposal_writer_response(payload, _request_context(event))
    body = {
        **result,
        "target_section": payload.target_section,
        "opportunity_id": payload.opportunity_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "legal_disclaimer": _procurement_decision_disclaimer(),
    }
    return _response(200, body)


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
