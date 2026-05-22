from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from psycopg2.extras import Json, RealDictCursor

try:
    from botocore.config import Config as BotoConfig
except ImportError:  # pragma: no cover - Lambda package includes botocore with boto3.
    BotoConfig = None


BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
MIN_AUTO_MATCH_SCORE = Decimal(os.getenv("ENTITY_RESOLUTION_AUTO_MATCH_SCORE", "0.91"))
MIN_BEDROCK_MATCH_CONFIDENCE = Decimal(os.getenv("ENTITY_RESOLUTION_BEDROCK_CONFIDENCE", "0.82"))
MIN_CANDIDATE_SCORE = Decimal(os.getenv("ENTITY_RESOLUTION_MIN_CANDIDATE_SCORE", "0.58"))
CORPORATE_SUFFIX_PATTERN = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|limited|ltd|llc|l l c|lp|l p|plc|sa|ag|gmbh|"
    r"holdings|holding|the|division|div|subsidiary|federal|services|systems|solutions|technologies)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EntityCandidate:
    entity_id: str
    legal_name: str
    canonical_uei: Optional[str]
    cage_code: Optional[str]
    alias_names: Sequence[str]
    parent_entity_id: Optional[str]
    similarity_score: Decimal
    exact_normalized_match: bool


def resolve_vendor_identity(raw_payload: Mapping[str, Any], db_connection) -> Dict[str, Any]:
    """
    Resolve an incoming award/subaward vendor into capture.entities.

    The returned dict is intentionally shaped for enrichment pipelines: entity_id is the
    authoritative FK, while write_payload records the database mutation that occurred.
    """
    vendor_name = _extract_vendor_name(raw_payload)
    canonical_uei = _extract_uei(raw_payload)
    cage_code = _extract_cage_code(raw_payload)

    if not vendor_name and not canonical_uei:
        raise ValueError("raw_payload must contain a vendor name or UEI.")

    legal_name = vendor_name or f"Unknown UEI {canonical_uei}"
    source_payload = _json_safe_dict(raw_payload)

    with db_connection:
        if canonical_uei:
            strict_match = _fetch_entity_by_uei(db_connection, canonical_uei)
            if strict_match is not None:
                updated = _merge_alias_metadata(
                    db_connection,
                    entity_id=strict_match["entity_id"],
                    alias_name=legal_name,
                    cage_code=cage_code,
                    canonical_uei=canonical_uei,
                    source_payload=source_payload,
                    strategy="uei_strict_match",
                )
                return {
                    "entity_id": str(strict_match["entity_id"]),
                    "resolution_strategy": "uei_strict_match",
                    "confidence": 1.0,
                    "write_payload": updated,
                    "matched_entity": _entity_summary(strict_match),
                }

        candidates = _fetch_name_candidates(db_connection, legal_name, limit=8)
        exact_candidate = next((candidate for candidate in candidates if candidate.exact_normalized_match), None)
        if exact_candidate is not None:
            updated = _merge_alias_metadata(
                db_connection,
                entity_id=exact_candidate.entity_id,
                alias_name=legal_name,
                cage_code=cage_code,
                canonical_uei=canonical_uei,
                source_payload=source_payload,
                strategy="exact_normalized_name_match",
            )
            return {
                "entity_id": exact_candidate.entity_id,
                "resolution_strategy": "exact_normalized_name_match",
                "confidence": 0.98,
                "write_payload": updated,
                "matched_entity": _candidate_summary(exact_candidate),
            }

        automatic_candidate = _select_unambiguous_candidate(legal_name, candidates)
        if automatic_candidate is not None:
            updated = _merge_alias_metadata(
                db_connection,
                entity_id=automatic_candidate.entity_id,
                alias_name=legal_name,
                cage_code=cage_code,
                canonical_uei=canonical_uei,
                source_payload=source_payload,
                strategy="high_confidence_text_similarity",
            )
            return {
                "entity_id": automatic_candidate.entity_id,
                "resolution_strategy": "high_confidence_text_similarity",
                "confidence": float(automatic_candidate.similarity_score),
                "write_payload": updated,
                "matched_entity": _candidate_summary(automatic_candidate),
            }

        if _requires_bedrock_adjudication(candidates):
            llm_decision = _invoke_bedrock_entity_match(legal_name, canonical_uei, cage_code, candidates)
            matched_candidate = _candidate_by_id(candidates, llm_decision.get("match_entity_id"))
            llm_confidence = Decimal(str(llm_decision.get("confidence", "0")))
            if (
                matched_candidate is not None
                and llm_decision.get("decision") == "match_existing"
                and llm_confidence >= MIN_BEDROCK_MATCH_CONFIDENCE
            ):
                updated = _merge_alias_metadata(
                    db_connection,
                    entity_id=matched_candidate.entity_id,
                    alias_name=legal_name,
                    cage_code=cage_code,
                    canonical_uei=canonical_uei,
                    source_payload={**source_payload, "llm_resolution": llm_decision},
                    strategy="bedrock_semantic_match",
                )
                return {
                    "entity_id": matched_candidate.entity_id,
                    "resolution_strategy": "bedrock_semantic_match",
                    "confidence": float(llm_confidence),
                    "write_payload": updated,
                    "matched_entity": _candidate_summary(matched_candidate),
                    "llm_decision": llm_decision,
                }

        inserted = _insert_or_merge_entity(
            db_connection,
            legal_name=legal_name,
            canonical_uei=canonical_uei,
            cage_code=cage_code,
            aliases=[],
            source_payload=source_payload,
            strategy="new_entity_created",
        )
        return {
            "entity_id": inserted["entity_id"],
            "resolution_strategy": "new_entity_created",
            "confidence": 1.0 if canonical_uei else 0.72,
            "write_payload": inserted,
            "matched_entity": {
                "entity_id": inserted["entity_id"],
                "legal_name": inserted["legal_name"],
                "canonical_uei": inserted["canonical_uei"],
                "cage_code": inserted["cage_code"],
            },
        }


