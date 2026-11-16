-- Historique des changements de configuration des modeles (etape M3, D-64).
-- Niveau systeme : aucun utilisateur, aucun projet, aucun contenu de conversation, aucun
-- secret. Seuls des noms de fournisseur, de modele et d'effort. Ajout seul.
CREATE TABLE llm_config_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('coaching', 'strategy', 'simple')),
    provider_before TEXT,
    model_before TEXT,
    effort_before TEXT,
    provider_after TEXT NOT NULL,
    model_after TEXT NOT NULL,
    effort_after TEXT,
    catalog_version TEXT NOT NULL,
    fingerprint TEXT NOT NULL
);
CREATE INDEX idx_llm_config_events_role ON llm_config_events(role, id);
CREATE TRIGGER llm_config_events_no_update BEFORE UPDATE ON llm_config_events
BEGIN
    SELECT RAISE(ABORT, 'historique des modeles en ajout seul');
END;
CREATE TRIGGER llm_config_events_no_delete BEFORE DELETE ON llm_config_events
BEGIN
    SELECT RAISE(ABORT, 'historique des modeles en ajout seul');
END;
