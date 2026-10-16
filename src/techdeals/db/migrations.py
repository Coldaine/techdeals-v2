"""Database migration runner for TechDeals v2."""
from __future__ import annotations

from pathlib import Path

import psycopg

from techdeals.config import get_settings

MIGRATION_FILES = [
    "000_functions.sql",
    "010_tables.sql",
    "020_views.sql",
]

LEGACY_MIGRATIONS = {"001_postings.sql", "002_observations.sql", "003_views.sql"}
LEGACY_POSTING_COLUMNS = {"capture_id", "source_listing_id", "status"}


def _legacy_database_state(conn: psycopg.Connection) -> tuple[set[str], set[str], bool]:
    """Inspect migration metadata and table shape without changing the database."""
    registry_exists, raw_captures_exists, postings_exists = conn.execute(
        """SELECT to_regclass('public._schema_migrations') IS NOT NULL,
                  to_regclass('public.raw_captures') IS NOT NULL,
                  to_regclass('public.postings') IS NOT NULL"""
    ).fetchone()

    applied: set[str] = set()
    if registry_exists:
        applied = {
            row[0]
            for row in conn.execute("SELECT filename FROM public._schema_migrations").fetchall()
        }

    posting_columns: set[str] = set()
    if postings_exists:
        posting_columns = {
            row[0]
            for row in conn.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'postings'"""
            ).fetchall()
        }
    return applied, posting_columns, raw_captures_exists


def _raise_on_legacy_database(conn: psycopg.Connection) -> None:
    applied, posting_columns, has_raw_captures = _legacy_database_state(conn)
    legacy_registry = applied & LEGACY_MIGRATIONS
    legacy_postings = bool(posting_columns & LEGACY_POSTING_COLUMNS)
    if not (legacy_registry or legacy_postings or has_raw_captures):
        return

    details = []
    if legacy_registry:
        details.append(f"legacy migrations recorded: {', '.join(sorted(legacy_registry))}")
    if legacy_postings or has_raw_captures:
        details.append("legacy raw_captures/postings tables detected")
    raise RuntimeError(
        "Refusing to apply the v2 schema over a legacy TechDeals database ("
        + "; ".join(details)
        + "). No schema changes were made. Preserve the existing database and its data; "
        "do not use `techdeals migrate --reset`. For v2, provision a separate empty scratch "
        "database. In-place legacy data conversion is not implemented; export/transform it "
        "only under a separately reviewed migration plan."
    )


def get_schema_dir() -> Path:
    """Resolve schema directory location (root schema/ preferred, fallback to package schema)."""
    # Root schema directory
    root_schema = Path(__file__).resolve().parents[3] / "schema"
    if root_schema.exists() and (root_schema / "000_functions.sql").exists():
        return root_schema

    # Package schema directory
    pkg_schema = Path(__file__).resolve().parent.parent / "schema"
    if pkg_schema.exists():
        return pkg_schema

    raise FileNotFoundError("Schema directory not found")


def run_migrations() -> None:
    """Run all SQL migration files in schema/ in order."""
    settings = get_settings()
    schema_dir = get_schema_dir()

    conn = psycopg.connect(settings.neon_database_url)
    try:
        _raise_on_legacy_database(conn)
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