def _fetch_entity_by_uei(conn, canonical_uei: str) -> Optional[Dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT entity_id, legal_name, canonical_uei, cage_code, alias_names, parent_entity_id
            FROM capture.entities
            WHERE canonical_uei = %(canonical_uei)s
            LIMIT 1
            FOR UPDATE;
            """,
            {"canonical_uei": canonical_uei},
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _fetch_name_candidates(conn, raw_name: str, limit: int) -> List[EntityCandidate]:
    normalized_compact = _compact_name(raw_name)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            WITH incoming AS (
              SELECT
                %(raw_name)s::text AS raw_name,
                capture.normalize_entity_name(%(raw_name)s::text) AS normalized_name,
                %(normalized_compact)s::text AS compact_name
            ),
            candidate_scores AS (
              SELECT
                e.entity_id,
                e.legal_name,
                e.canonical_uei,
                e.cage_code,
                e.alias_names,
                e.parent_entity_id,
                GREATEST(
                  similarity(e.normalized_legal_name, i.normalized_name),
                  similarity(capture.normalize_entity_name(e.legal_name), i.normalized_name),
                  COALESCE(alias_scores.alias_similarity, 0)
                )::numeric AS similarity_score,
                (
                  e.normalized_legal_name = i.normalized_name
                  OR regexp_replace(capture.normalize_entity_name(e.legal_name), '[[:space:]]+', '', 'g') = i.compact_name
                  OR COALESCE(alias_scores.exact_alias_match, false)
                ) AS exact_normalized_match
              FROM capture.entities e
              CROSS JOIN incoming i
              LEFT JOIN LATERAL (
                SELECT
                  MAX(similarity(capture.normalize_entity_name(alias_value), i.normalized_name)) AS alias_similarity,
                  BOOL_OR(capture.normalize_entity_name(alias_value) = i.normalized_name) AS exact_alias_match
                FROM unnest(e.alias_names) AS alias_value
              ) alias_scores ON true
              WHERE
                e.legal_name %% i.raw_name
                OR e.normalized_legal_name %% i.normalized_name
                OR e.normalized_legal_name = i.normalized_name
                OR COALESCE(alias_scores.alias_similarity, 0) >= %(min_candidate_score)s
            )
            SELECT *
            FROM candidate_scores
            WHERE similarity_score >= %(min_candidate_score)s OR exact_normalized_match
            ORDER BY exact_normalized_match DESC, similarity_score DESC, legal_name
            LIMIT %(limit)s;
            """,
            {
                "raw_name": raw_name,
                "normalized_compact": normalized_compact,
                "min_candidate_score": MIN_CANDIDATE_SCORE,
                "limit": limit,
            },
        )
        rows = cur.fetchall()

    return [
        EntityCandidate(
            entity_id=str(row["entity_id"]),
            legal_name=row["legal_name"],
            canonical_uei=row["canonical_uei"],
            cage_code=row["cage_code"],
            alias_names=row["alias_names"] or [],
            parent_entity_id=str(row["parent_entity_id"]) if row["parent_entity_id"] else None,
            similarity_score=Decimal(str(row["similarity_score"])),
            exact_normalized_match=bool(row["exact_normalized_match"]),
        )
        for row in rows
    ]


