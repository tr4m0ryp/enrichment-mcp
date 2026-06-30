"""Async data-access layer for the lean ``leads`` table (T7 / F4).

Plain async functions behind the five state/CRM tools (Task 004 wraps these as
``@mcp.tool``). Every query is parametrized ($1, $2, ...) -- user values are
never string-interpolated -- and every function acquires the shared asyncpg
pool from :func:`db.pool.get_pool` and returns plain ``dict`` rows.
"""

from __future__ import annotations

from .pool import get_pool

# Canonical status progression: qualified -> contact_resolved -> contacted ->
# replied -> closed/rejected. Ordering is used both to validate updates and to
# avoid regressing an advanced lead during an upsert.
LEAD_STATUSES: tuple[str, ...] = (
    "qualified",
    "contact_resolved",
    "contacted",
    "replied",
    "closed",
    "rejected",
)

# Columns the caller may supply to add_qualified_lead. ``status`` is derived,
# never accepted directly; ``domain``/``company_name`` are required.
_LEAD_COLUMNS: tuple[str, ...] = (
    "domain",
    "company_name",
    "summary",
    "location",
    "webshop_platform",
    "bounty_fit_score",
    "why",
    "contact_name",
    "contact_role",
    "contact_email",
    "contact_linkedin",
    "contact_email_verified",
)

_CONTACT_FIELDS: tuple[str, ...] = (
    "contact_name",
    "contact_role",
    "contact_email",
    "contact_linkedin",
)

# SQL array literal of the status order, reused in the upsert's no-regress CASE.
_STATUS_ORDER_SQL = (
    "ARRAY['qualified','contact_resolved','contacted',"
    "'replied','closed','rejected']"
)


async def add_qualified_lead(lead: dict) -> dict:
    """Insert or update a lead, keyed on ``domain`` (UPSERT).

    Accepts the lean fields plus optional contact fields. Status is *derived*,
    not taken from the caller: if any contact field is present the lead seeds
    at ``contact_resolved``, otherwise ``qualified``.

    On conflict only the columns actually supplied are overwritten, so a later
    partial re-qualify never blanks existing data. The status is advanced but
    never regressed: an already-``contacted``/``replied``/``closed`` lead keeps
    its status even when re-added with only the lean fields.
    """
    domain = (lead.get("domain") or "").strip()
    if not domain:
        raise ValueError("add_qualified_lead requires a non-empty 'domain'")
    company_name = lead.get("company_name")
    if not company_name:
        raise ValueError("add_qualified_lead requires 'company_name'")

    has_contact = any(lead.get(f) for f in _CONTACT_FIELDS)
    derived_status = "contact_resolved" if has_contact else "qualified"

    # Build the column/value lists from supplied keys (domain + company_name
    # always; status always, with its computed value).
    data: dict = {"domain": domain, "company_name": company_name}
    for col in _LEAD_COLUMNS:
        if col in ("domain", "company_name"):
            continue
        if col in lead:
            data[col] = lead[col]
    data["status"] = derived_status

    columns = list(data.keys())
    placeholders = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
    col_sql = ", ".join(columns)

    # ON CONFLICT: overwrite every supplied column except domain (the key) and
    # status (handled by the no-regress CASE below).
    set_parts = [
        f"{c} = EXCLUDED.{c}"
        for c in columns
        if c not in ("domain", "status")
    ]
    set_parts.append(
        "status = CASE "
        f"WHEN array_position({_STATUS_ORDER_SQL}, leads.status) "
        f">= array_position({_STATUS_ORDER_SQL}, EXCLUDED.status) "
        "THEN leads.status ELSE EXCLUDED.status END"
    )
    set_parts.append("updated_at = now()")

    query = (
        f"INSERT INTO leads ({col_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT (domain) DO UPDATE SET {', '.join(set_parts)} "
        "RETURNING *"
    )

    pool = await get_pool()
    row = await pool.fetchrow(query, *data.values())
    return dict(row)


async def list_leads(
    status: str | None = None,
    min_score: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return leads, newest/highest-scoring first.

    Optionally filter by exact ``status`` and/or a ``bounty_fit_score`` floor.
    Ordered by ``bounty_fit_score DESC`` (NULLs last) then ``created_at DESC``.
    """
    clauses: list[str] = []
    args: list = []
    if status is not None:
        args.append(status)
        clauses.append(f"status = ${len(args)}")
    if min_score is not None:
        args.append(min_score)
        clauses.append(f"bounty_fit_score >= ${len(args)}")

    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    args.append(limit)
    query = (
        f"SELECT * FROM leads {where}"
        "ORDER BY bounty_fit_score DESC NULLS LAST, created_at DESC "
        f"LIMIT ${len(args)}"
    )

    pool = await get_pool()
    rows = await pool.fetch(query, *args)
    return [dict(r) for r in rows]


async def get_lead(domain: str) -> dict | None:
    """Fetch a single lead by domain, or ``None`` if absent."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM leads WHERE domain = $1", domain)
    return dict(row) if row else None


async def update_lead_status(
    domain: str,
    status: str,
    note: str | None = None,
) -> dict:
    """Move a lead to ``status``; optionally append ``note`` to ``why``.

    ``status`` is validated against the enum and a clear :class:`ValueError`
    is raised on a bad value. A supplied ``note`` is appended to the existing
    ``why`` (separated by `` | ``) so the rationale keeps a short audit trail;
    pass ``None`` to leave ``why`` untouched. Raises ``ValueError`` when the
    domain does not exist. ``updated_at`` is refreshed by the table trigger.
    """
    if status not in LEAD_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; expected one of {LEAD_STATUSES}"
        )

    query = (
        "UPDATE leads SET status = $2, "
        "why = CASE "
        "WHEN $3::text IS NULL THEN why "
        "WHEN why IS NULL OR why = '' THEN $3 "
        "ELSE why || ' | ' || $3 END "
        "WHERE domain = $1 RETURNING *"
    )

    pool = await get_pool()
    row = await pool.fetchrow(query, domain, status, note)
    if row is None:
        raise ValueError(f"no lead with domain {domain!r}")
    return dict(row)


async def get_uncontacted(limit: int = 20) -> list[dict]:
    """Leads not yet contacted -- status ``qualified`` or ``contact_resolved``.

    Highest ``bounty_fit_score`` first (NULLs last), then newest. This is the
    work queue the session pulls from to drive contact resolution / outreach.
    """
    query = (
        "SELECT * FROM leads "
        "WHERE status IN ('qualified', 'contact_resolved') "
        "ORDER BY bounty_fit_score DESC NULLS LAST, created_at DESC "
        "LIMIT $1"
    )
    pool = await get_pool()
    rows = await pool.fetch(query, limit)
    return [dict(r) for r in rows]
