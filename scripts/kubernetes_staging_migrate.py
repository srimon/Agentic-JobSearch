#!/usr/bin/env python3
"""Apply Jobsearch migrations only to the guarded empty Kubernetes staging DB."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "src/db").glob("[0-9][0-9][0-9]_*.sql"))
EXPECTED_VERSIONS = list(range(1, 14))


class StagingMigrationError(RuntimeError):
    pass


def validate_target(dsn: str, enabled: str, app_password: str) -> None:
    parsed = urlparse(dsn)
    if enabled != "1":
        raise StagingMigrationError("staging migration flag is not enabled")
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise StagingMigrationError("staging database scheme is invalid")
    if parsed.hostname != "postgres" or parsed.path != "/jobsearch_staging" or parsed.username != "jobsearch_owner":
        raise StagingMigrationError("refusing a database outside guarded Kubernetes staging")
    if parsed.port not in (None, 5432):
        raise StagingMigrationError("staging database port is invalid")
    if len(app_password) < 24:
        raise StagingMigrationError("staging application password is too short")
    if len(MIGRATIONS) != 13:
        raise StagingMigrationError("expected exactly 13 ordered migrations")


def existing_versions(conn) -> list[int]:
    if not conn.execute("SELECT to_regclass('jobsearch.schema_versions')").fetchone()[0]:
        return []
    return [row[0] for row in conn.execute("SELECT version FROM jobsearch.schema_versions ORDER BY version")]


def apply() -> dict:
    dsn = os.environ.get("JOBSEARCH_DATABASE_URL", "")
    app_password = os.environ.get("JOBSEARCH_STAGING_APP_PASSWORD", "")
    validate_target(dsn, os.environ.get("JOBSEARCH_STAGING_MIGRATIONS", ""), app_password)
    with psycopg.connect(dsn) as conn:
        versions = existing_versions(conn)
        if versions == EXPECTED_VERSIONS:
            return {"database": "jobsearch_staging", "versions": versions, "changed": False}
        if versions:
            raise StagingMigrationError("refusing partially initialized staging schema")
        role = sql.Identifier("jobsearch_app")
        password = sql.Literal(app_password)
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname='jobsearch_app'").fetchone()
        conn.execute(sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(role, password) if exists else sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(role, password))
        for migration in MIGRATIONS:
            conn.execute(migration.read_text(encoding="utf-8"))
        conn.execute("GRANT CONNECT ON DATABASE jobsearch_staging TO jobsearch_app")
        conn.execute("GRANT USAGE ON SCHEMA jobsearch TO jobsearch_app")
        conn.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA jobsearch TO jobsearch_app")
        conn.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA jobsearch TO jobsearch_app")
        versions = existing_versions(conn)
        if versions != EXPECTED_VERSIONS:
            raise StagingMigrationError("staging schema versions are incomplete")
    return {"database": "jobsearch_staging", "versions": versions, "changed": True}


if __name__ == "__main__":
    print(json.dumps(apply(), separators=(",", ":")))
