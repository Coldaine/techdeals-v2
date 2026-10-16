"""CLI entry point for TechDeals v2."""
from __future__ import annotations

import asyncio
import hashlib
import sys

from rich.console import Console
from rich.table import Table

console = Console()


def main() -> None:
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        console.print("[bold]TechDeals v2[/bold] — Hardware marketplace data pipeline")
        console.print()
        console.print("Commands:")
        console.print("  migrate         Run database migrations")
        console.print("  migrate --reset Drop all tables and re-run")
        console.print("  ingest          Run ingestion on fixtures")
        console.print("  extract         Run LLM extraction")
        console.print("  query <name>    Run a predefined query")
        return

    command = sys.argv[1]

    if command == "migrate":
        from techdeals.db.migrations import reset_database, run_migrations
        if "--reset" in sys.argv:
            confirm = input("This will DROP ALL TABLES. Type 'yes' to confirm: ")
            if confirm.lower() == "yes":
                reset_database()
            else:
                console.print("Aborted.")
        else:
            run_migrations()
    elif command == "ingest":
        console.print("[yellow]Ingestion pipeline — loading fixtures into postings.[/yellow]")
        asyncio.run(_run_ingest())
    elif command == "extract":
        console.print("[yellow]Extraction pipeline — running LLM on postings.[/yellow]")
        asyncio.run(_run_extract())
    elif command == "query":
        if len(sys.argv) < 3:
            console.print("Available queries: available, history, lots, quarantine, accounting")
            return
        _run_query(sys.argv[2])
    else:
        console.print(f"[red]Unknown command: {command}[/red]")
        sys.exit(1)


async def _run_ingest() -> None:
    """Ingest fixtures into postings table."""
    from techdeals.db.connection import get_connection
    from techdeals.ingestion.loaders import load_all_fixtures

    console.print("Loading fixtures from corpus...")

    captures = list(load_all_fixtures(max_per_source=10))
    console.print(f"Found {len(captures)} captures from all sources.")

    if not captures:
        console.print("[yellow]No fixtures found.[/yellow]")
        return

    try:
        conn = get_connection()
    except Exception as e:
        console.print(f"[red]Database connection failed: {e}[/red]")
        return

    try:
        inserted = 0
        failed = 0
        for capture in captures:
            try:
                natural_key = f"{capture.source}|{capture.url}|{capture.fetched_at.isoformat()}"
                offer_key = hashlib.sha256(natural_key.encode()).hexdigest()
                conn.execute(
                    """INSERT INTO postings (offer_key, source, url, fetched_at, checksum, payload)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (offer_key) DO NOTHING""",
                    (
                        offer_key,
                        capture.source,
                        capture.url,
                        capture.fetched_at,
                        capture.checksum,
                        capture.raw_payload,
                    ),
                )
                inserted += 1
            except Exception as e:
                console.print(
                    f"[red]Error inserting {capture.source}/{capture.source_listing_id}: {e}[/red]"
                )
                conn.rollback()
                failed += 1
                continue

        conn.commit()
        console.print(
            f"[green]Processed: {inserted} captures; {failed} failed "
            "(duplicates skipped by ON CONFLICT)[/green]"
        )
    finally:
        conn.close()


async def _run_extract() -> None:
    """Report extraction as unavailable until persistence is wired."""
    console.print("[yellow]Extraction is not implemented; no postings were processed.[/yellow]")


def _run_query(name: str) -> None:
    """Run a predefined query."""
    from techdeals.db.connection import get_connection

    queries = {
        "available": "SELECT * FROM v_cheapest_available LIMIT 20",
        "history": "SELECT * FROM v_price_history LIMIT 50",
        "lots": "SELECT * FROM v_lot_worth LIMIT 20",
        "quarantine": "SELECT * FROM v_stale_quarantine LIMIT 20",
        "accounting": "SELECT * FROM v_accounting LIMIT 20",
    }

    if name not in queries:
        console.print(f"[red]Unknown query: {name}. Options: {', '.join(queries.keys())}[/red]")
        return

    try:
        conn = get_connection()
    except Exception as e:
        console.print(f"[red]Database connection failed: {e}[/red]")
        return

    try:
        result = conn.execute(queries[name])
        rows = result.fetchall()
        columns = [desc[0] for desc in result.description]

        if not rows:
            console.print("[yellow]No results.[/yellow]")
            return

        table = Table(title=f"Query: {name}")
        for col in columns:
            table.add_column(col)
        for row in rows:
            table.add_row(*[str(v) for v in row])

        console.print(table)
        console.print(f"\n{len(rows)} rows returned.")
    except Exception as e:
        console.print(f"[red]Query failed: {e}[/red]")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
