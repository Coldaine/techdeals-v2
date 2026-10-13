"""Run a multi-statement SQL script over a psycopg connection.

psycopg3 returns only the last result of a multi-statement simple query, which is
useless for an acceptance file full of checks. This splits the script into
statements and captures every result set. Naive but correct for our SQL: no
dollar-quoted bodies and no semicolons inside string literals.
"""
from __future__ import annotations

import psycopg


def split_statements(sql: str) -> list[str]:
    lines: list[str] = []
    for raw in sql.splitlines():
        idx = raw.find("--")
        lines.append(raw if idx == -1 else raw[:idx])
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


def run_script(
    conn: psycopg.Connection, sql: str
) -> list[tuple[str, list[str], list[tuple]]]:
    """Execute each statement, returning (statement, columns, rows)."""
    results: list[tuple[str, list[str], list[tuple]]] = []
    for statement in split_statements(sql):
        cur = conn.execute(statement)
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            results.append((statement, columns, cur.fetchall()))
        else:
            results.append((statement, [], []))
    conn.commit()
    return results
