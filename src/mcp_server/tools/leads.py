"""The five lead-store tools (T10): thin async wrappers over ``db.leads``.

Each wrapper just calls a Task-003 data-access function and normalises the
asyncpg row(s) into JSON-friendly ``dict``s (timestamps -> ISO strings). The
docstrings below become the tool descriptions the session sees, so they state
exactly what the tool does and returns. ``ValueError``s raised by the store
(missing domain, bad status, unknown lead) are surfaced as proper tool errors.
"""

from __future__ import annotations

import datetime as _dt
import functools
from typing import Any, Awaitable, Callable

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ..db import (
    add_qualified_lead as _add_lead,
    get_lead as _get_lead,
    get_uncontacted as _get_uncontacted,
    list_leads as _list_leads,
    update_lead_status as _update_lead_status,
)


def _jsonable(value: Any) -> Any:
    """Map asyncpg scalar types FastMCP can't serialise to JSON primitives."""
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return value


def _row(row: dict | None) -> dict | None:
    """Normalise a single lead row (or ``None``)."""
    if row is None:
        return None
    return {key: _jsonable(val) for key, val in row.items()}


def _rows(rows: list[dict]) -> list[dict]:
    """Normalise a list of lead rows."""
    return [{key: _jsonable(val) for key, val in r.items()} for r in rows]


def _surface_value_errors(
    fn: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Translate the store's ``ValueError``s into client-visible tool errors.

    ``functools.wraps`` preserves ``__wrapped__`` / annotations so FastMCP
    still introspects the original signature for the tool's input schema.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


@_surface_value_errors
async def add_qualified_lead(lead: dict) -> dict:
    """Insert or update one qualified lead, keyed on its ``domain`` (upsert).

    ``lead`` carries the lean record: required ``domain`` and ``company_name``,
    plus optional ``summary``, ``location``, ``webshop_platform``,
    ``bounty_fit_score``, ``why`` and the single contact fields
    (``contact_name``/``contact_role``/``contact_email``/``contact_linkedin``/
    ``contact_email_verified``). Status is derived, never taken from the caller:
    a lead with any contact field seeds at ``contact_resolved``, otherwise
    ``qualified``. Re-adding never blanks existing data nor regresses an
    already-advanced status. Returns the stored row.

    Also accepts the contactform-nudge cache (``contactform_checked``,
    ``contactform_status``, ``contactform_url``, ``contactform_ts``) and the
    whatsapp-nudge cache (``whatsapp_checked``, ``whatsapp_number``,
    ``whatsapp_nudge_sent``, ``whatsapp_nudge_ts``). ``contactform_checked`` /
    ``whatsapp_nudge_sent`` are permanent skip-forever gates -- only pass them
    true on a genuinely terminal outcome (a real submit/send, or a permanent
    no-form/CAPTCHA/no-number skip), never on a transient connector error,
    which must stay retry-eligible on a later sweep.
    """
    return _row(await _add_lead(lead))  # type: ignore[return-value]


@_surface_value_errors
async def list_leads(
    status: str | None = None,
    min_score: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """List leads, highest ``bounty_fit_score`` first then newest.

    Optionally filter by exact ``status`` (one of qualified, contact_resolved,
    contacted, replied, agreement_sent, signed, authorized_ready, running,
    reported, closed, rejected) and/or a ``min_score`` floor on
    ``bounty_fit_score``. ``limit`` caps the number returned (default 50).
    """
    return _rows(
        await _list_leads(status=status, min_score=min_score, limit=limit)
    )


@_surface_value_errors
async def get_lead(domain: str) -> dict | None:
    """Fetch one lead by its ``domain``; returns the row or ``null`` if absent."""
    return _row(await _get_lead(domain))


@_surface_value_errors
async def update_lead_status(
    domain: str,
    status: str,
    note: str | None = None,
) -> dict:
    """Move a lead to ``status``; optionally append ``note`` to its rationale.

    ``status`` must be one of the enum values (qualified, contact_resolved,
    contacted, replied, agreement_sent, signed, authorized_ready, running,
    reported, closed, rejected). A supplied ``note`` is appended to
    the existing ``why`` (separated by `` | ``) as a short audit trail. Errors
    if the domain does not exist or the status is invalid. Returns the row.
    """
    return _row(await _update_lead_status(domain, status, note))  # type: ignore[return-value]


@_surface_value_errors
async def get_uncontacted(limit: int = 20) -> list[dict]:
    """List leads not yet contacted (status ``qualified``/``contact_resolved``).

    Highest ``bounty_fit_score`` first then newest -- the work queue the session
    pulls from to drive contact resolution. ``limit`` caps the count (default 20).
    """
    return _rows(await _get_uncontacted(limit))


def register_lead_tools(mcp: FastMCP) -> None:
    """Register the five lead-store tools on ``mcp``."""
    for fn in (
        add_qualified_lead,
        list_leads,
        get_lead,
        update_lead_status,
        get_uncontacted,
    ):
        mcp.tool(fn)


__all__ = [
    "add_qualified_lead",
    "list_leads",
    "get_lead",
    "update_lead_status",
    "get_uncontacted",
    "register_lead_tools",
]
