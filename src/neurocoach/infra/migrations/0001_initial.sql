-- Schema initial de la base metier (DOMAIN_CONTRACTS section 1).
-- Horodatages : texte ISO 8601 UTC ; echeances : texte AAAA-MM-JJ.

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE preferences (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    response_length TEXT NOT NULL CHECK (response_length IN ('court', 'standard', 'detaille')),
    max_visible_tasks INTEGER NOT NULL CHECK (max_visible_tasks BETWEEN 1 AND 3),
    one_question_at_a_time INTEGER NOT NULL CHECK (one_question_at_a_time IN (0, 1)),
    deadlines_enabled INTEGER NOT NULL CHECK (deadlines_enabled IN (0, 1)),
    cadence TEXT NOT NULL CHECK (cadence IN ('flexible', 'quotidienne', 'hebdomadaire')),
    display_timezone TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    idea TEXT NOT NULL DEFAULT '',
    target_outcome TEXT,
    constraints_json TEXT NOT NULL DEFAULT '[]',
    facts_json TEXT NOT NULL DEFAULT '[]',
    assumptions_json TEXT NOT NULL DEFAULT '[]',
    available_minutes_per_day INTEGER,
    horizon_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('draft', 'active')),
    next_task_number INTEGER NOT NULL CHECK (next_task_number >= 1),
    version INTEGER NOT NULL CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_projects_user ON projects(user_id);

CREATE TABLE phases (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    exit_criterion TEXT,
    position INTEGER NOT NULL CHECK (position >= 0)
);
CREATE INDEX idx_phases_project ON phases(project_id);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase_id TEXT NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    number INTEGER NOT NULL CHECK (number >= 1),
    title TEXT NOT NULL,
    description TEXT,
    acceptance_criteria TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'blocked', 'done')),
    blocked_reason TEXT,
    priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
    estimate_minutes INTEGER,
    due_date TEXT,
    position INTEGER NOT NULL CHECK (position >= 0),
    completed_at TEXT,
    version INTEGER NOT NULL CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, number),
    CHECK ((status = 'done') = (completed_at IS NOT NULL)),
    CHECK ((status = 'blocked') = (blocked_reason IS NOT NULL))
);
CREATE INDEX idx_tasks_project ON tasks(project_id);
CREATE INDEX idx_tasks_phase ON tasks(phase_id);

CREATE TABLE task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, depends_on_task_id),
    CHECK (task_id <> depends_on_task_id)
);
CREATE INDEX idx_dependencies_target ON task_dependencies(depends_on_task_id);

CREATE TABLE pending_actions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- SET NULL : l'action qui supprime un projet garde sa trace apres la suppression.
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    action_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    preview_json TEXT NOT NULL,
    expected_versions_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'applied', 'cancelled', 'expired', 'superseded', 'failed')
    ),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT,
    result_json TEXT
);
-- I-12 : au plus une action en attente par couple (utilisateur, projet).
CREATE UNIQUE INDEX uq_one_pending_action
    ON pending_actions(user_id, COALESCE(project_id, ''))
    WHERE status = 'pending';

CREATE TABLE activity_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    pending_action_id TEXT REFERENCES pending_actions(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    reverts_event_id TEXT REFERENCES activity_events(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_events_user ON activity_events(user_id);
CREATE INDEX idx_events_task ON activity_events(task_id);

CREATE TABLE conversation_threads (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, project_id)
);
