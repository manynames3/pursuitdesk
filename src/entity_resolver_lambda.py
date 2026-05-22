from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Mapping

import psycopg2

from .entity_resolver import resolve_vendor_identity


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


def lambda_handler(event: Mapping[str, Any], context: Any) -> Dict[str, Any]:
    failures = []
    resolved = []

    for record in event.get("Records", [event]):
        message_id = str(record.get("messageId", "direct-invoke")) if isinstance(record, Mapping) else "direct-invoke"
        try:
            payload = _record_payload(record)
            with psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=8) as conn:
                resolved.append(resolve_vendor_identity(payload, conn))
        except Exception:
            LOGGER.exception("Failed to resolve entity for message %s", message_id)
            failures.append({"itemIdentifier": message_id})

    return {
        "batchItemFailures": failures,
        "resolvedCount": len(resolved),
        "resolved": resolved if len(resolved) <= 10 else resolved[:10],
    }


def _record_payload(record: Any) -> Dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError("Lambda event record must be a JSON object.")

    if "body" in record:
        body = record["body"]
        if isinstance(body, Mapping):
            return dict(body)
        parsed = json.loads(str(body))
        if not isinstance(parsed, Mapping):
            raise ValueError("SQS record body must decode to a JSON object.")
        return dict(parsed)

    return dict(record)
