-- D-85 : mise en pause reelle d'un projet (simulation 6 validee du dossier V1).
-- Deux colonnes facultatives : aucun projet existant n'est modifie, aucune table n'est
-- reconstruite. Un projet en pause garde son statut, son plan, ses taches et sa conversation.
ALTER TABLE projects ADD COLUMN paused_at TEXT;
ALTER TABLE projects ADD COLUMN pause_note TEXT;
