"""CLI entry point for TechDeals v2.

    techdeals migrate [--reset]        apply schema migrations to NEON_DATABASE_URL
    techdeals ingest                   load the fixture corpus into raw_captures
    techdeals extract [--provider ..]  batch-extract + persist postings/lines/observations
    techdeals pipeline                 ingest + extract in one go
    techdeals query <name>             run a read view (available|history|lots|quarantine)
    techdeals acceptance               run tests/acceptance_queries.sql and print results
    techdeals status                   one-line pipeline health summary
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="techdeals", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    p_migrate = sub.add_parser("migrate", help="run schema migrations")
    p_migrate.add_argument("--reset", action="store_true", help="drop all tables first")
    p_migrate.add_argument("--yes", action="store_true", help="skip the reset confirmation")

    p_ingest = sub.add_parser("ingest", help="load fixtures into raw_captures")
    p_ingest.add_argument("--max-per-source", type=int, default=None)

    p_extract = sub.add_parser("extract", help="run batched extraction + persistence")
    p_extract.add_argument("--provider", choices=["llm", "offline"], default="llm")
    p_extract.add_argument("--batch-size", type=int, default=None)
    p_extract.add_argument("--parser-version", default="v1")
    p_extract.add_argument("--prompt-version", default="v1")
    p_extract.add_argument("--model", default=None)
    p_extract.add_argument("--max-per-source", type=int, default=None)

    p_pipeline = sub.add_parser("pipeline", help="ingest then extract")
    p_pipeline.add_argument("--provider", choices=["llm", "offline"], default="offline")
    p_pipeline.add_argument("--batch-size", type=int, default=None)
    p_pipeline.add_argument("--parser-version", default="v1")
    p_pipeline.add_argument("--model", default=None)
    p_pipeline.add_argument("--max-per-source", type=int, default=None)

    p_query = sub.add_parser("query", help="run a read view")
    p_query.add_argument("name", nargs="?", default=None)

    sub.add_parser("acceptance", help="run the acceptance query suite")
    sub.add_parser("status", help="pipeline health summary")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if not args.command:
        parser.print_help()
        return

    if args.command == "migrate":
        from techdeals.db.migrations import reset_database, run_migrations

        if args.reset:
            confirmed = args.yes or (
                input("This will DROP ALL TABLES. Type 'yes' to confirm: ").lower() == "yes"
            )
            if confirmed:
                reset_database()
            else:
                console.print("Aborted.")
        else:
            run_migrations()
    elif args.command == "ingest":
        asyncio.run(_run_ingest(args.max_per_source))
    elif args.command == "extract":
        asyncio.run(_run_extract(args, provider=args.provider))
    elif args.command == "pipeline":
        asyncio.run(_run_pipeline(args))
    elif args.command == "query":
        _run_query(args.name)
    elif args.command == "acceptance":
        _run_acceptance()
    elif args.command == "status":
        _run_status()


def _load_captures(max_per_source: int | None):
    from techdeals.ingestion.loaders import fixtures_dir, load_all_fixtures

    console.print(f"Fixtures dir: [cyan]{fixtures_dir()}[/cyan]")
    return list(load_all_fixtures(max_per_source=max_per_source))


async def _run_ingest(max_per_source: int | None) -> None:
    from techdeals.db.connection import get_connection
    from techdeals.pipeline import ingest

    captures = _load_captures(max_per_source)
    console.print(f"Found [bold]{len(captures)}[/bold] captures in the corpus.")
    if not captures:
        console.print("[yellow]No fixtures found.[/yellow]")
        return
    conn = get_connection()
    try:
        summary = ingest(conn, captures)
        console.print(
            f"[green]raw_captures now holds {summary.captures_in_db} rows "
            f"({summary.captures_written} loaded this run; duplicates skipped).[/green]"
        )
    finally:
        conn.close()


async def _run_extract(args, *, provider: str) -> None:
    from techdeals.config import get_settings
    from techdeals.db.connection import get_connection
    from techdeals.pipeline import extract

    captures = _load_captures(args.max_per_source)
    if not captures:
        console.print("[yellow]No fixtures found.[/yellow]")
        return

    batch_size = args.batch_size or get_settings().llm_batch_size
    conn = get_connection()
    try:
        summary = await extract(
            conn,
            captures,
            parser_version=args.parser_version,
            batch_size=batch_size,
            provider=provider,
            model=args.model,
        )
    finally:
        conn.close()

    console.print(
        f"[green]Extraction ({provider}) done:[/green] {summary.listings} listings, "
        f"{summary.postings} postings written, {summary.quarantined} quarantined, "
        f"{summary.skipped_replay} replay-skipped, {summary.batches} batches "
        f"(batch_size={batch_size}, single-listing calls={summary.single_listing_calls})."
    )


async def _run_pipeline(args) -> None:
    await _run_ingest(args.max_per_source)
    await _run_extract(args, provider=args.provider)
    _run_status()


def _run_query(name: str | None) -> None:
    from techdeals.db.connection import get_connection

    queries = {
        "available": "SELECT * FROM v_available_now ORDER BY price_cents LIMIT 20",
        "history": "SELECT * FROM v_price_history LIMIT 50",
        "lots": "SELECT * FROM v_lot_decomposition LIMIT 20",
        "quarantine": "SELECT * FROM v_quarantine LIMIT 20",
        "batches": "SELECT * FROM v_batch_economics",
    }
    if not name:
        console.print("Available queries: " + ", ".join(queries))
        return
    if name not in queries:
        console.print(f"[red]Unknown query: {name}[/red]")
        return

    conn = get_connection()
    try:
        result = conn.execute(queries[name])
        _print_result(result.description, result.fetchall(), title=f"Query: {name}")
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        console.print(f"[red]Query failed: {exc}[/red]")
    finally:
        conn.close()


def _run_acceptance() -> None:
    from techdeals.db.connection import get_connection
    from techdeals.db.runner import run_script

    sql_path = Path(__file__).resolve().parents[2] / "tests" / "acceptance_queries.sql"
    if not sql_path.exists():
        console.print(f"[red]Acceptance file not found: {sql_path}[/red]")
        return

    conn = get_connection()
    try:
        for statement, columns, rows in run_script(conn, sql_path.read_text()):
            label = " ".join(statement.split())[:72]
            if not columns:
                console.print(f"[dim]{label} -> ok[/dim]")
                continue
            _print_result(columns, rows, title=label)
    finally:
        conn.close()



_STATUS_SQL = """
SELECT
  (SELECT count(*) FROM raw_captures) AS captures,
  (SELECT count(*) FROM postings WHERE status = 'extracted') AS extracted,
  (SELECT count(*) FROM postings WHERE status = 'quarantined') AS quarantined,
  (SELECT count(*) FROM postings WHERE status = 'failed') AS failed,
  (SELECT count(*) FROM lines) AS lines,
  (SELECT count(*) FROM sale_groups) AS sale_groups,
  (SELECT count(*) FROM observations WHERE superseded_by IS NULL) AS observations,
  (SELECT count(*) FROM resolutions WHERE superseded_by IS NULL) AS resolutions,
  (SELECT COALESCE(round(avg(listing_count), 2), 0) FROM extraction_batches) AS avg_batch
