-- Refonte de l'interface (D-76) : profils locaux et projets ouverts depuis la conversation.
-- Le nom d'utilisateur identifie un espace local ; ce n'est PAS une authentification
-- (prototype local, R-SEC-01). Aucune donnee existante n'est supprimee.

ALTER TABLE users ADD COLUMN first_name TEXT;
ALTER TABLE users ADD COLUMN last_name TEXT;
ALTER TABLE users ADD COLUMN username TEXT;
-- Cle d'unicite : nom d'utilisateur sans espaces de bord, normalise (NFKC) et sans casse.
ALTER TABLE users ADD COLUMN username_key TEXT;
CREATE UNIQUE INDEX uq_users_username_key ON users(username_key) WHERE username_key IS NOT NULL;

-- Projet commence par la conversation : titre provisoire tant que l'utilisateur ne l'a pas
-- confirme (aucun titre n'est enregistre sans son clic).
ALTER TABLE projects ADD COLUMN title_pending INTEGER NOT NULL DEFAULT 0
    CHECK (title_pending IN (0, 1));

-- Espaces existants : un nom d'utilisateur pour pouvoir les rouvrir. Les deux espaces de
-- demonstration gardent un nom lisible ; tout autre espace recoit un nom derive de son
-- identifiant (unique par construction).
UPDATE users SET first_name = 'Alice', username = 'alice-demo', username_key = 'alice-demo'
    WHERE display_name = 'Alice (démo)' AND username IS NULL
    AND NOT EXISTS (SELECT 1 FROM users WHERE username_key = 'alice-demo');
UPDATE users SET first_name = 'Bruno', username = 'bruno-demo', username_key = 'bruno-demo'
    WHERE display_name = 'Bruno (démo)' AND username IS NULL
    AND NOT EXISTS (SELECT 1 FROM users WHERE username_key = 'bruno-demo');
UPDATE users SET username = 'espace-' || substr(id, 5, 8), username_key = 'espace-' || substr(id, 5, 8)
    WHERE username IS NULL;