def _merge_alias_metadata(
    conn,
    entity_id: str,
    alias_name: str,
    cage_code: Optional[str],
    canonical_uei: Optional[str],
    source_payload: Mapping[str, Any],
    strategy: str,
) -> Dict[str, Any]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            UPDATE capture.entities
            SET
              canonical_uei = COALESCE(capture.entities.canonical_uei, %(canonical_uei)s),
              cage_code = COALESCE(capture.entities.cage_code, %(cage_code)s),
              alias_names = CASE
                WHEN %(alias_name)s IS NULL
                  OR capture.normalize_entity_name(%(alias_name)s) = normalized_legal_name
                  OR EXISTS (
                    SELECT 1
                    FROM unnest(alias_names) AS existing_alias
                    WHERE capture.normalize_entity_name(existing_alias) = capture.normalize_entity_name(%(alias_name)s)
                  )
                THEN alias_names
                ELSE array_append(alias_names, %(alias_name)s)
              END,
              source_payload = source_payload || %(source_payload)s::jsonb,
              source_system = 'SAM.gov',
              updated_at = now()
            WHERE entity_id = %(entity_id)s::uuid
            RETURNING
              entity_id::text,
              legal_name,
              canonical_uei,
              cage_code,
              alias_names,
              parent_entity_id::text,
              %(strategy)s::text AS write_strategy;
            """,
            {
                "entity_id": entity_id,
                "alias_name": _clean_text(alias_name),
                "canonical_uei": canonical_uei,
                "cage_code": cage_code,
                "source_payload": Json({"last_resolution": {"strategy": strategy, "raw_payload": source_payload}}),
                "strategy": strategy,
            },
        )
        row = cur.fetchone()
    return _json_safe_dict(row)


def _insert_or_merge_entity(
    conn,
    legal_name: str,
    canonical_uei: Optional[str],
    cage_code: Optional[str],
    aliases: Sequence[str],
    source_payload: Mapping[str, Any],
    strategy: str,
) -> Dict[str, Any]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO capture.entities (
              legal_name,
              canonical_uei,
              cage_code,
              alias_names,
              source_system,
              source_payload
            )
            VALUES (
              %(legal_name)s,
              %(canonical_uei)s,
              %(cage_code)s,
              %(alias_names)s::text[],
              'SAM.gov',
              %(source_payload)s::jsonb
            )
            ON CONFLICT (normalized_legal_name)
            DO UPDATE SET
              canonical_uei = COALESCE(capture.entities.canonical_uei, EXCLUDED.canonical_uei),
              cage_code = COALESCE(capture.entities.cage_code, EXCLUDED.cage_code),
              alias_names = (
                SELECT ARRAY(
                  SELECT DISTINCT alias_value
                  FROM unnest(capture.entities.alias_names || EXCLUDED.alias_names) AS alias_value
                  WHERE alias_value IS NOT NULL AND length(trim(alias_value)) > 0
                  ORDER BY alias_value
                )
              ),
              source_payload = capture.entities.source_payload || EXCLUDED.source_payload,
              updated_at = now()
            RETURNING
              entity_id::text,
              legal_name,
              canonical_uei,
              cage_code,
              alias_names,
              parent_entity_id::text,
              %(strategy)s::text AS write_strategy;
            """,
            {
                "legal_name": legal_name,
                "canonical_uei": canonical_uei,
                "cage_code": cage_code,
                "alias_names": list(aliases),
                "source_payload": Json({"last_resolution": {"strategy": strategy, "raw_payload": source_payload}}),
                "strategy": strategy,
            },
        )
        row = cur.fetchone()
    return _json_safe_dict(row)


