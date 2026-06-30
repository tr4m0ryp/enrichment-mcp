#!/usr/bin/env bash
# deploy/setup-incus.sh -- Incus provisioning runbook for enrichment-mcp
#
# WHAT: Launches a small Incus instance on the Mac mini, deploys the FastMCP
#       server inside it, and publishes it via the existing Cloudflare tunnel as:
#           https://enrichment-mcp.frogbytes.xyz/mcp
#
# WHERE TO RUN: Mac mini (10.0.0.138) as user tr4m0ryp.
#
# NOT AUTOMATED: read each section before executing. Steps that require manual
#                input are marked [MANUAL]. Run sections top-to-bottom; after
#                step 1, set INSTANCE_IP before continuing.
#
# PRE-REQUISITES:
#   - Incus is installed; bridge 10.42.0.0/24 exists on the host.
#   - The Cloudflare named tunnel (frogbytes.xyz) is running.
#   - cf-publish helper is on PATH.
#   - The repo is checked out on the host (or available to push).

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration -- edit INSTANCE_IP after step 1 reveals it
# ---------------------------------------------------------------------------
INSTANCE_NAME="enrichment-mcp"
APP_USER="mcpsvr"
APP_DIR="/opt/enrichment-mcp"
APP_PORT="8000"
UNIT_SRC="$(dirname "$0")/enrichment-mcp.service"
UNIT_NAME="enrichment-mcp.service"

# Set this after running step 1 and noting the 10.42.0.x address:
INSTANCE_IP="${INSTANCE_IP:-<INSTANCE_IP>}"

