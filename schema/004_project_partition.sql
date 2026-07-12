-- 004_project_partition.sql -- tag every lead with the pipeline that owns it.
--
-- The `leads` table is shared by more than one outreach pipeline: the pentest /
-- bug-bounty pipeline and the Avelero licensing pipeline both call the same
-- enrichment MCP. Until now nothing distinguished their rows, so the two
-- commingled in one table (and, keyed on `domain` alone, a company targeted by
-- both would collide on the primary key). This adds a `project` discriminator so
-- each pipeline sees only its own leads.
--
-- Existing rows are the pentest pipeline's corpus, so they default to 'pentest'.
-- The server scopes every read/write by `project` (LEADS_PROJECT env default
-- 'pentest', overridable per tool call); add_qualified_lead refuses to overwrite
-- a domain owned by a different project.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, guarded constraint, CREATE INDEX IF NOT
-- EXISTS. `domain` stays the primary key (a domain belongs to one project;
-- first writer wins), so this migration is purely additive and safe to run
-- against the live table with the old server still up.
--
-- Apply:  psql "$SUPABASE_DB_URL" -f schema/004_project_partition.sql

BEGIN;

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS project TEXT NOT NULL DEFAULT 'pentest';

-- Widen/(re)assert the allow-list constraint idempotently.
ALTER TABLE leads DROP CONSTRAINT IF EXISTS leads_project_check;
ALTER TABLE leads ADD CONSTRAINT leads_project_check
    CHECK (project IN ('pentest', 'avelero'));

-- The filtered reads (WHERE project = $1 [...]) and the per-project work queue
-- lean on this index.
CREATE INDEX IF NOT EXISTS idx_leads_project ON leads (project);
CREATE INDEX IF NOT EXISTS idx_leads_project_status ON leads (project, status);

COMMENT ON COLUMN leads.project IS
    'Owning outreach pipeline: pentest | avelero. Set on insert, never changed '
    'on re-add; the server scopes every read/write to one project so the two '
    'pipelines'' leads never commingle.';

COMMIT;
