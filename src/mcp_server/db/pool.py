"""Async Postgres connection pool for the lead store.

Lifted from clay's ``src/api_keys/supabase_client.py``: just the asyncpg pool
against the Supabase direct / Session-pooler endpoint, keyed off the
``SUPABASE_DB_URL`` DSN (read via ``config``). The supabase-py Auth/Storage
client and the ``SUPABASE_URL`` / ``SERVICE_ROLE_KEY`` vars are intentionally
dropped -- this server only needs the data-plane pool.
"""

from __future__ import annotations

from typing import Optional

import asyncpg

from ..config import get_config

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Return the shared asyncpg pool, creating it on first call.

    Builds from ``config.supabase_db_url`` (the full Postgres DSN). ``max_size``
    stays small (2) to keep the per-process connection count well under
    Supabase's session-pooler client cap.
    """
    global _pool
    if _pool is None:
        dsn = get_config().supabase_db_url
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    return _pool


async def close_pool() -> None:
    """Close the shared pool if it has been created.

    Safe to call multiple times or before the pool is initialised.
    """
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
