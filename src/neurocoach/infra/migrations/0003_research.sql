-- Business Researcher, R1 (D-68) : missions de recherche, requetes, sources et constats.
-- Isolation par user_id (cascade a l'effacement de l'utilisateur). Une mission concerne
-- un ou plusieurs projets ; supprimer l'un d'eux supprime la mission et tout ce qu'elle a
-- collecte (minimisation : aucune donnee de recherche orpheline).
-- Une recherche n'ecrit jamais dans projects, phases ni tasks.
CREATE TABLE research_missions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (
        status IN ('proposed', 'approved', 'completed', 'partial', 'cancelled', 'expired',
                   'superseded')
    ),
    scope_json TEXT NOT NULL,
    brief_json TEXT NOT NULL,
    planned_json TEXT NOT NULL,
    preview_json TEXT NOT NULL,
    scope_hash TEXT NOT NULL,
    simulated INTEGER NOT NULL CHECK (simulated IN (0, 1)),
    parent_mission_id TEXT REFERENCES research_missions(id) ON DELETE SET NULL,
    spent_usd REAL NOT NULL DEFAULT 0 CHECK (spent_usd >= 0),
    queries_used INTEGER NOT NULL DEFAULT 0 CHECK (queries_used >= 0),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,          -- limite pour approuver la proposition
    approved_at TEXT,
    valid_until TEXT,                  -- fin de l'autorisation une fois approuvee
    decided_at TEXT,
    finished_at TEXT
);
CREATE INDEX idx_research_missions_user ON research_missions(user_id, created_at);

CREATE TABLE research_mission_projects (
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (mission_id, project_id)
);
CREATE INDEX idx_research_mission_projects_project ON research_mission_projects(project_id);
-- Projet supprime : la mission entiere disparait (requetes, sources, constats en cascade).
CREATE TRIGGER research_mission_project_removed AFTER DELETE ON research_mission_projects
BEGIN
    DELETE FROM research_missions WHERE id = OLD.mission_id;
END;

CREATE TABLE research_queries (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL,
    category TEXT NOT NULL,
    provider TEXT NOT NULL,
    market TEXT,
    text TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('done', 'failed')),
    estimated_cost_usd REAL NOT NULL CHECK (estimated_cost_usd >= 0),
    result_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    simulated INTEGER NOT NULL CHECK (simulated IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_research_queries_mission ON research_queries(mission_id, created_at);

CREATE TABLE research_sources (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    query_id TEXT NOT NULL REFERENCES research_queries(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    provider TEXT NOT NULL,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL CHECK (length(excerpt) <= 500),
    published_date TEXT,
    retrieved_at TEXT NOT NULL,
    market TEXT,
    content_hash TEXT NOT NULL,
    suspicious INTEGER NOT NULL CHECK (suspicious IN (0, 1)),
    simulated INTEGER NOT NULL CHECK (simulated IN (0, 1))
);
CREATE INDEX idx_research_sources_mission ON research_sources(mission_id);

CREATE TABLE research_findings (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    statement TEXT NOT NULL,
    nature TEXT NOT NULL CHECK (nature IN ('fait', 'estimation', 'hypothese')),
    proposed_nature TEXT NOT NULL,
    quotes_json TEXT NOT NULL,
    confidence TEXT NOT NULL,
    flags_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_research_findings_mission ON research_findings(mission_id);

CREATE TABLE research_finding_sources (
    finding_id TEXT NOT NULL REFERENCES research_findings(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
    PRIMARY KEY (finding_id, source_id)
);
