"""FastMCP app, static-bearer auth, tool registration, and ``run()`` (T5, T6).

Builds the ``enrichment-mcp`` Streamable-HTTP server: one auth layer plus the
seven tools, served at ``/mcp``. Construction is pure -- no DB or Prospeo
connection happens here, so importing this module (and the module-level ``mcp``
app it builds) never touches the network. The contact tools open their pool /
HTTP sessions lazily on first call.

Auth is isolated in :func:`_build_auth`: today a static bearer token equal to
``config.mcp_bearer_token``; swapping to OAuth later (an ``OIDCProxy`` /
``RemoteAuthProvider``) is a one-function change.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from .config import Config, get_config
from .tools import register_tools

logger = logging.getLogger(__name__)

SERVER_NAME = "enrichment-mcp"
# Identity attached to the single static bearer token. Cosmetic today; the
# slot OAuth client identities will fill once auth is swapped.
_BEARER_CLIENT_ID = "lead-finder-session"


def _build_auth(config: Config) -> AuthProvider | None:
    """Return the server's single auth layer, or ``None`` for authless dev.

    Static-bearer mode (T6): any request whose ``Authorization: Bearer <token>``
    equals ``config.mcp_bearer_token`` is accepted. Isolated here so moving to
    OAuth later touches exactly this function. When the token is empty we log a
    loud warning and return ``None`` -- the server then runs authless, which is
    acceptable only for local development.
    """
    token = config.mcp_bearer_token
    if not token:
        logger.warning(
            "MCP_BEARER_TOKEN is empty -- starting AUTHLESS: every /mcp request "
            "will be accepted. Set MCP_BEARER_TOKEN before exposing this server "
            "beyond localhost.",
        )
        return None
    return StaticTokenVerifier(
        tokens={token: {"client_id": _BEARER_CLIENT_ID, "scopes": []}},
    )


def build_server(config: Config | None = None) -> FastMCP:
    """Construct the FastMCP app with auth and the seven registered tools.

    Pure construction: safe to call at import time and from tests. No network.
    """
    config = config or get_config()
    mcp = FastMCP(SERVER_NAME, auth=_build_auth(config))
    register_tools(mcp)
    return mcp


# Module-level app object (the verification target). Building it registers the
# seven tools and the auth layer but opens no connections.
mcp = build_server()


def run() -> None:
    """Serve the app over Streamable HTTP at ``/mcp`` on the configured bind.

    FastMCP 3.4.2 exposes no allowed-hosts / trusted-host knob through ``run()``
    or its settings, so the tunnel host-header mitigation (see Risks) is handled
    at the reverse-proxy / Cloudflare-tunnel layer in deploy (Task 006), not here.
    """
    config = get_config()
    logger.info(
        "Starting %s over Streamable HTTP at http://%s:%d/mcp",
        SERVER_NAME,
        config.mcp_host,
        config.mcp_port,
    )
    mcp.run(transport="http", host=config.mcp_host, port=config.mcp_port)


__all__ = ["mcp", "run", "build_server"]
