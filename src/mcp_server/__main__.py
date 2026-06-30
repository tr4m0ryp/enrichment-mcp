"""Entrypoint: ``python -m src.mcp_server`` -> serve Streamable HTTP at ``/mcp``."""

from __future__ import annotations

from .server import run

if __name__ == "__main__":
    run()
