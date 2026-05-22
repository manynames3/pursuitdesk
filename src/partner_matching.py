from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, Mapping, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor, register_default_jsonb


def connect_from_env(dsn: Optional[str] = None):
    return psycopg2.connect(dsn or os.environ["DATABASE_URL"], connect_timeout=10)


def find_best_teaming_partners(
    conn,
    opportunity_id: str,
    our_entity_id: Optional[str] = None,
    historical_limit: int = 75,
    top_primes: int = 3,
    subs_per_prime: int = 5,
    team_sub_limit: int = 12,
) -> Dict[str, Any]:
    """
    Return competing primes, frequent subcontractors, and a baseline P(win) estimate.

    opportunity_id may be either capture.opportunities.opportunity_id (UUID) or notice_id.
    our_entity_id is optional; when provided, the P(win) model includes direct prime/sub history.
    """
    register_default_jsonb(conn, loads=json.loads)

    target_predicate, target_params = _target_predicate(opportunity_id)
    our_entity_uuid = _optional_uuid(our_entity_id, "our_entity_id")

    target = _fetch_target(conn, target_predicate, target_params)
    if target is None:
        raise ValueError(f"Opportunity was not found: {opportunity_id}")
    if not target["has_sow_embedding"]:
        raise ValueError(f"Opportunity {opportunity_id} has no sow_embedding; semantic matching cannot run.")

    params: Dict[str, Any] = {
        **target_params,
        "our_entity_id": our_entity_uuid,
        "historical_limit": max(1, int(historical_limit)),
        "top_primes": max(1, int(top_primes)),
        "subs_per_prime": max(1, int(subs_per_prime)),
        "team_sub_limit": max(1, int(team_sub_limit)),
    }

    sql = f"""
    WITH target AS (
      SELECT
        opportunity_id,
        notice_id,
        title,
        naics_code,
        psc_code,
        funding_agency_code,
        funding_agency_name,
        set_aside_code,
        estimated_value_min,
        estimated_value_max,
        sow_embedding
      FROM capture.opportunities
      WHERE {target_predicate}
    ),
    candidate_awards AS MATERIALIZED (
      SELECT
        a.award_id,
        a.prime_entity_id,
        a.piid,
        a.award_number,
        a.title,
        a.signed_date,
        a.naics_code,
        a.psc_code,
        a.funding_agency_code,
        COALESCE(a.total_obligation, a.current_total_value, a.potential_total_value, 0)::numeric AS award_value,
        GREATEST(0.0, 1.0 - (a.description_embedding <=> t.sow_embedding))::double precision AS semantic_similarity,
        CASE WHEN a.naics_code IS NOT NULL AND t.naics_code IS NOT NULL AND a.naics_code = t.naics_code THEN 1.0 ELSE 0.0 END AS naics_match,
        CASE WHEN a.psc_code IS NOT NULL AND t.psc_code IS NOT NULL AND a.psc_code = t.psc_code THEN 1.0 ELSE 0.0 END AS psc_match,
        CASE WHEN a.funding_agency_code IS NOT NULL AND t.funding_agency_code IS NOT NULL AND a.funding_agency_code = t.funding_agency_code THEN 1.0 ELSE 0.0 END AS agency_match,
        CASE
          WHEN a.signed_date IS NULL THEN 0.35
          ELSE LEAST(1.0, GREATEST(0.0, 1.0 - (EXTRACT(YEAR FROM age(current_date, a.signed_date)) / 10.0)))
        END AS recency_score
      FROM capture.awards a
      CROSS JOIN target t
      WHERE a.description_embedding IS NOT NULL
      ORDER BY a.description_embedding <=> t.sow_embedding
      LIMIT %(historical_limit)s
    ),
    scored_awards AS (
      SELECT
        ca.*,
        (
          0.58 * ca.semantic_similarity
          + 0.16 * ca.naics_match
          + 0.10 * ca.psc_match
          + 0.10 * ca.agency_match
          + 0.06 * ca.recency_score
        )::double precision AS match_score
      FROM candidate_awards ca
    ),
    prime_rollup AS (
      SELECT
        e.entity_id AS prime_entity_id,
        e.legal_name AS prime_name,
        e.canonical_uei,
        e.cage_code,
        COUNT(*)::int AS similar_wins,
        AVG(sa.match_score)::double precision AS avg_match_score,
        AVG(sa.semantic_similarity)::double precision AS avg_semantic_similarity,
        SUM(sa.award_value)::numeric AS matched_obligation,
        JSONB_AGG(
          JSONB_BUILD_OBJECT(
            'award_id', sa.award_id::text,
            'piid', sa.piid,
            'award_number', sa.award_number,
            'title', sa.title,
            'signed_date', sa.signed_date,
            'award_value', sa.award_value,
            'match_score', ROUND(sa.match_score::numeric, 4),
            'semantic_similarity', ROUND(sa.semantic_similarity::numeric, 4)
          )
          ORDER BY sa.match_score DESC, sa.award_value DESC
        ) AS representative_awards
      FROM scored_awards sa
      JOIN capture.entities e ON e.entity_id = sa.prime_entity_id
      GROUP BY e.entity_id, e.legal_name, e.canonical_uei, e.cage_code
    ),
    ranked_primes AS (
      SELECT
        pr.*,
        ROW_NUMBER() OVER (
          ORDER BY pr.avg_match_score DESC, pr.similar_wins DESC, pr.matched_obligation DESC
        ) AS prime_rank
      FROM prime_rollup pr
    ),
    top_primes AS (
      SELECT *
      FROM ranked_primes
      WHERE prime_rank <= %(top_primes)s
    ),
    sub_rollup AS (
      SELECT
        tp.prime_entity_id,
        sub.entity_id AS subcontractor_entity_id,
        sub.legal_name AS subcontractor_name,
        sub.canonical_uei,
        sub.cage_code,
        COUNT(*)::int AS engagement_count,
        COALESCE(SUM(sw.amount), 0)::numeric AS total_subaward_value,
        MAX(sw.action_date) AS last_seen,
        ARRAY_AGG(DISTINCT sw.subaward_number) FILTER (WHERE sw.subaward_number IS NOT NULL) AS subaward_numbers
      FROM top_primes tp
      JOIN scored_awards sa ON sa.prime_entity_id = tp.prime_entity_id
      JOIN capture.sub_awards sw
        ON sw.award_id = sa.award_id
       AND sw.prime_entity_id = tp.prime_entity_id
      JOIN capture.entities sub ON sub.entity_id = sw.subcontractor_entity_id
      GROUP BY tp.prime_entity_id, sub.entity_id, sub.legal_name, sub.canonical_uei, sub.cage_code
    ),
    ranked_subs AS (
      SELECT
        sr.*,
        ROW_NUMBER() OVER (
          PARTITION BY sr.prime_entity_id
          ORDER BY sr.engagement_count DESC, sr.total_subaward_value DESC, sr.last_seen DESC NULLS LAST
        ) AS sub_rank
      FROM sub_rollup sr
    ),
    prime_json AS (
      SELECT COALESCE(
        JSONB_AGG(
          JSONB_BUILD_OBJECT(
            'rank', tp.prime_rank,
            'prime_entity_id', tp.prime_entity_id::text,
            'legal_name', tp.prime_name,
            'canonical_uei', tp.canonical_uei,
            'cage_code', tp.cage_code,
            'similar_wins', tp.similar_wins,
            'avg_match_score', ROUND(tp.avg_match_score::numeric, 4),
            'avg_semantic_similarity', ROUND(tp.avg_semantic_similarity::numeric, 4),
            'matched_obligation', tp.matched_obligation,
            'representative_awards', tp.representative_awards,
            'frequent_subcontractors', COALESCE(
              (
                SELECT JSONB_AGG(
                  JSONB_BUILD_OBJECT(
                    'rank', rs.sub_rank,
                    'subcontractor_entity_id', rs.subcontractor_entity_id::text,
                    'legal_name', rs.subcontractor_name,
                    'canonical_uei', rs.canonical_uei,
                    'cage_code', rs.cage_code,
                    'engagement_count', rs.engagement_count,
                    'total_subaward_value', rs.total_subaward_value,
                    'last_seen', rs.last_seen,
                    'subaward_numbers', COALESCE(rs.subaward_numbers, ARRAY[]::text[])
                  )
                  ORDER BY rs.sub_rank
                )
                FROM (
                  SELECT *
                  FROM ranked_subs
                  WHERE prime_entity_id = tp.prime_entity_id
                  ORDER BY sub_rank
                  LIMIT %(subs_per_prime)s
                ) rs
              ),
              '[]'::jsonb
            )
          )
          ORDER BY tp.prime_rank
        ),
        '[]'::jsonb
      ) AS competing_primes
      FROM top_primes tp
    ),
    target_teaming_subs AS (
      SELECT COALESCE(
        JSONB_AGG(
          JSONB_BUILD_OBJECT(
            'subcontractor_entity_id', aggregated.subcontractor_entity_id::text,
            'legal_name', aggregated.subcontractor_name,
            'canonical_uei', aggregated.canonical_uei,
            'cage_code', aggregated.cage_code,
            'associated_prime_count', aggregated.associated_prime_count,
            'total_engagements', aggregated.total_engagements,
            'total_subaward_value', aggregated.total_subaward_value,
            'last_seen', aggregated.last_seen,
            'associated_primes', aggregated.associated_primes
          )
          ORDER BY aggregated.associated_prime_count DESC,
                   aggregated.total_engagements DESC,
                   aggregated.total_subaward_value DESC
        ),
        '[]'::jsonb
      ) AS target_teaming_subs
      FROM (
        SELECT
          rs.subcontractor_entity_id,
          rs.subcontractor_name,
          rs.canonical_uei,
          rs.cage_code,
          COUNT(DISTINCT rs.prime_entity_id)::int AS associated_prime_count,
          SUM(rs.engagement_count)::int AS total_engagements,
          SUM(rs.total_subaward_value)::numeric AS total_subaward_value,
          MAX(rs.last_seen) AS last_seen,
          JSONB_AGG(
            JSONB_BUILD_OBJECT(
              'prime_entity_id', tp.prime_entity_id::text,
              'prime_name', tp.prime_name,
              'prime_rank', tp.prime_rank,
              'engagement_count', rs.engagement_count,
              'total_subaward_value', rs.total_subaward_value
            )
            ORDER BY rs.engagement_count DESC, tp.prime_rank
          ) AS associated_primes
        FROM ranked_subs rs
        JOIN top_primes tp ON tp.prime_entity_id = rs.prime_entity_id
        WHERE rs.sub_rank <= %(subs_per_prime)s
        GROUP BY rs.subcontractor_entity_id, rs.subcontractor_name, rs.canonical_uei, rs.cage_code
        ORDER BY associated_prime_count DESC, total_engagements DESC, total_subaward_value DESC
        LIMIT %(team_sub_limit)s
      ) aggregated
    ),
    baseline AS (
      SELECT
        COUNT(*)::int AS historical_match_count,
        COUNT(DISTINCT prime_entity_id)::int AS competing_prime_count,
        COALESCE(AVG(match_score), 0.0)::double precision AS avg_match_score,
        COALESCE(MAX(match_score), 0.0)::double precision AS top_match_score,
        COALESCE(AVG(semantic_similarity), 0.0)::double precision AS avg_semantic_similarity,
        COALESCE(AVG(agency_match), 0.0)::double precision AS agency_match_rate,
        COALESCE(AVG(naics_match), 0.0)::double precision AS naics_match_rate,
        COALESCE(SUM(award_value), 0)::numeric AS total_matched_obligation
      FROM scored_awards
    ),
    prime_counts AS (
      SELECT prime_entity_id, COUNT(*)::int AS wins
      FROM scored_awards
      GROUP BY prime_entity_id
    ),
    concentration AS (
      SELECT COALESCE(
        MAX(pc.wins::double precision / NULLIF((SELECT historical_match_count FROM baseline), 0)),
        0.0
      ) AS incumbent_concentration
      FROM prime_counts pc
    ),
    partner_depth AS (
      SELECT LEAST(
        1.0,
        COALESCE(
          COUNT(*) FILTER (WHERE sub_rank <= %(subs_per_prime)s)::double precision
          / NULLIF((%(top_primes)s * %(subs_per_prime)s)::double precision, 0.0),
          0.0
        )
      ) AS partner_depth_score
      FROM ranked_subs
    ),
    our_history AS (
      SELECT
        LEAST(
          1.0,
          COUNT(*) FILTER (WHERE sa.prime_entity_id = %(our_entity_id)s::uuid)::double precision / 5.0
        ) AS our_prime_signal,
        LEAST(
          1.0,
          COUNT(DISTINCT sw.award_id) FILTER (WHERE sw.subcontractor_entity_id = %(our_entity_id)s::uuid)::double precision / 5.0
        ) AS our_sub_signal
      FROM scored_awards sa
      LEFT JOIN capture.sub_awards sw ON sw.award_id = sa.award_id
    ),
    pwin_features AS (
      SELECT
        b.*,
        c.incumbent_concentration,
        pd.partner_depth_score,
        oh.our_prime_signal,
        oh.our_sub_signal,
        GREATEST(oh.our_prime_signal, 0.65 * oh.our_sub_signal) AS our_relevance_signal,
        LEAST(
          0.88,
          GREATEST(
            0.05,
            1.0 / (
              1.0 + EXP(-(
                -1.85
                + 2.80 * b.avg_match_score
                + 0.75 * b.agency_match_rate
                + 0.45 * b.naics_match_rate
                + 0.80 * pd.partner_depth_score
                - 1.20 * c.incumbent_concentration
                + 1.35 * GREATEST(oh.our_prime_signal, 0.65 * oh.our_sub_signal)
              ))
            )
          )
        ) AS estimated_p_win
      FROM baseline b
      CROSS JOIN concentration c
      CROSS JOIN partner_depth pd
      CROSS JOIN our_history oh
    )
    SELECT JSONB_BUILD_OBJECT(
      'opportunity', JSONB_BUILD_OBJECT(
        'opportunity_id', t.opportunity_id::text,
        'notice_id', t.notice_id,
        'title', t.title,
        'naics_code', t.naics_code,
        'psc_code', t.psc_code,
        'funding_agency_code', t.funding_agency_code,
        'funding_agency_name', t.funding_agency_name,
        'set_aside_code', t.set_aside_code,
        'estimated_value_min', t.estimated_value_min,
        'estimated_value_max', t.estimated_value_max
      ),
      'competing_primes', pj.competing_primes,
      'target_teaming_subs', ts.target_teaming_subs,
      'competitive_baseline', JSONB_BUILD_OBJECT(
        'estimated_p_win', ROUND(pf.estimated_p_win::numeric, 3),
        'model_scope', CASE
          WHEN %(our_entity_id)s::uuid IS NULL THEN 'market_baseline_without_company_specific_capture_history'
          ELSE 'company_adjusted_with_prime_and_subcontract_history'
        END,
        'confidence', CASE
          WHEN pf.historical_match_count >= 50 THEN 'high'
          WHEN pf.historical_match_count >= 15 THEN 'medium'
          ELSE 'low'
        END,
        'historical_match_count', pf.historical_match_count,
        'competing_prime_count', pf.competing_prime_count,
        'total_matched_obligation', pf.total_matched_obligation,
        'score_inputs', JSONB_BUILD_OBJECT(
          'avg_match_score', ROUND(pf.avg_match_score::numeric, 4),
          'top_match_score', ROUND(pf.top_match_score::numeric, 4),
          'avg_semantic_similarity', ROUND(pf.avg_semantic_similarity::numeric, 4),
          'agency_match_rate', ROUND(pf.agency_match_rate::numeric, 4),
          'naics_match_rate', ROUND(pf.naics_match_rate::numeric, 4),
          'partner_depth_score', ROUND(pf.partner_depth_score::numeric, 4),
          'incumbent_concentration', ROUND(pf.incumbent_concentration::numeric, 4),
          'our_prime_signal', ROUND(pf.our_prime_signal::numeric, 4),
          'our_sub_signal', ROUND(pf.our_sub_signal::numeric, 4),
          'our_relevance_signal', ROUND(pf.our_relevance_signal::numeric, 4)
        ),
        'score_weights', JSONB_BUILD_OBJECT(
          'semantic_and_structural_fit', 2.80,
          'agency_match', 0.75,
          'naics_match', 0.45,
          'available_partner_depth', 0.80,
          'incumbent_concentration_penalty', -1.20,
          'company_relevance_signal', 1.35,
          'logistic_intercept', -1.85
        )
      )
    ) AS summary
    FROM target t
    CROSS JOIN prime_json pj
    CROSS JOIN target_teaming_subs ts
    CROSS JOIN pwin_features pf;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

    if not row or row["summary"] is None:
        return {
            "opportunity": target,
            "competing_primes": [],
            "target_teaming_subs": [],
            "competitive_baseline": {
                "estimated_p_win": 0.05,
                "confidence": "low",
                "historical_match_count": 0,
            },
        }

    summary = row["summary"]
    return json.loads(summary) if isinstance(summary, str) else summary


def _fetch_target(conn, target_predicate: str, params: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    sql = f"""
      SELECT
        opportunity_id::text,
        notice_id,
        title,
        naics_code,
        psc_code,
        funding_agency_code,
        funding_agency_name,
        (sow_embedding IS NOT NULL) AS has_sow_embedding
      FROM capture.opportunities
      WHERE {target_predicate}
      LIMIT 1;
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return dict(row) if row else None


def _target_predicate(opportunity_id: str) -> Tuple[str, Dict[str, Any]]:
    try:
        parsed = uuid.UUID(str(opportunity_id))
        return (
            "(opportunity_id = %(opportunity_uuid)s::uuid OR notice_id = %(notice_id)s)",
            {"opportunity_uuid": str(parsed), "notice_id": str(opportunity_id)},
        )
    except ValueError:
        return "notice_id = %(notice_id)s", {"notice_id": str(opportunity_id)}


def _optional_uuid(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UUID when provided.") from exc
