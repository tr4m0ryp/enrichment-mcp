"""Read helper over ``prospeo_usage`` -- the credit-metering table (T4).

Used optionally by Task 004 / acceptance to surface a "X credits used this
month" signal that flags free-tier exhaustion early. Read-only: the finders
own the inserts (see ``contacts.finder.log_usage``).

The table name predates the multi-provider chain and is kept for migration
safety; rows now carry a ``provider`` column (schema 005) so Prospeo and
Apollo spend can be read apart.
"""

from __future__ import annotations

from .pool import get_pool


async def prospeo_credit_summary(provider: str | None = None) -> dict:
    """Summarize this calendar month's enrichment credit spend.

    Pass ``provider`` (``"prospeo"`` / ``"apollo"``) to scope the totals to one
    tier; omit it for the combined figure across every provider.

    Returns a plain dict::

        {"credits_used": int, "calls": int, "month": "YYYY-MM",
         "provider": "prospeo" | "apollo" | "all",
         "by_provider": {"prospeo": {"credits_used": int, "calls": int}, ...}}

    ``credits_used`` sums the ``credits`` column and ``calls`` counts the rows
    logged since the start of the current month (``date_trunc('month', now())``,
    server timezone). Both are ``0`` when nothing has been logged yet.
    ``by_provider`` always reports the full per-tier breakdown, so an
    unscoped call still shows which provider is burning the credits.
    """
    where = "used_at >= date_trunc('month', now())"
    args: list[str] = []
    if provider:
        args.append(provider)
        where += " AND provider = $1"

    totals_query = (
        "SELECT COALESCE(SUM(credits), 0) AS credits_used, "
        "COUNT(*) AS calls, "
        "to_char(date_trunc('month', now()), 'YYYY-MM') AS month "
        f"FROM prospeo_usage WHERE {where}"
    )
    breakdown_query = (
        "SELECT provider, COALESCE(SUM(credits), 0) AS credits_used, "
        "COUNT(*) AS calls "
        "FROM prospeo_usage "
        "WHERE used_at >= date_trunc('month', now()) "
        "GROUP BY provider ORDER BY provider"
    )

    pool = await get_pool()
    row = await pool.fetchrow(totals_query, *args)
    rows = await pool.fetch(breakdown_query)
    return {
        "credits_used": int(row["credits_used"]),
        "calls": int(row["calls"]),
        "month": row["month"],
        "provider": provider or "all",
        "by_provider": {
            r["provider"]: {
                "credits_used": int(r["credits_used"]),
                "calls": int(r["calls"]),
            }
            for r in rows
        },
    }
