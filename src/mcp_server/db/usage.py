"""Read helper over ``prospeo_usage`` -- the credit-metering table (T4).

Used optionally by Task 004 / acceptance to surface a "X credits used this
month" signal that flags Prospeo free-tier exhaustion early. Read-only: the
finder's salvaged Prospeo path owns the inserts.
"""

from __future__ import annotations

from .pool import get_pool


async def prospeo_credit_summary() -> dict:
    """Summarize this calendar month's Prospeo credit spend.

    Returns a plain dict::

        {"credits_used": int, "calls": int, "month": "YYYY-MM"}

    ``credits_used`` sums the ``credits`` column and ``calls`` counts the rows
    logged since the start of the current month (``date_trunc('month', now())``,
    server timezone). Both are ``0`` when nothing has been logged yet.
    """
    query = (
        "SELECT COALESCE(SUM(credits), 0) AS credits_used, "
        "COUNT(*) AS calls, "
        "to_char(date_trunc('month', now()), 'YYYY-MM') AS month "
        "FROM prospeo_usage "
        "WHERE used_at >= date_trunc('month', now())"
    )
    pool = await get_pool()
    row = await pool.fetchrow(query)
    return {
        "credits_used": int(row["credits_used"]),
        "calls": int(row["calls"]),
        "month": row["month"],
    }
