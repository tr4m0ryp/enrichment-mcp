"""Contact-layer helpers: domain extraction and name splitting.

Two small pure functions with no project dependencies, ported verbatim from
clay's people layer so ``resolve_contact`` can normalise the Claude-supplied
``domain`` and ``person_name`` before hitting Prospeo.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def extract_domain(website_url: str) -> str:
    """Extract the bare domain from a company website URL.

    Handles URLs with or without scheme, strips 'www.' prefix.

    Args:
        website_url: Raw URL string (e.g. "https://www.example.com/about").

    Returns:
        Bare domain string (e.g. "example.com"), or empty string if
        the URL cannot be parsed.
    """
    if not website_url:
        return ""

    url = website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def split_name(full_name: str) -> tuple[str, str]:
    """Split a full name into first and last name for email construction.

    For multi-word names, returns the FIRST word and the LAST word --
    middle names, initials, and particles ("de", "van", "von", "L.")
    are dropped. Most email-pattern systems (Hunter, Apollo, etc.)
    follow the same convention; matching them keeps constructed
    addresses aligned with how mailbox local-parts are actually
    provisioned.

    Examples:
        "Anne Marie L. Nielsen"     -> ("Anne", "Nielsen")
        "Carolina Álvarez-Ossorio"  -> ("Carolina", "Álvarez-Ossorio")
        "Iñigo de la Fuente"        -> ("Iñigo", "Fuente")
        "Mats Rombaut"              -> ("Mats", "Rombaut")
        "Madonna"                   -> ("Madonna", "")

    Args:
        full_name: Full name string.

    Returns:
        Tuple of (first_name, last_name). Last name is empty for
        single-word names.
    """
    parts = full_name.strip().split()
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[-1])
