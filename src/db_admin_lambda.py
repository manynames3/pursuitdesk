from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Mapping

import psycopg2

from .mock_data_seeder import seed_mock_data


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "migrations"


def lambda_handler(event: Mapping[str, Any], context: Any) -> Dict[str, Any]:
    action = str(event.get("action", "migrate_and_seed"))
    reset = bool(event.get("reset", False))

    if action not in {"migrate", "seed", "migrate_and_seed", "cleanup_sam_mock_seed"}:
        raise ValueError("action must be one of: migrate, seed, migrate_and_seed, cleanup_sam_mock_seed")

    result: Dict[str, Any] = {"action": action}

    if action in {"migrate", "migrate_and_seed"}:
        result["migrations"] = apply_migrations(os.environ["DATABASE_URL"])

    if action in {"seed", "migrate_and_seed"}:
        result["seeded"] = seed_mock_data(os.environ["DATABASE_URL"], reset=reset)

    if action == "cleanup_sam_mock_seed":
        result["cleanup"] = cleanup_sam_mock_seed(os.environ["DATABASE_URL"])

    LOGGER.info("DB admin completed: %s", json.dumps(result, sort_keys=True))
    return result


def apply_migrations(database_url: str) -> list[str]:
    migration_paths = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_paths:
        raise FileNotFoundError(f"No SQL migrations found in {MIGRATIONS_DIR}")

    applied = []
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for path in migration_paths:
                LOGGER.info("Applying migration %s", path.name)
                cur.execute(path.read_text(encoding="utf-8"))
                applied.append(path.name)
    return applied


def cleanup_sam_mock_seed(database_url: str) -> Dict[str, int]:
    """Remove seeded SAM opportunity rows after live SAM.gov ingest is enabled."""
    with psycopg2.connect(database_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH target_opportunities AS (
                  SELECT opportunity_id
                  FROM capture.opportunities
                  WHERE notice_id LIKE 'SAM-2026-%'
                     OR source_payload @> '{"mock_seed": true}'::jsonb
                     OR source_payload->>'source_mode' = 'mock_seed'
                ),
                deleted_opportunities AS (
                  DELETE FROM capture.opportunities o
                  USING target_opportunities t
                  WHERE o.opportunity_id = t.opportunity_id
                  RETURNING o.opportunity_id
                )
                SELECT count(*)::int FROM deleted_opportunities;
                """
            )
            deleted_opportunities = int(cur.fetchone()[0])

            cur.execute(
                """
                DELETE FROM capture.data_freshness
                WHERE source_system = 'SAM.gov'
                  AND source_mode = 'mock_seed'
                RETURNING freshness_id;
                """
            )
            deleted_sam_freshness_rows = cur.rowcount

            cur.execute(
                """
                SELECT count(*)::int
                FROM capture.opportunities
                WHERE source_payload ? 'noticeId'
                   OR source_payload ? 'notice_id'
                   OR ui_link ILIKE '%sam.gov%'
                   OR description_url ILIKE '%sam.gov%';
                """
            )
            live_sam_opportunities = int(cur.fetchone()[0])

            if live_sam_opportunities:
                cur.execute(
                    """
                    INSERT INTO capture.data_freshness (
                      source_system, dataset_name, source_mode, last_successful_sync_at,
                      last_attempted_sync_at, sync_status, record_count, freshness_sla_hours,
                      source_url, notes
                    )
                    VALUES (
                      'SAM.gov',
                      'Opportunities',
                      'live_api',
                      now(),
                      now(),
                      'ready',
                      %(record_count)s,
                      6,
                      'https://api.sam.gov/opportunities/v2/search',
                      'Live SAM.gov Opportunities API records. Seeded SAM demo opportunities have been removed.'
                    )
                    ON CONFLICT (source_system, dataset_name)
                    DO UPDATE SET
                      source_mode = 'live_api',
                      last_successful_sync_at = COALESCE(capture.data_freshness.last_successful_sync_at, EXCLUDED.last_successful_sync_at),
                      last_attempted_sync_at = COALESCE(capture.data_freshness.last_attempted_sync_at, EXCLUDED.last_attempted_sync_at),
                      sync_status = 'ready',
                      record_count = EXCLUDED.record_count,
                      freshness_sla_hours = EXCLUDED.freshness_sla_hours,
                      source_url = EXCLUDED.source_url,
                      notes = EXCLUDED.notes,
                      updated_at = now();
                    """,
                    {"record_count": live_sam_opportunities},
                )

    return {
        "deleted_sam_mock_opportunities": deleted_opportunities,
        "deleted_sam_mock_freshness_rows": deleted_sam_freshness_rows,
        "live_sam_opportunities": live_sam_opportunities,
    }
