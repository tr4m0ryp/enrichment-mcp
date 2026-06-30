"""Pluggable auth layer for the MCP server (T6).

One function, ``build_auth``, selects the auth provider from config so the rest
of the server never branches on it. Modes, by ``MCP_OAUTH_PROVIDER``:

- ``"workos"`` -- OAuth via WorkOS AuthKit (the recommended claude.ai-web path).
  AuthKit supports Dynamic Client Registration natively, so ``AuthKitProvider``
  needs only ``WORKOS_AUTHKIT_DOMAIN`` + ``MCP_BASE_URL`` -- no client secret.
- ``"oidc"`` -- OAuth via any OIDC provider (Descope, Auth0, Google, or WorkOS
  the manual way) through ``OIDCProxy`` (FastMCP performs DCR itself). Needs
  ``MCP_OIDC_CONFIG_URL`` + ``MCP_OIDC_CLIENT_ID`` (+ secret) + ``MCP_BASE_URL``.
- ``"supabase"`` -- OAuth backed by the project's OWN Supabase Auth via
  ``SupabaseProvider``. Needs ``SUPABASE_PROJECT_URL`` + ``MCP_BASE_URL``. NOTE:
  this delegates DCR to Supabase, which only works if the project advertises a
  registration endpoint -- many do not, so prefer ``workos``/``oidc``.
- empty -- static bearer (Claude Code) when ``MCP_BEARER_TOKEN`` is set, else
  authless (local dev only).

Provider classes are imported lazily inside each branch so the unused ones never
load and a missing optional dependency only bites the mode that needs it.
"""

from __future__ import annotations

import logging

from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from .config import Config

logger = logging.getLogger(__name__)

# Identity attached to the static bearer token (cosmetic; OAuth fills real ids).
_BEARER_CLIENT_ID = "lead-finder-session"


def build_auth(config: Config) -> AuthProvider | None:
    """Return the server's single auth layer, or ``None`` for authless dev."""
    provider = config.mcp_oauth_provider
    if provider == "workos":
        return _workos(config)
    if provider == "oidc":
        return _oidc(config)
    if provider == "supabase":
        return _supabase(config)
    if provider:
        raise ValueError(
            f"Unknown MCP_OAUTH_PROVIDER={provider!r}; "
            "use 'supabase', 'oidc', or leave empty for bearer/authless.",
        )

    # No OAuth provider configured: static bearer, or authless.
    if config.mcp_bearer_token:
        return StaticTokenVerifier(
            tokens={
                config.mcp_bearer_token: {
                    "client_id": _BEARER_CLIENT_ID,
                    "scopes": [],
                },
            },
        )
    logger.warning(
        "No auth configured (no MCP_OAUTH_PROVIDER, no MCP_BEARER_TOKEN) -- "
        "starting AUTHLESS: every /mcp request is accepted. Configure auth "
        "before exposing this server.",
    )
    return None


def _require(config: Config, *fields: str) -> None:
    missing = [f for f in fields if not getattr(config, f, "")]
    if missing:
        env = {
            "supabase_project_url": "SUPABASE_PROJECT_URL",
            "mcp_base_url": "MCP_BASE_URL",
            "oidc_config_url": "MCP_OIDC_CONFIG_URL",
            "oidc_client_id": "MCP_OIDC_CLIENT_ID",
        }
        names = ", ".join(env.get(f, f) for f in missing)
        raise ValueError(
            f"MCP_OAUTH_PROVIDER={config.mcp_oauth_provider!r} requires: {names}",
        )


def _supabase(config: Config) -> AuthProvider:
    """OAuth via the project's own Supabase Auth (DCR-ready for claude.ai)."""
    from fastmcp.server.auth.providers.supabase import SupabaseProvider

    _require(config, "supabase_project_url", "mcp_base_url")
    logger.info(
        "Auth: Supabase OAuth (project=%s, resource=%s)",
        config.supabase_project_url,
        config.mcp_base_url,
    )
    return SupabaseProvider(
        project_url=config.supabase_project_url,
        base_url=config.mcp_base_url,
    )


def _oidc(config: Config) -> AuthProvider:
    """OAuth via any OIDC provider (WorkOS / Descope / Auth0 / ...)."""
    from fastmcp.server.auth.oidc_proxy import OIDCProxy

    _require(config, "oidc_config_url", "oidc_client_id", "mcp_base_url")
    logger.info("Auth: OIDC OAuth (config_url=%s)", config.oidc_config_url)
    return OIDCProxy(
        config_url=config.oidc_config_url,
        client_id=config.oidc_client_id,
        client_secret=config.oidc_client_secret or None,
        base_url=config.mcp_base_url,
    )


__all__ = ["build_auth"]
