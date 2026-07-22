-- 005_provider_column.sql -- attribute credit burn to an enrichment provider.
--
-- `prospeo_usage` predates the multi-provider finder chain (Prospeo primary,
-- Apollo failover). The table keeps its name so no existing reader breaks;
-- `provider` is what separates the two providers' spend from here on.
--
-- Existing rows are backfilled to 'prospeo' because that is the only provider
-- that could have written them. The DEFAULT keeps any straggler writer that
-- has not been redeployed yet inserting valid rows. Idempotent: ADD COLUMN IF
-- NOT EXISTS, CREATE INDEX IF NOT EXISTS.

BEGIN;

ALTER TABLE prospeo_usage
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'prospeo';

-- Per-provider month-to-date rollups scan by (provider, used_at); the existing
-- used_at index alone forces a filter over every provider's rows.
CREATE INDEX IF NOT EXISTS prospeo_usage_provider_used_at
    ON prospeo_usage (provider, used_at DESC);

COMMIT;
