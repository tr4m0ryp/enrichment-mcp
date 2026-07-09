#!/usr/bin/env bash
# Reproducible Cloud Run deploy for the enrichment-mcp server.
# One-time provisioning + deploy. Re-running the deploy step is safe (new revision).
#
# Prereqs: gcloud authenticated; a billing account id; the data secrets
# (Supabase DSN, Prospeo keys, QuickEmailVerification keys, MyEmailVerifier
# key) to hand.
set -euo pipefail

# ---- configure these ----
PROJECT_ID="${PROJECT_ID:-enrichment-mcp-XXXXXX}"   # globally-unique project id
BILLING_ACCOUNT="${BILLING_ACCOUNT:-XXXXXX-XXXXXX-XXXXXX}"
REGION="${REGION:-europe-west1}"
SERVICE="enrichment-mcp"
# --------------------------

# 1. Project + billing (skip if it already exists).
gcloud projects create "$PROJECT_ID" --name="enrichment-mcp" 2>/dev/null || true
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"
gcloud config set project "$PROJECT_ID"

# 2. APIs.
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com

# 3. Secrets. The bearer is generated here; the three data secrets are created
#    as placeholders -- replace them with real values (see step 5).
NUM=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
SA="${NUM}-compute@developer.gserviceaccount.com"
create_secret() { gcloud secrets create "$1" --data-file=- --replication-policy=automatic 2>/dev/null \
                  || gcloud secrets versions add "$1" --data-file=- ; }
openssl rand -hex 32          | create_secret MCP_BEARER_TOKEN
printf 'REPLACE_ME'           | create_secret SUPABASE_DB_URL
printf 'REPLACE_ME'           | create_secret PROSPEO_API_KEYS
printf ''                     | create_secret QUICKEMAILVERIFICATION_API_KEYS
printf 'REPLACE_ME'           | create_secret MYEMAILVERIFIER_API_KEY
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role="roles/secretmanager.secretAccessor" >/dev/null

# 4. Deploy from source (builds the Dockerfile via Cloud Build).
gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" \
  --allow-unauthenticated --max-instances 1 \
  --set-secrets=MCP_BEARER_TOKEN=MCP_BEARER_TOKEN:latest,SUPABASE_DB_URL=SUPABASE_DB_URL:latest,PROSPEO_API_KEYS=PROSPEO_API_KEYS:latest,QUICKEMAILVERIFICATION_API_KEYS=QUICKEMAILVERIFICATION_API_KEYS:latest,MYEMAILVERIFIER_API_KEY=MYEMAILVERIFIER_API_KEY:latest

# 5. Set the real data secrets, then redeploy to pick them up:
#    printf '%s' '<your full postgres DSN>'  | gcloud secrets versions add SUPABASE_DB_URL --data-file=-
#    printf '%s' 'key1,key2'                  | gcloud secrets versions add PROSPEO_API_KEYS --data-file=-
#    printf '%s' 'qev_key1,qev_key2'           | gcloud secrets versions add QUICKEMAILVERIFICATION_API_KEYS --data-file=-
#    printf '%s' 'your-verifier-key'          | gcloud secrets versions add MYEMAILVERIFIER_API_KEY --data-file=-
#    (then re-run step 4)
#
# Apply the schema once to your Postgres (run every numbered file in order):
#    psql "<SUPABASE_DB_URL>" -f schema/001_leads.sql
#    psql "<SUPABASE_DB_URL>" -f schema/002_engagement_statuses.sql
#    psql "<SUPABASE_DB_URL>" -f schema/003_nudge_channels.sql
#
# Read the bearer for `claude mcp add`:
#    gcloud secrets versions access latest --secret=MCP_BEARER_TOKEN
#
# 6. (Optional) Enable OAuth for the claude.ai WEB connector. Use the STATELESS
#    authkit mode: the server only verifies AuthKit JWTs; claude.ai registers
#    (DCR) and refreshes tokens directly with AuthKit, so Cloud Run instance
#    recycling never forces re-authentication. Enable Dynamic Client
#    Registration in the WorkOS dashboard first. Config, not secrets:
#    gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated --max-instances 1 \
#      --set-secrets=MCP_BEARER_TOKEN=MCP_BEARER_TOKEN:latest,SUPABASE_DB_URL=SUPABASE_DB_URL:latest,PROSPEO_API_KEYS=PROSPEO_API_KEYS:latest,QUICKEMAILVERIFICATION_API_KEYS=QUICKEMAILVERIFICATION_API_KEYS:latest,MYEMAILVERIFIER_API_KEY=MYEMAILVERIFIER_API_KEY:latest \
#      --set-env-vars=MCP_OAUTH_PROVIDER=authkit,WORKOS_AUTHKIT_DOMAIN=https://<tenant>.authkit.app,MCP_BASE_URL=https://<service-url>
#    NOTE: switching to OAuth means the static bearer (Claude Code) stops being
#    accepted -- the server now expects AuthKit-issued tokens.
