from __future__ import annotations

from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "src" / "techdeals" / "schema"


def test_schema_files_exist() -> None:
    expected = [
        "001_postings.sql",
        "002_observations.sql",
        "003_views.sql",
        "004_batch_economics.sql",
    ]
    for name in expected:
        path = SCHEMA_DIR / name
        assert path.exists(), f"Missing schema file: {name}"


def test_schema_files_are_valid_sql() -> None:
    for sql_file in sorted(SCHEMA_DIR.glob("*.sql")):
        content = sql_file.read_text()
        assert len(content.strip()) > 0, f"{sql_file.name} is empty"
