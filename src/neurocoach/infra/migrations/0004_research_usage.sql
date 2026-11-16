-- Business Researcher, R2 (D-69) : cout reel des requetes et garde des quotas gratuits.
-- research_provider_usage est un compteur SYSTEME (aucun utilisateur, aucun contenu) :
-- il survit a l'effacement des donnees d'un utilisateur, pour que le quota reste exact.
ALTER TABLE research_queries ADD COLUMN actual_cost_usd REAL CHECK (actual_cost_usd >= 0);
ALTER TABLE research_queries ADD COLUMN error_kind TEXT;

CREATE TABLE research_provider_usage (
    provider TEXT NOT NULL,
    period TEXT NOT NULL,                      -- mois civil UTC, par exemple 2026-11
    reserved_usd REAL NOT NULL DEFAULT 0 CHECK (reserved_usd >= 0),
    queries INTEGER NOT NULL DEFAULT 0 CHECK (queries >= 0),
    exhausted INTEGER NOT NULL DEFAULT 0 CHECK (exhausted IN (0, 1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, period)
);
