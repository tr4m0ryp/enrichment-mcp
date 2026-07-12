"""Async data-access layer for the lean ``leads`` table (T7 / F4).

Plain async functions behind the five state/CRM tools (Task 004 wraps these as
``@mcp.tool``). Every query is parametrized ($1, $2, ...) -- user values are
never string-interpolated -- and every function acquires the shared asyncpg
pool from :func:`db.pool.get_pool` and returns plain ``dict`` rows.

**Project partition.** The ``leads`` table is shared by more than one outreach
pipeline (the pentest / bug-bounty pipeline and the Avelero licensing pipeline).
Every row carries a ``project`` tag and every function here is scoped to a single
project: reads filter ``WHERE project = $project``, writes stamp it, and the
upsert refuses to cross project boundaries. Callers pass ``project`` (the tool
layer defaults it to the instance's ``LEADS_PROJECT`` env, "pentest").
"""

from __future__ import annotations

from .pool import get_pool

# Canonical status progression: qualified -> contact_resolved -> contacted ->
# replied -> agreement_sent -> signed -> authorized_ready -> running ->
# reported -> closed/rejected. The five engagement states (agreement_sent
# .. reported) carry a lead through signature-verification, the shor-run, and
# reporting. Ordering is used both to validate updates and to avoid regressing
# an advanced lead during an upsert, so it must stay in sync with the
# ``leads_status_check`` DB constraint (schema/002_engagement_statuses.sql).
LEAD_STATUSES: tuple[str, ...] = (
    "qualified",
    "contact_resolved",
    "contacted",
    "replied",
    "agreement_sent",
    "signed",
    "authorized_ready",
    "running",
    "reported",
    "closed",
    "rejected",
)

# The outreach pipelines that share this store. Must stay in sync with the
# ``leads_project_check`` DB constraint (schema/004_project_partition.sql).
VALID_PROJECTS: tuple[str, ...] = ("pentest", "avelero")

# Columns the caller may supply to add_qualified_lead. ``status`` and ``project``
# are handled explicitly (never taken from the lean lead dict);
# ``domain``/``company_name`` are required.
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
    # contactform-nudge cache (schema/003_nudge_channels.sql). contactform_checked
    # is the permanent skip-forever gate -- callers must only pass it true on a
    # genuinely terminal outcome, never on a transient connector error.
    "contactform_checked",
    "contactform_status",
    "contactform_url",
    "contactform_ts",
    # whatsapp-nudge cache (schema/003_nudge_channels.sql).
    "whatsapp_checked",
    "whatsapp_number",
    "whatsapp_nudge_sent",
    "whatsapp_nudge_ts",
)

_CONTACT_FIELDS: tuple[str, ...] = (
    "contact_name",
    "contact_role",
    "contact_email",
    "contact_linkedin",
)

# Compact column set the LIST tools return. `SELECT *` on the full ~24-column row
# (with the long `summary` and the ever-growing `why` audit-trail) overflows the
# MCP output token cap at realistic list sizes, so list results are projected to
# the scan fields only and `summary` is truncated. `get_lead` still returns the
# full row (SELECT *) -- single-record detail belongs there.
_LIST_SELECT = (
    "domain, company_name, status, bounty_fit_score, location, "
    "contact_name, contact_email, contact_email_verified, "
    "left(summary, 140) AS summary, created_at, updated_at"
)

# SQL array literal of the status order, reused in the upsert's no-regress CASE.
# Derived from LEAD_STATUSES so the two can never drift: a status missing here
# would make array_position() return NULL and silently regress an advanced lead
# back to its EXCLUDED (re-add) status.
_STATUS_ORDER_SQL = "ARRAY[" + ",".join(f"'{s}'" for s in LEAD_STATUSES) + "]"


def _check_project(project: str) -> str:
    """Validate ``project`` against the allow-list, raising ``ValueError``."""
    if project not in VALID_PROJECTS:
        raise ValueError(
            f"invalid project {project!r}; expected one of {VALID_PROJECTS}"
        )
    return project