def _select_unambiguous_candidate(
    raw_name: str,
    candidates: Sequence[EntityCandidate],
) -> Optional[EntityCandidate]:
    if not candidates:
        return None
    top = candidates[0]
    runner_up_score = candidates[1].similarity_score if len(candidates) > 1 else Decimal("0")
    suffix_stripped_match = _strip_corporate_noise(raw_name) == _strip_corporate_noise(top.legal_name)
    if top.similarity_score >= MIN_AUTO_MATCH_SCORE and (top.similarity_score - runner_up_score) >= Decimal("0.08"):
        return top
    if suffix_stripped_match and top.similarity_score >= Decimal("0.84"):
        return top
    return None


def _requires_bedrock_adjudication(candidates: Sequence[EntityCandidate]) -> bool:
    if not candidates:
        return False
    if len(candidates) == 1:
        return candidates[0].similarity_score >= Decimal("0.72")
    return candidates[0].similarity_score >= Decimal("0.66")


def _invoke_bedrock_entity_match(
    raw_name: str,
    canonical_uei: Optional[str],
    cage_code: Optional[str],
    candidates: Sequence[EntityCandidate],
) -> Dict[str, Any]:
    import boto3

    system_prompt = (
        "You are an entity-resolution adjudicator for U.S. federal procurement data. "
        "Decide only whether the incoming vendor name is an alias, operating division, "
        "subsidiary, or direct naming variant of one candidate company. "
        "Return strict JSON and no prose. If evidence is insufficient, choose create_new."
    )
    candidate_payload = [
        {
            "entity_id": candidate.entity_id,
            "legal_name": candidate.legal_name,
            "canonical_uei": candidate.canonical_uei,
            "cage_code": candidate.cage_code,
            "alias_names": list(candidate.alias_names)[:12],
            "parent_entity_id": candidate.parent_entity_id,
            "text_similarity_score": float(candidate.similarity_score),
        }
        for candidate in candidates
    ]
    user_payload = {
        "incoming_vendor": {
            "raw_name": raw_name,
            "canonical_uei": canonical_uei,
            "cage_code": cage_code,
        },
        "candidate_entities": candidate_payload,
        "required_json_schema": {
            "decision": "match_existing | create_new",
            "match_entity_id": "uuid string or null",
            "confidence": "number from 0.0 to 1.0",
            "standardized_legal_name": "string",
            "alias_to_record": "string or null",
            "reason": "short string",
        },
    }

    client_kwargs: Dict[str, Any] = {"service_name": "bedrock-runtime", "region_name": BEDROCK_REGION}
    if BotoConfig is not None:
        client_kwargs["config"] = BotoConfig(connect_timeout=2, read_timeout=8, retries={"max_attempts": 2})
    client = boto3.client(**client_kwargs)
    response = client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 420,
                "temperature": 0,
                "system": system_prompt,
                "messages": [{"role": "user", "content": json.dumps(user_payload, separators=(",", ":"))}],
            }
        ),
    )
    response_body = json.loads(response["body"].read())
    text = "".join(part.get("text", "") for part in response_body.get("content", []) if part.get("type") == "text")
    decision = _parse_llm_json(text)
    if decision.get("decision") not in {"match_existing", "create_new"}:
        return {"decision": "create_new", "match_entity_id": None, "confidence": 0.0, "reason": "invalid_decision"}
    if decision.get("match_entity_id") and _candidate_by_id(candidates, decision["match_entity_id"]) is None:
        return {"decision": "create_new", "match_entity_id": None, "confidence": 0.0, "reason": "unknown_candidate_id"}
    decision["confidence"] = max(0.0, min(1.0, float(decision.get("confidence", 0.0))))
    return decision


