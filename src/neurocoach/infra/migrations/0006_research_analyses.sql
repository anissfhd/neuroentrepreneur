-- Business Researcher, R4 (D-71) : analyses validees des missions de recherche.
-- Une analyse ne contient que ce que le code a valide contre les sources stockees ; elle
-- disparait avec sa mission (projet ou donnees supprimes).
CREATE TABLE research_analyses (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    sources_hash TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    analysis_json TEXT NOT NULL
);
CREATE INDEX idx_research_analyses_mission ON research_analyses(mission_id, created_at);
