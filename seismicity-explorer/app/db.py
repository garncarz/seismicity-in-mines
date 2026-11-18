import json
from pathlib import Path

import psycopg
from flask import current_app


def connect() -> psycopg.Connection:
    return psycopg.connect(**current_app.config["DATABASE"])


def migrate() -> None:
    migration = Path(__file__).parent / "migrations" / "001_initial.sql"
    with connect() as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 1"
        ).fetchone()
        if not applied:
            connection.execute(migration.read_text())
            connection.execute("INSERT INTO schema_migrations (version) VALUES (1)")


def geojson_value(value: str | None) -> dict | None:
    return json.loads(value) if value is not None else None
