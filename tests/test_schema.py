from __future__ import annotations

from pathlib import Path

ROOT_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
PKG_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "src" / "techdeals" / "schema"


def test_schema_files_exist() -> None:
    expected = ["000_functions.sql", "010_tables.sql", "020_views.sql"]
    for schema_dir in [ROOT_SCHEMA_DIR, PKG_SCHEMA_DIR]:
        for name in expected:
            path = schema_dir / name
            assert path.exists(), f"Missing schema file: {path}"


def test_schema_files_are_valid_sql() -> None:
    for schema_dir in [ROOT_SCHEMA_DIR, PKG_SCHEMA_DIR]:
        for sql_file in sorted(schema_dir.glob("*.sql")):
            if sql_file.name == "smoke_test.sql":
                continue
            content = sql_file.read_text()
            assert len(content.strip()) > 0, f"{sql_file} is empty"
