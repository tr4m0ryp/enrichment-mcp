-- 003_nudge_channels.sql -- add the contact-form and WhatsApp nudge cache
-- columns that the pentest-pipeline's contactform-nudge / whatsapp-nudge
-- skills have relied on since their introduction, but that were never
-- migrated: add_qualified_lead's fixed column allow-list silently dropped
-- every one of these keys, so neither skill's one-shot-ever guarantee was
-- ever actually persisted.
--
-- Apply:  psql "$SUPABASE_DB_URL" -f schema/003_nudge_channels.sql

BEGIN;

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS contactform_checked BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS contactform_status   TEXT CHECK (contactform_status IS NULL OR contactform_status IN (
                                   'submitted', 'skipped-noform', 'skipped-jsblocked',
                                   'skipped-captcha', 'skipped-error')),
    ADD COLUMN IF NOT EXISTS contactform_url       TEXT,
    ADD COLUMN IF NOT EXISTS contactform_ts        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS whatsapp_checked       BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS whatsapp_number        TEXT,
    ADD COLUMN IF NOT EXISTS whatsapp_nudge_sent    BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS whatsapp_nudge_ts      TIMESTAMPTZ;

COMMENT ON COLUMN leads.contactform_checked IS
    'Permanent skip-forever gate. Set true ONLY on a terminal outcome '
    '(submitted / skipped-noform / skipped-jsblocked / skipped-captcha) -- '
    'never on skipped-error, which must stay retry-eligible on a later sweep.';
COMMENT ON COLUMN leads.whatsapp_nudge_sent IS
    'True once the two-message nudge pair has actually sent. Never set on a '
    'failed/blocked send attempt.';

COMMIT;
