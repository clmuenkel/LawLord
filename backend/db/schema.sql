-- LawLord Database Schema
-- Target: Neon PostgreSQL (supports pgvector)

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================
-- INTAKE SESSIONS
-- Stores chat conversations and generated reports
-- ============================================================
CREATE TABLE IF NOT EXISTS intake_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    state           VARCHAR(50) DEFAULT 'greeting',
    case_type       VARCHAR(50),
    gathered_facts  JSONB DEFAULT '{}',
    conversation    JSONB DEFAULT '[]',
    recommendation  VARCHAR(50),
    report          JSONB,
    client_info     JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sessions_case_type ON intake_sessions(case_type);
CREATE INDEX IF NOT EXISTS idx_sessions_recommendation ON intake_sessions(recommendation);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON intake_sessions(created_at DESC);

-- ============================================================
-- CASE OPINIONS
-- Court opinions from CAP / CourtListener
-- Filtered to Texas criminal (DWI, traffic, parking)
-- ============================================================
CREATE TABLE IF NOT EXISTS case_opinions (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(50) NOT NULL,           -- 'courtlistener' or 'cap'
    source_id       VARCHAR(200) UNIQUE,            -- ID from origin system
    case_name       TEXT NOT NULL,
    court           VARCHAR(200) NOT NULL,          -- e.g. 'texcrimapp', 'texapp'
    court_full_name TEXT,
    date_filed      DATE,
    docket_number   VARCHAR(300),
    citations       TEXT[],                         -- array of citation strings
    case_type       VARCHAR(50),                    -- 'dwi', 'parking_ticket', etc.
    opinion_type    VARCHAR(50),                    -- 'majority', 'concurrence', 'dissent'
    opinion_text    TEXT,                           -- full text of the opinion
    summary         TEXT,                           -- AI or human-written summary
    outcome         VARCHAR(300),                   -- 'affirmed', 'reversed', 'remanded'
    judges          TEXT[],
    statutes_cited  TEXT[],                         -- e.g. 'Tex. Penal Code § 49.04'
    tags            TEXT[],                         -- extracted topics
    metadata        JSONB DEFAULT '{}',             -- anything else from the source
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    -- Full-text search vector (auto-populated by trigger)
    search_vector   tsvector
);

CREATE INDEX IF NOT EXISTS idx_opinions_case_type ON case_opinions(case_type);
CREATE INDEX IF NOT EXISTS idx_opinions_court ON case_opinions(court);
CREATE INDEX IF NOT EXISTS idx_opinions_date ON case_opinions(date_filed DESC);
CREATE INDEX IF NOT EXISTS idx_opinions_source ON case_opinions(source, source_id);
CREATE INDEX IF NOT EXISTS idx_opinions_outcome ON case_opinions(outcome);
CREATE INDEX IF NOT EXISTS idx_opinions_search ON case_opinions USING gin(search_vector);
CREATE INDEX IF NOT EXISTS idx_opinions_statutes ON case_opinions USING gin(statutes_cited);
CREATE INDEX IF NOT EXISTS idx_opinions_tags ON case_opinions USING gin(tags);

-- Auto-update search_vector on insert/update
CREATE OR REPLACE FUNCTION update_opinion_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.case_name, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.summary, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.opinion_text, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_opinion_search_vector ON case_opinions;
CREATE TRIGGER trg_opinion_search_vector
    BEFORE INSERT OR UPDATE OF case_name, summary, opinion_text
    ON case_opinions
    FOR EACH ROW
    EXECUTE FUNCTION update_opinion_search_vector();

-- ============================================================
-- CASE EMBEDDINGS (for semantic / vector search)
-- Stores vector representations of case opinions
-- Enables "find similar cases" queries
-- ============================================================
CREATE TABLE IF NOT EXISTS case_embeddings (
    id              SERIAL PRIMARY KEY,
    opinion_id      INT NOT NULL REFERENCES case_opinions(id) ON DELETE CASCADE,
    model           VARCHAR(100) NOT NULL,          -- e.g. 'text-embedding-3-small'
    chunk_index     INT DEFAULT 0,                  -- if opinion split into chunks
    chunk_text      TEXT,
    embedding       vector(1536),                   -- OpenAI text-embedding-3-small dimension
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(opinion_id, model, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_opinion ON case_embeddings(opinion_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_vector ON case_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ============================================================
-- HELPFUL VIEWS
-- ============================================================

-- Quick stats per case type
CREATE OR REPLACE VIEW case_type_stats AS
SELECT
    case_type,
    COUNT(*) AS total_cases,
    COUNT(DISTINCT court) AS courts,
    MIN(date_filed) AS earliest,
    MAX(date_filed) AS latest,
    COUNT(*) FILTER (WHERE outcome ILIKE '%affirm%') AS affirmed,
    COUNT(*) FILTER (WHERE outcome ILIKE '%revers%') AS reversed,
    COUNT(*) FILTER (WHERE outcome ILIKE '%remand%') AS remanded
FROM case_opinions
GROUP BY case_type;

-- DWI-specific view with common fields
CREATE OR REPLACE VIEW dwi_cases AS
SELECT
    id, case_name, court, date_filed, docket_number,
    citations, outcome, judges, statutes_cited, summary,
    metadata->>'bac_level' AS bac_level,
    metadata->>'prior_offenses' AS prior_offenses,
    metadata->>'offense_level' AS offense_level
FROM case_opinions
WHERE case_type = 'dwi';
