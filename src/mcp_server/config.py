"""Typed configuration for the enrichment_mcp lead-finder server.

Plain ``@dataclass`` + ``python-dotenv`` -- no pydantic (T10/F2), mirroring the
salvaged clay config pattern but trimmed to the seven variables this server
needs: the Supabase DSN, the Prospeo key pool + mobile gate, the
MyEmailVerifier key, and the MCP bearer/host/port. ``get_config()`` is a lazy
singleton; ``SUPABASE_DB_URL`` is the only structurally-required value.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Supabase Postgres DSN -- the one structurally-required var. The asyncpg
    # pool (db/pool.py) builds directly from this; an empty value is logged as
    # an error at load time and will fail fast when the pool is first opened.
    supabase_db_url: str = ""

    # Prospeo enrich-person key pool. Comma-separated free-tier keys; each
    # grants ~75-100 enrichments/month, so the pool scales linearly with the
    # number of keys. Mobile enrichment costs 10x credits and stays opt-in via
    # PROSPEO_ENRICH_MOBILE (default email + LinkedIn only).
    prospeo_api_keys: list[str] = field(default_factory=list)
    prospeo_enrich_mobile: bool = False

    # MyEmailVerifier key for the in-session guess+verify fallback path
    # (the verify_email tool); the paid key stays server-side.
    myemailverifier_api_key: str = ""

    # MCP transport: the static bearer the server enforces on every request,
    # plus the HTTP bind address.
    mcp_bearer_token: str = ""
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000


def _load_config() -> Config:
    cfg = Config(
        supabase_db_url=os.environ.get("SUPABASE_DB_URL", "").strip(),
        prospeo_api_keys=[
            k.strip()
            for k in os.environ.get("PROSPEO_API_KEYS", "").split(",")
            if k.strip()
        ],
        prospeo_enrich_mobile=os.environ.get(
            "PROSPEO_ENRICH_MOBILE", "false",
        ).strip().lower() == "true",
        myemailverifier_api_key=os.environ.get(
            "MYEMAILVERIFIER_API_KEY", "",
        ).strip(),
        mcp_bearer_token=os.environ.get("MCP_BEARER_TOKEN", "").strip(),
        mcp_host=os.environ.get("MCP_HOST", "0.0.0.0").strip(),
        # Cloud Run (and most PaaS) inject the listen port as PORT; honor it
        # first so the container binds correctly, then MCP_PORT, then default.
        mcp_port=int(
            os.environ.get("PORT")
            or os.environ.get("MCP_PORT")
            or "8000"
        ),
    )

    if not cfg.supabase_db_url:
        logging.getLogger(__name__).error(
            "Missing required environment variable SUPABASE_DB_URL "
            "(full Postgres DSN). Set it in .env before starting the server.",
        )

    return cfg


_config: Config | None = None


def get_config() -> Config:
    """Return the process-wide ``Config``, building it on first call."""
    global _config
    if _config is None:
        _config = _load_config()
    return _config