# Guard: abort before any step that needs a real IP
_require_ip() {
  if [[ "$INSTANCE_IP" == "<INSTANCE_IP>" ]]; then
    echo "[ERROR] INSTANCE_IP is still a placeholder."
    echo "        Run step 1, note the 10.42.0.x address, then:"
    echo "        INSTANCE_IP=10.42.0.x bash $0"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# 1. Launch the Incus instance (idempotent -- skips if already exists)
# ---------------------------------------------------------------------------
echo "==> [1] Launch Incus instance: $INSTANCE_NAME"
if incus info "$INSTANCE_NAME" &>/dev/null; then
  echo "    Instance already exists; skipping launch."
else
  incus launch ubuntu:24.04 "$INSTANCE_NAME"
  echo "    Waiting for network inside the instance..."
  sleep 10
fi

echo "==> Instance IPs (set INSTANCE_IP to the 10.42.0.x address):"
incus list "$INSTANCE_NAME" -c 4 --format csv

if [[ "$INSTANCE_IP" == "<INSTANCE_IP>" ]]; then
  echo "    INSTANCE_IP not set. Export it and re-run to continue:"
  echo "      INSTANCE_IP=10.42.0.x bash $0"
  exit 0
fi

# ---------------------------------------------------------------------------
# 2. Install Python 3.12 + venv tools inside the instance
# ---------------------------------------------------------------------------
_require_ip
echo "==> [2] Installing Python 3.12 inside $INSTANCE_NAME"
incus exec "$INSTANCE_NAME" -- apt-get update -qq
incus exec "$INSTANCE_NAME" -- apt-get install -y --no-install-recommends \
  python3.12 python3.12-venv python3.12-dev git curl ca-certificates

# ---------------------------------------------------------------------------
# 3. Create the non-root app user (idempotent)
# ---------------------------------------------------------------------------
echo "==> [3] Creating service user: $APP_USER"
incus exec "$INSTANCE_NAME" -- bash -c \
  "id $APP_USER &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin $APP_USER"

# ---------------------------------------------------------------------------
# 4. Push the application source into the instance
#    [MANUAL] Choose option A or B; uncomment the relevant block.
# ---------------------------------------------------------------------------
echo "==> [4] Push application source to $APP_DIR"
#
# Option A -- pack the local checkout and push (recommended for a host checkout):
#   REPO_ROOT="/path/to/enrichment_mcp"
#   tar -czf /tmp/enrichment-mcp.tar.gz -C "$REPO_ROOT" \
#     src requirements.txt schema
#   incus file push /tmp/enrichment-mcp.tar.gz "$INSTANCE_NAME/tmp/"
#   incus exec "$INSTANCE_NAME" -- bash -c \
#     "mkdir -p $APP_DIR && tar -xzf /tmp/enrichment-mcp.tar.gz -C $APP_DIR"
#
# Option B -- git clone inside the instance:
#   incus exec "$INSTANCE_NAME" -- bash -c \
#     "git clone https://github.com/<owner>/<repo>.git $APP_DIR"
#
echo "    [MANUAL] Uncomment and run Option A or B above, then continue."

# ---------------------------------------------------------------------------
# 5. Create the Python venv and install dependencies
# ---------------------------------------------------------------------------
echo "==> [5] Setting up venv in $APP_DIR"
incus exec "$INSTANCE_NAME" -- bash -c "
  python3.12 -m venv $APP_DIR/.venv &&
  $APP_DIR/.venv/bin/pip install --upgrade pip --quiet &&
  $APP_DIR/.venv/bin/pip install -r $APP_DIR/requirements.txt --quiet
"

# ---------------------------------------------------------------------------
# 6. Drop the .env file
#    [MANUAL] Create /tmp/enrichment-mcp.env on the HOST with real credentials
#    before running this step. The 7 required vars are listed in .env.example.
#    Never commit credentials; delete /tmp/enrichment-mcp.env after this step.
#
#    Required vars:
#      SUPABASE_DB_URL       -- full postgres://... DSN to Supabase
#      PROSPEO_API_KEYS      -- comma-separated API keys
#      PROSPEO_ENRICH_MOBILE -- 0 (email-only, 1 credit) or 1 (adds mobile, 10 credits)
#      MYEMAILVERIFIER_API_KEY
#      MCP_BEARER_TOKEN      -- strong random string; used in the claude mcp add command
#      MCP_HOST              -- 0.0.0.0
#      MCP_PORT              -- 8000
# ---------------------------------------------------------------------------
echo "==> [6] Pushing .env to $APP_DIR"
if [[ ! -f /tmp/enrichment-mcp.env ]]; then
  echo "[ERROR] /tmp/enrichment-mcp.env not found."
  echo "        Create it with the 7 required vars (see .env.example), then re-run."
  exit 1
fi
incus file push /tmp/enrichment-mcp.env "$INSTANCE_NAME/${APP_DIR#/}/.env"
incus exec "$INSTANCE_NAME" -- chmod 600 "$APP_DIR/.env"
incus exec "$INSTANCE_NAME" -- chown "$APP_USER:$APP_USER" "$APP_DIR/.env"

# ---------------------------------------------------------------------------
# 7. Install and enable the systemd unit
# ---------------------------------------------------------------------------
echo "==> [7] Installing systemd unit: $UNIT_NAME"
incus file push "$UNIT_SRC" "$INSTANCE_NAME/etc/systemd/system/$UNIT_NAME"
incus exec "$INSTANCE_NAME" -- chown -R "$APP_USER:$APP_USER" "$APP_DIR"
incus exec "$INSTANCE_NAME" -- systemctl daemon-reload
incus exec "$INSTANCE_NAME" -- systemctl enable "$UNIT_NAME"
incus exec "$INSTANCE_NAME" -- systemctl start "$UNIT_NAME"
incus exec "$INSTANCE_NAME" -- systemctl status "$UNIT_NAME" --no-pager

# ---------------------------------------------------------------------------
# 8. Quick health check
# ---------------------------------------------------------------------------
echo "==> [8] Health check: http://$INSTANCE_IP:$APP_PORT/mcp"
sleep 4
if curl -sf "http://$INSTANCE_IP:$APP_PORT/mcp" -o /dev/null; then
  echo "    Server is responding."
else
  echo "    [WARN] No response yet. Check logs:"
  echo "      incus exec $INSTANCE_NAME -- journalctl -u $UNIT_NAME -n 50"
fi

# ---------------------------------------------------------------------------
# 9. Publish via the Cloudflare named tunnel
#
#    cf-publish <slug> http://<backend> maps to https://<slug>.frogbytes.xyz
#    The tunnel is outbound-only; no inbound ports are needed on the host.
#
#    HOST-HEADER CAVEAT (R6): Cloudflare forwards requests with the Host header
#    set to enrichment-mcp.frogbytes.xyz. If FastMCP/ASGI rejects it with
#    421 Misdirected Request, configure the tunnel ingress:
#      httpHostHeader: enrichment-mcp.frogbytes.xyz
#    or start the server with --allowed-hosts=enrichment-mcp.frogbytes.xyz.
#    Verify at deploy by checking server logs immediately after cf-publish.
# ---------------------------------------------------------------------------
echo "==> [9] Publishing via Cloudflare tunnel"
cf-publish "enrichment-mcp" "http://$INSTANCE_IP:$APP_PORT"

echo ""
echo "Public MCP endpoint: https://enrichment-mcp.frogbytes.xyz/mcp"
echo ""
echo "Connect Claude Code with:"
echo "  claude mcp add --transport http enrichment-mcp \\"
echo "    https://enrichment-mcp.frogbytes.xyz/mcp \\"
echo "    --header \"Authorization: Bearer <MCP_BEARER_TOKEN>\""
echo ""
echo "Done."
