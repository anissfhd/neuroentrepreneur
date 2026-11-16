-- Business Researcher, R6 (D-73) : solutions validees d'une mission de solutions.
-- Supprimees avec leur mission (projet ou donnees supprimes).
CREATE TABLE research_solutions (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    sources_hash TEXT NOT NULL,
    plan_json TEXT NOT NULL
);
CREATE INDEX idx_research_solutions_mission ON research_solutions(mission_id, created_at);
