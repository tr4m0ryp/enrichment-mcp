-- 001_leads.sql -- Postgres schema for the enrichment_mcp lead store.
--
-- One lean `leads` table (PK = domain) behind the five state/CRM tools, plus
-- the salvaged `prospeo_usage` credit-metering table (T4). Fully idempotent:
-- CREATE TABLE IF NOT EXISTS, CREATE OR REPLACE FUNCTION, guarded trigger,
-- CREATE INDEX IF NOT EXISTS. No RLS, no GRANTs -- the `postgres` DSN role
-- bypasses RLS, so the server needs no policy/grant ceremony (F6).

BEGIN;

-- ---------------------------------------------------------------------------
-- Trigger function: auto-update updated_at on every UPDATE (mirrors clay).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- leads -- the single lean lead record (C7 / T7). PK is the company domain.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leads (
    domain                 TEXT        PRIMARY KEY,
    company_name           TEXT        NOT NULL,
    summary                TEXT,                       -- what they sell
    location               TEXT,
    webshop_platform       TEXT        CHECK (webshop_platform IN (
                                           'custom', 'shopify',
                                           'woocommerce', 'unknown')),
    bounty_fit_score       SMALLINT,                   -- >=7 keep-gate lives in the skill
    why                    TEXT,                       -- one-line rationale
    status                 TEXT        NOT NULL DEFAULT 'qualified'
                                       CHECK (status IN (
                                           'qualified', 'contact_resolved',
                                           'contacted', 'replied',
                                           'closed', 'rejected')),
    -- One decision-maker contact; all nullable per C8.
    contact_name           TEXT,
    contact_role           TEXT,
    contact_email          TEXT,
    contact_linkedin       TEXT,
    contact_email_verified BOOLEAN     NOT NULL DEFAULT false,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Guarded trigger: drop-then-create keeps the file re-runnable on PG < 14
-- (which lacks CREATE OR REPLACE TRIGGER).
DROP TRIGGER IF EXISTS trg_leads_updated_at ON leads;
CREATE TRIGGER trg_leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status);
CREATE INDEX IF NOT EXISTS idx_leads_bounty_fit_score
    ON leads (bounty_fit_score DESC);

-- ---------------------------------------------------------------------------
-- prospeo_usage -- credit metering (salvaged verbatim from clay's 012, T4).
-- We log only credit-spending Prospeo enrich-person calls; misses are
-- off-budget. used_at powers the "X / N used this month" summary.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prospeo_usage (
    id           BIGSERIAL PRIMARY KEY,
    used_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    key_prefix   TEXT,         -- redacted "pk_xxx...yyy" for forensics
    credits      SMALLINT NOT NULL DEFAULT 1,
    contact_id   UUID,         -- optional, for cross-referencing leads
    domain       TEXT,         -- target company domain
    free_dedup   BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS prospeo_usage_used_at
    ON prospeo_usage (used_at DESC);

COMMIT;