def _parse_llm_json(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _candidate_by_id(candidates: Sequence[EntityCandidate], entity_id: Any) -> Optional[EntityCandidate]:
    if entity_id is None:
        return None
    try:
        needle = str(uuid.UUID(str(entity_id)))
    except ValueError:
        return None
    return next((candidate for candidate in candidates if candidate.entity_id == needle), None)


def _extract_vendor_name(payload: Mapping[str, Any]) -> Optional[str]:
    direct_keys = (
        "vendor_name",
        "raw_vendor_name",
        "awardee_name",
        "recipient_name",
        "legal_business_name",
        "legalBusinessName",
        "businessName",
        "name",
    )
    for key in direct_keys:
        value = _clean_text(payload.get(key))
        if value:
            return value
    for key in ("awardee", "vendor", "recipient", "contractor"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            value = _extract_vendor_name(nested)
            if value:
                return value
    return None


def _extract_uei(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("uei", "ueiSAM", "uei_sam", "sam_uei", "unique_entity_id", "uniqueEntityId"):
        value = _clean_uei(payload.get(key))
        if value:
            return value
    for key in ("awardee", "vendor", "recipient", "contractor"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            value = _extract_uei(nested)
            if value:
                return value
    return None


def _extract_cage_code(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("cage_code", "cageCode", "cage", "cageCodeSAM"):
        value = _clean_text(payload.get(key))
        if value and re.fullmatch(r"[A-Z0-9]{5}", value.upper()):
            return value.upper()
    for key in ("awardee", "vendor", "recipient", "contractor"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            value = _extract_cage_code(nested)
            if value:
                return value
    return None


def _clean_uei(value: Any) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]", "", text).upper()
    return normalized if re.fullmatch(r"[A-Z0-9]{12}", normalized) else None


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "unassigned", "not provided", "n/a"}:
        return None
    return re.sub(r"\s+", " ", text)


def _compact_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", value.lower())
    return cleaned


def _strip_corporate_noise(value: str) -> str:
    lowered = value.lower()
    lowered = CORPORATE_SUFFIX_PATTERN.sub(" ", lowered)
    return re.sub(r"[^a-z0-9]+", "", lowered)


def _candidate_summary(candidate: EntityCandidate) -> Dict[str, Any]:
    return {
        "entity_id": candidate.entity_id,
        "legal_name": candidate.legal_name,
        "canonical_uei": candidate.canonical_uei,
        "cage_code": candidate.cage_code,
        "parent_entity_id": candidate.parent_entity_id,
        "similarity_score": float(candidate.similarity_score),
    }


def _entity_summary(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "entity_id": str(row["entity_id"]),
        "legal_name": row["legal_name"],
        "canonical_uei": row["canonical_uei"],
        "cage_code": row["cage_code"],
        "parent_entity_id": str(row["parent_entity_id"]) if row.get("parent_entity_id") else None,
    }


def _json_safe_dict(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        return {"value": _json_safe(value)}
    return {str(key): _json_safe(item) for key, item in value.items()}


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _json_safe_dict(value)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return value
