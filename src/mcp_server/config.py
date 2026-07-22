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

    # Apollo.io people/match keys -- the failover tier behind Prospeo. Pooled
    # the same way, but Apollo gates this endpoint by plan: a key on a free or
    # trial plan gets 403 API_INACCESSIBLE, which retires that key after one
    # probe so resolution silently degrades to Prospeo-only. Apollo is skipped
    # entirely when unset, which is the pre-Apollo behaviour exactly.
    apollo_api_keys: list[str] = field(default_factory=list)

    # Whether the finder chain also fails over when a provider answers "no such
    # person" (as opposed to only on quota/outage). Providers hold different
    # databases and bill nothing when they return no data, so a second opinion
    # is close to free -- hence default on. Set false to spend Apollo credits
    # ONLY when Prospeo is actually down or exhausted.
    contact_fallback_on_no_match: bool = True

    # QuickEmailVerification key pool -- primary tier of the guess+verify
    # fallback (the verify_email tool). Comma-separated free-tier keys, 100
    # verifications/day each; pools the same way PROSPEO_API_KEYS does.
    quickemailverification_api_keys: list[str] = field(default_factory=list)

    # MyEmailVerifier key -- secondary/fallback tier of the guess+verify
    # path, used only when QuickEmailVerification is unconfigured or its
    # whole pool is exhausted; the paid key stays server-side.
    myemailverifier_api_key: str = ""

    # MCP transport: the static bearer the server enforces on every request,
    # plus the HTTP bind address.
    mcp_bearer_token: str = ""
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    # Lead partition this instance serves. The `leads` table is shared by more
    # than one outreach pipeline (pentest / bug-bounty and the Avelero licensing
    # pipeline); `project` tags every row so the two never commingle. This is the
    # instance-wide DEFAULT applied when a tool call omits `project`; a call may
    # still override it per-request. Default 'pentest' keeps the existing
    # single-instance behaviour unchanged.
    leads_project: str = "pentest"

    # Auth mode (T6). Empty -> static-bearer (Claude Code) or authless.
    # "supabase" -> OAuth via the project's own Supabase Auth (claude.ai web,
    # no separate IdP). "oidc" -> any OIDC provider (WorkOS / Descope / Auth0).
    mcp_oauth_provider: str = ""
    # Public HTTPS base URL of THIS server (no /mcp), required for any OAuth
    # mode -- it is what the OAuth metadata advertises and must match the URL
    # entered in the claude.ai connector. e.g. https://<svc>.run.app
    mcp_base_url: str = ""
    # workos mode: the AuthKit domain (https://<name>.authkit.app) + the WorkOS
    # application's client id and secret (the WorkOS API key acts as the secret).
    workos_authkit_domain: str = ""
    workos_client_id: str = ""
    workos_client_secret: str = ""
    # supabase mode: the project URL (https://<ref>.supabase.co), NOT the DB DSN.
    supabase_project_url: str = ""
    # oidc mode: the provider's OIDC discovery URL + client credentials.
    oidc_config_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""


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
        apollo_api_keys=[
            k.strip()
            for k in os.environ.get("APOLLO_API_KEYS", "").split(",")
            if k.strip()
        ],
        contact_fallback_on_no_match=os.environ.get(
            "CONTACT_FALLBACK_ON_NO_MATCH", "true",
        ).strip().lower() != "false",
        quickemailverification_api_keys=[
            k.strip()
            for k in os.environ.get(
                "QUICKEMAILVERIFICATION_API_KEYS", "",
            ).split(",")
            if k.strip()
        ],
        myemailverifier_api_key=os.environ.get(
            "MYEMAILVERIFIER_API_KEY", "",
        ).strip(),
        mcp_bearer_token=os.environ.get("MCP_BEARER_TOKEN", "").strip(),
        leads_project=(os.environ.get("LEADS_PROJECT", "").strip() or "pentest"),
        mcp_host=os.environ.get("MCP_HOST", "0.0.0.0").strip(),
        # Cloud Run (and most PaaS) inject the listen port as PORT; honor it
        # first so the container binds correctly, then MCP_PORT, then default.
        mcp_port=int(
            os.environ.get("PORT")
            or os.environ.get("MCP_PORT")
            or "8000"
        ),
        mcp_oauth_provider=os.environ.get("MCP_OAUTH_PROVIDER", "").strip().lower(),
        mcp_base_url=os.environ.get("MCP_BASE_URL", "").strip().rstrip("/"),
        workos_authkit_domain=os.environ.get(
            "WORKOS_AUTHKIT_DOMAIN", "",
        ).strip().rstrip("/"),
        workos_client_id=os.environ.get("WORKOS_CLIENT_ID", "").strip(),
        workos_client_secret=os.environ.get("WORKOS_CLIENT_SECRET", "").strip(),
        supabase_project_url=os.environ.get(
            "SUPABASE_PROJECT_URL", "",
        ).strip().rstrip("/"),
        oidc_config_url=os.environ.get("MCP_OIDC_CONFIG_URL", "").strip(),
        oidc_client_id=os.environ.get("MCP_OIDC_CLIENT_ID", "").strip(),
        oidc_client_secret=os.environ.get("MCP_OIDC_CLIENT_SECRET", "").strip(),
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