"""


def _run_status() -> None:
    from techdeals.db.connection import get_connection

    conn = get_connection()
    try:
        row = conn.execute(_STATUS_SQL).fetchone()
        names = ["captures", "extracted", "quarantined", "failed", "lines",
                 "sale_groups", "observations", "resolutions", "avg_batch"]
        table = Table(title="Pipeline status")
        table.add_column("metric")
        table.add_column("value", justify="right")
        for key, value in zip(names, row):
            table.add_row(key, str(value))
        console.print(table)
    finally:
        conn.close()


def _print_result(description, rows, *, title: str, max_rows: int = 40) -> None:
    """Plain-text grid: rich shrinks/wraps columns, which mangles wide results."""
    columns = [str(desc[0]) for desc in description]
    if not rows:
        console.print(f"[yellow]{title}: no rows[/yellow]")
        return
    shown = rows[:max_rows]
    cells = [[_cell(v) for v in row] for row in shown]
    widths = [
        max(len(columns[i]), *(len(row[i]) for row in cells)) if cells else len(columns[i])
        for i in range(len(columns))
    ]
    console.print(f"[bold]{title}[/bold]")
    console.print("  ".join(columns[i].ljust(widths[i]) for i in range(len(columns))))
    console.print("  ".join("-" * widths[i] for i in range(len(columns))))
    for row in cells:
        console.print("  ".join(row[i].ljust(widths[i]) for i in range(len(columns))))
    suffix = f" (showing first {max_rows})" if len(rows) > max_rows else ""
    console.print(f"[dim]{len(rows)} row(s){suffix}[/dim]")


def _cell(value, limit: int = 34) -> str:
    text = "" if value is None else str(value).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


if __name__ == "__main__":
    main()
