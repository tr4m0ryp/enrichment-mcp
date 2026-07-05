-- 002_engagement_statuses.sql -- widen the leads.status CHECK constraint.
--
-- 001 shipped the six CRM-lifecycle statuses (qualified -> ... -> closed/
-- rejected). The engagement flow added five states that the DB must now
-- accept: agreement_sent, signed, authorized_ready, running, reported --
-- the states signature-verification, the shor-run, and the manager persist.
--
-- CREATE TABLE IF NOT EXISTS in 001 never alters an existing table, so a
-- deployed DB keeps the old constraint until this migration runs. Idempotent:
-- drop the constraint if present, re-add it with the full 11-value set. The
-- new constraint keeps the auto-generated name `leads_status_check` so 001 and
-- 002 converge on the same schema whichever ran first.
--
-- Apply:  psql "$SUPABASE_DB_URL" -f schema/002_engagement_statuses.sql

BEGIN;

ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_status_check;

ALTER TABLE leads ADD CONSTRAINT leads_status_check CHECK (status IN (
    'qualified', 'contact_resolved',
    'contacted', 'replied',
    'agreement_sent', 'signed',
    'authorized_ready', 'running',
    'reported',
    'closed', 'rejected'
));

COMMIT;
