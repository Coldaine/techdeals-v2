"""Database migration runner for TechDeals v2."""
from __future__ import annotations

from pathlib import Path

import psycopg

from techdeals.config import get_settings

MIGRATION_FILES = [
    "001_postings.sql",
    "002_observations.sql",
    "003_views.sql",
    "004_batch_economics.sql",
]


def run_migrations() -> None:
    """Run all SQL migration files in schema/ in order."""
    settings = get_settings()
    schema_dir = Path(__file__).parent.parent / "schema"
    if not schema_dir.exists():
        raise FileNotFoundError(f"Schema directory not found: {schema_dir}")

    conn = psycopg.connect(settings.neon_database_url)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.commit()

        for filename in MIGRATION_FILES:
            filepath = schema_dir / filename
            if not filepath.exists():
                print(f"WARNING: Migration file not found: {filename}")
                continue

            result = conn.execute(
                "SELECT 1 FROM _schema_migrations WHERE filename = %s",
                (filename,)
            ).fetchone()

            if result:
                print(f"Already applied: {filename}")
                continue

            sql = filepath.read_text()
            try:
                conn.execute(sql)
                conn.commit()
            except Exception as e:
                if "timescaledb" in str(e).lower():
                    conn.rollback()
                    filtered_sql = _filter_timescaledb(sql)
                    conn.execute(filtered_sql)
                    conn.commit()
                    print(f"Applied without TimescaleDB: {filename}")
                else:
                    conn.rollback()
                    raise

            conn.execute(
                "INSERT INTO _schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING",
                (filename,)
            )
            conn.commit()
            print(f"Applied: {filename}")

        print("\nAll migrations complete.")
    finally:
        conn.close()


def _filter_timescaledb(sql: str) -> str:
    """Remove TimescaleDB-specific SQL."""
    lines = sql.split("\n")
    filtered = []
    skip_block = False
    for line in lines:
        stripped = line.strip().lower()
        if "create extension" in stripped and "timescaledb" in stripped:
            continue
        if stripped.startswith("do $$") and not skip_block:
            skip_block = True
            continue
        if skip_block:
            if "$$" in stripped and not stripped.startswith("do $$"):
                skip_block = False
            continue
        if "create_hypertable" in stripped:
            continue
        filtered.append(line)
    return "\n".join(filtered)


def reset_database() -> None:
    """Drop all tables and re-run migrations."""
    settings = get_settings()
    conn = psycopg.connect(settings.neon_database_url)
    try:
        conn.execute("""
            DO $$ DECLARE r RECORD;
            BEGIN
                FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
                END LOOP;
            END $$;
        """)
        conn.commit()
        print("Dropped all tables.")
    finally:
        conn.close()
    run_migrations()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        confirm = input("This will DROP ALL TABLES. Type 'yes' to confirm: ")
        if confirm.lower() == "yes":
            reset_database()
        else:
            print("Aborted.")
    else:
        run_migrations()
