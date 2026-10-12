from __future__ import annotations

from collections.abc import AsyncGenerator

import asyncpg
import psycopg

from techdeals.config import get_settings


def get_connection() -> psycopg.Connection:
    """Return a synchronous psycopg connection to Neon."""
    settings = get_settings()
    return psycopg.connect(settings.neon_database_url)


async def get_pool() -> asyncpg.Pool:
    """Return an asyncpg connection pool to Neon."""
    settings = get_settings()
    return await asyncpg.create_pool(settings.neon_database_url)


async def get_async_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Yield an async connection from a short-lived pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
    await pool.close()