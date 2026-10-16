from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from techdeals import cli
from techdeals.db import migrations
from techdeals.ingestion.contract import RawCapture


class _Result:
    def __init__(self, one=None, all_rows=()):
        self._one = one
        self._all_rows = list(all_rows)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all_rows


class _LegacyConnection:
    def __init__(self):
        self.statements = []
        self.closed = False

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if "to_regclass" in sql:
            return _Result((True, True, True))
        if "SELECT filename" in sql:
            return _Result(all_rows=[("001_postings.sql",), ("002_observations.sql",)])
        if "information_schema.columns" in sql:
            return _Result(all_rows=[("capture_id",), ("source_listing_id",), ("status",)])
        raise AssertionError(f"Unexpected SQL during legacy preflight: {sql}")

    def close(self):
        self.closed = True


class _FailingInsertConnection:
    def __init__(self):
        self.closed = False

    @contextmanager
    def transaction(self):
        yield self

    def execute(self, sql, params=None):
        raise RuntimeError("incompatible postings schema")

    def commit(self):
        pass

    def close(self):
        self.closed = True


def _capture() -> RawCapture:
    return RawCapture(
        source="test",
        source_listing_id="capture-1",
        url="https://example.test/capture-1",
        fetched_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
        checksum="a" * 64,
        raw_payload="<html>raw</html>",
        payload_format="html",
        metadata={"timestamp_provenance": "capture_metadata.fetched_at"},
    )


def test_migrations_fail_closed_before_any_ddl_on_legacy_database(monkeypatch) -> None:
    connection = _LegacyConnection()
    monkeypatch.setattr(migrations.psycopg, "connect", lambda _: connection)
    monkeypatch.setattr(
        migrations, "get_settings", lambda: SimpleNamespace(neon_database_url="local-test")
    )

    with pytest.raises(RuntimeError, match="No schema changes were made") as error:
        migrations.run_migrations()

    assert "do not use `techdeals migrate --reset`" in str(error.value)
    assert connection.closed
    assert not any(
        "CREATE " in statement or "DROP " in statement for statement in connection.statements
    )


def test_available_and_quarantine_queries_match_view_contracts() -> None:
    assert "availability_state = 'available'" in cli.QUERY_SQL["available"]
    assert "v_accounting" in cli.QUERY_SQL["quarantine"]
    assert "quarantine_state = 'quarantined'" in cli.QUERY_SQL["quarantine"]


def test_ingest_returns_failure_on_database_connection_error(monkeypatch, capsys) -> None:
    from techdeals.db import connection
    from techdeals.ingestion import loaders

    monkeypatch.setattr(loaders, "load_all_fixtures", lambda **_: [_capture()])

    def fail_connection():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(connection, "get_connection", fail_connection)
    assert asyncio.run(cli._run_ingest()) == 1
    assert "Database connection failed" in capsys.readouterr().out


def test_ingest_returns_failure_when_any_row_insert_fails(monkeypatch, capsys) -> None:
    from techdeals.db import connection
    from techdeals.ingestion import loaders

    fake_connection = _FailingInsertConnection()
    monkeypatch.setattr(loaders, "load_all_fixtures", lambda **_: [_capture()])
    monkeypatch.setattr(connection, "get_connection", lambda: fake_connection)

    assert asyncio.run(cli._run_ingest()) == 1
    assert fake_connection.closed
    assert "failed: 1" in capsys.readouterr().out


def test_main_exits_nonzero_when_ingest_reports_failure(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys, "argv", ["techdeals", "ingest"])

    def failed_run(coro):
        coro.close()
        return 1

    monkeypatch.setattr(cli.asyncio, "run", failed_run)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1


def test_ingest_explains_zero_eligible_rows_without_connecting(monkeypatch, capsys) -> None:
    from techdeals.db import connection
    from techdeals.ingestion import loaders

    monkeypatch.setattr(loaders, "load_all_fixtures", lambda **_: [])

    def unexpected_connection():
        raise AssertionError("empty intake must not connect")

    monkeypatch.setattr(connection, "get_connection", unexpected_connection)
    assert asyncio.run(cli._run_ingest()) == 0
    output = capsys.readouterr().out
    assert "Eligible captures: 0" in output
    assert "No rows attempted" in output