async def add_qualified_lead(lead: dict, project: str = "pentest") -> dict:
    """Insert or update a lead, keyed on ``domain`` within ``project`` (UPSERT).

    Accepts the lean fields plus optional contact fields. Status is *derived*,
    not taken from the caller: if any contact field is present the lead seeds
    at ``contact_resolved``, otherwise ``qualified``. The row is stamped with
    ``project``.

    On conflict only the columns actually supplied are overwritten, so a later
    partial re-qualify never blanks existing data. The status is advanced but
    never regressed. The upsert is **project-scoped**: a domain already owned by
    a different project is never clobbered -- the call raises ``ValueError``
    instead, so the two pipelines' leads can never overwrite each other.
    """
    _check_project(project)
    domain = (lead.get("domain") or "").strip()
    if not domain:
        raise ValueError("add_qualified_lead requires a non-empty 'domain'")
    company_name = lead.get("company_name")
    if not company_name:
        raise ValueError("add_qualified_lead requires 'company_name'")

    has_contact = any(lead.get(f) for f in _CONTACT_FIELDS)
    derived_status = "contact_resolved" if has_contact else "qualified"

    # Build the column/value lists from supplied keys (domain + company_name
    # always; status + project always, with their computed/scoped values).
    data: dict = {"domain": domain, "company_name": company_name}
    for col in _LEAD_COLUMNS:
        if col in ("domain", "company_name"):
            continue
        if col in lead:
            data[col] = lead[col]
    data["status"] = derived_status
    data["project"] = project

    columns = list(data.keys())
    placeholders = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
    col_sql = ", ".join(columns)

    # ON CONFLICT: overwrite every supplied column except domain (the key),
    # status (the no-regress CASE below), and project (the partition key -- it is
    # never changed on an existing row; a cross-project re-add is rejected by the
    # WHERE guard).
    set_parts = [
        f"{c} = EXCLUDED.{c}"
        for c in columns
        if c not in ("domain", "status", "project")
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
        "WHERE leads.project = EXCLUDED.project "
        "RETURNING *"
    )

    pool = await get_pool()
    row = await pool.fetchrow(query, *data.values())
    if row is None:
        # The domain exists under a different project: the WHERE guard blocked
        # the update and the INSERT hit the conflict, so nothing was written.
        owner = await pool.fetchval(
            "SELECT project FROM leads WHERE domain = $1", domain
        )
        raise ValueError(
            f"domain {domain!r} already belongs to project {owner!r}; "
            f"not added to project {project!r}"
        )
    return dict(row)


async def list_leads(
    project: str = "pentest",
    status: str | None = None,
    min_score: int | None = None,
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    """Return leads for ``project``, newest/highest-scoring first (compact rows).

    Optionally filter by exact ``status`` and/or a ``bounty_fit_score`` floor.
    Ordered by ``bounty_fit_score DESC`` (NULLs last) then ``created_at DESC``.
    Returns the compact projection (see ``_LIST_SELECT``); ``offset`` paginates.
    """
    _check_project(project)
    clauses: list[str] = ["project = $1"]
    args: list = [project]
    if status is not None:
        args.append(status)
        clauses.append(f"status = ${len(args)}")
    if min_score is not None:
        args.append(min_score)
        clauses.append(f"bounty_fit_score >= ${len(args)}")

    where = "WHERE " + " AND ".join(clauses)
    args.append(limit)
    limit_ph = f"${len(args)}"
    args.append(offset)
    offset_ph = f"${len(args)}"
    query = (
        f"SELECT {_LIST_SELECT} FROM leads {where} "
        "ORDER BY bounty_fit_score DESC NULLS LAST, created_at DESC "
        f"LIMIT {limit_ph} OFFSET {offset_ph}"
    )

    pool = await get_pool()
    rows = await pool.fetch(query, *args)
    return [dict(r) for r in rows]


async def get_lead(domain: str, project: str = "pentest") -> dict | None:
    """Fetch a single lead (full row) by ``domain`` within ``project``."""
    _check_project(project)
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM leads WHERE project = $1 AND domain = $2", project, domain
    )
    return dict(row) if row else None


async def update_lead_status(
    domain: str,
    status: str,
    note: str | None = None,
    project: str = "pentest",
) -> dict:
    """Move a lead to ``status`` within ``project``; optionally append ``note``.

    ``status`` is validated against the enum. A supplied ``note`` is appended to
    the existing ``why`` (separated by `` | ``); pass ``None`` to leave it. Raises
    ``ValueError`` when no lead with that domain exists in this project.
    ``updated_at`` is refreshed by the table trigger.
    """
    _check_project(project)
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
        "WHERE project = $4 AND domain = $1 RETURNING *"
    )

    pool = await get_pool()
    row = await pool.fetchrow(query, domain, status, note, project)
    if row is None:
        raise ValueError(
            f"no lead with domain {domain!r} in project {project!r}"
        )
    return dict(row)


async def get_uncontacted(project: str = "pentest", limit: int = 20) -> list[dict]:
    """Leads in ``project`` not yet contacted (``qualified``/``contact_resolved``).

    Highest ``bounty_fit_score`` first (NULLs last), then newest. This is the
    work queue the session pulls from to drive contact resolution / outreach.
    Returns the compact projection (see ``_LIST_SELECT``).
    """
    _check_project(project)
    query = (
        f"SELECT {_LIST_SELECT} FROM leads "
        "WHERE project = $1 AND status IN ('qualified', 'contact_resolved') "
        "ORDER BY bounty_fit_score DESC NULLS LAST, created_at DESC "
        "LIMIT $2"
    )
    pool = await get_pool()
    rows = await pool.fetch(query, project, limit)
    return [dict(r) for r in rows]
