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

    if action not in {"migrate", "seed", "migrate_and_seed"}:
        raise ValueError("action must be one of: migrate, seed, migrate_and_seed")

    result: Dict[str, Any] = {"action": action}

    if action in {"migrate", "migrate_and_seed"}:
        result["migrations"] = apply_migrations(os.environ["DATABASE_URL"])

    if action in {"seed", "migrate_and_seed"}:
        result["seeded"] = seed_mock_data(os.environ["DATABASE_URL"], reset=reset)

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
