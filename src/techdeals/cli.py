"""CLI entry point for TechDeals v2."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime

from rich.console import Console
from rich.table import Table

from techdeals.ingestion.contract import RawCapture

console = Console()

QUERY_SQL = {
    "available": (
        "SELECT * FROM v_cheapest_available "
        "WHERE availability_state = 'available' ORDER BY unit_price LIMIT 20"
    ),
    "history": "SELECT * FROM v_price_history LIMIT 50",
    "lots": "SELECT * FROM v_lot_worth LIMIT 20",
    "quarantine": (
        "SELECT * FROM v_accounting WHERE quarantine_state = 'quarantined' "
        "OR COALESCE(quarantined_line_count, 0) > 0 LIMIT 20"
    ),
    "accounting": "SELECT * FROM v_accounting LIMIT 20",
}


def _posting_offer_key(
    source: str, url: str, fetched_at: datetime, source_listing_id: str
) -> str:
    """Hash the posting key, using the source ID when no source URL exists."""
    natural_key = f"{source}|{url}|{fetched_at.isoformat()}"
    if not url:
        natural_key += f"|missing-url|{source_listing_id}"
    return hashlib.sha256(natural_key.encode()).hexdigest()


def _stored_payload(capture: RawCapture) -> str:
    """Encode raw evidence and its format/provenance inside the JSONB column."""
    return json.dumps(
        {
            "payload_format": capture.payload_format,
            "raw_payload": capture.raw_payload,
            "metadata": {**capture.metadata, "source_listing_id": capture.source_listing_id},
        }
    )


def main() -> None:
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        console.print("[bold]TechDeals v2[/bold] — Hardware marketplace data pipeline")
        console.print()
        console.print("Commands:")
        console.print("  migrate         Run database migrations")
        console.print("  migrate --reset Drop all tables and re-run")
        console.print("  ingest          Run ingestion on fixtures")
        console.print("  extract         Extract postings (currently unavailable; exits nonzero)")
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
        if asyncio.run(_run_ingest()) != 0:
            sys.exit(1)
    elif command == "extract":
        console.print(
            "[red]Extraction persistence is not implemented; no postings were processed.[/red]"
        )
        sys.exit(2)
    elif command == "query":
        if len(sys.argv) < 3:
            console.print("Available queries: available, history, lots, quarantine, accounting")
            return
        _run_query(sys.argv[2])
    else:
        console.print(f"[red]Unknown command: {command}[/red]")
        sys.exit(1)


async def _run_ingest() -> int:
    """Ingest fixtures into postings table."""
    from techdeals.db.connection import get_connection
    from techdeals.ingestion.loaders import load_all_fixtures

    console.print("Loading fixtures from corpus...")

    captures = list(load_all_fixtures(max_per_source=10))
    console.print(f"Eligible captures: {len(captures)}.")

    if not captures:
        console.print(
            "[yellow]No rows attempted: no fixture has explicit "
            "capture_metadata.fetched_at.[/yellow]"
        )
        return 0

    try:
        conn = get_connection()
    except Exception as e:
        console.print(f"[red]Database connection failed: {e}[/red]")
        return 1

    try:
        inserted = 0
        duplicates = 0
        failed = 0
        for capture in captures:
            try:
                offer_key = _posting_offer_key(
                    capture.source, capture.url, capture.fetched_at, capture.source_listing_id
                )
                # A savepoint keeps a bad row from rolling back earlier inserts.
                with conn.transaction():
                    result = conn.execute(
                        """INSERT INTO postings (
                        offer_key, source, url, fetched_at, checksum, payload)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT (offer_key) DO NOTHING""",
                        (
                            offer_key,
                            capture.source,
                            capture.url,
                            capture.fetched_at,
                            capture.checksum,
                            _stored_payload(capture),
                        ),
                    )
                if result.rowcount == 1:
                    inserted += 1
                else:
                    duplicates += 1
            except Exception as e:
                console.print(
                    f"[red]Error inserting {capture.source}/{capture.source_listing_id}: {e}[/red]"
                )
                failed += 1
                continue

        conn.commit()
        summary = (
            f"Input: {len(captures)}; inserted: {inserted}; "
            f"duplicates: {duplicates}; failed: {failed}"
        )
        console.print(f"[{'red' if failed else 'green'}]{summary}[/]")
        return 1 if failed else 0
    finally:
        conn.close()


def _run_query(name: str) -> None:
    """Run a predefined query."""
    from techdeals.db.connection import get_connection

    if name not in QUERY_SQL:
        console.print(f"[red]Unknown query: {name}. Options: {', '.join(QUERY_SQL.keys())}[/red]")
        return

    try:
        conn = get_connection()
    except Exception as e:
        console.print(f"[red]Database connection failed: {e}[/red]")
        return

    try:
        result = conn.execute(QUERY_SQL[name])
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
