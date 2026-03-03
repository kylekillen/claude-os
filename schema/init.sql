-- Claude OS Memory Database Schema
-- Initialize a fresh claude-mem.db with all tables, indexes, FTS5, and triggers.

CREATE TABLE IF NOT EXISTS schema_versions (
    id INTEGER PRIMARY KEY,
    version INTEGER UNIQUE NOT NULL,
    applied_at TEXT NOT NULL
);

INSERT INTO schema_versions (version, applied_at) VALUES (1, datetime('now'));

CREATE TABLE IF NOT EXISTS sdk_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_session_id TEXT UNIQUE NOT NULL,
    memory_session_id TEXT UNIQUE,
    project TEXT NOT NULL,
    user_prompt TEXT,
    started_at TEXT NOT NULL,
    started_at_epoch INTEGER NOT NULL,
    completed_at TEXT,
    completed_at_epoch INTEGER,
    status TEXT CHECK(status IN ('active', 'completed', 'failed')) NOT NULL DEFAULT 'active',
    worker_port INTEGER,
    prompt_counter INTEGER DEFAULT 0
);

CREATE INDEX idx_sdk_sessions_claude_id ON sdk_sessions(content_session_id);
CREATE INDEX idx_sdk_sessions_sdk_id ON sdk_sessions(memory_session_id);
CREATE INDEX idx_sdk_sessions_project ON sdk_sessions(project);
CREATE INDEX idx_sdk_sessions_status ON sdk_sessions(status);
CREATE INDEX idx_sdk_sessions_started ON sdk_sessions(started_at_epoch DESC);

CREATE TABLE IF NOT EXISTS session_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    request TEXT,
    investigated TEXT,
    learned TEXT,
    completed TEXT,
    next_steps TEXT,
    files_read TEXT,
    files_edited TEXT,
    notes TEXT,
    prompt_number INTEGER,
    created_at TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL,
    discovery_tokens INTEGER DEFAULT 0,
    FOREIGN KEY(memory_session_id) REFERENCES sdk_sessions(memory_session_id) ON DELETE CASCADE
);

CREATE INDEX idx_session_summaries_sdk_session ON session_summaries(memory_session_id);
CREATE INDEX idx_session_summaries_project ON session_summaries(project);
CREATE INDEX idx_session_summaries_created ON session_summaries(created_at_epoch DESC);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    text TEXT,
    type TEXT NOT NULL CHECK(type IN ('decision', 'bugfix', 'feature', 'refactor', 'discovery', 'change')),
    title TEXT,
    subtitle TEXT,
    facts TEXT,
    narrative TEXT,
    concepts TEXT,
    files_read TEXT,
    files_modified TEXT,
    prompt_number INTEGER,
    created_at TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL,
    discovery_tokens INTEGER DEFAULT 0,
    attention_score REAL DEFAULT 1.0,
    last_accessed_epoch INTEGER,
    access_count INTEGER DEFAULT 0,
    valid_until_epoch INTEGER,
    validity_class TEXT DEFAULT 'permanent',
    embedding BLOB DEFAULT NULL,
    content_hash TEXT,
    supersedes_id TEXT,
    updated_at_epoch INTEGER,
    FOREIGN KEY(memory_session_id) REFERENCES sdk_sessions(memory_session_id) ON DELETE CASCADE
);

CREATE INDEX idx_observations_sdk_session ON observations(memory_session_id);
CREATE INDEX idx_observations_project ON observations(project);
CREATE INDEX idx_observations_type ON observations(type);
CREATE INDEX idx_observations_created ON observations(created_at_epoch DESC);
CREATE INDEX idx_observations_attention ON observations(attention_score DESC);
CREATE INDEX idx_observations_validity ON observations(valid_until_epoch);

CREATE TABLE IF NOT EXISTS user_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_session_id TEXT NOT NULL,
    prompt_number INTEGER NOT NULL,
    prompt_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL,
    FOREIGN KEY(content_session_id) REFERENCES sdk_sessions(content_session_id) ON DELETE CASCADE
);

CREATE INDEX idx_user_prompts_claude_session ON user_prompts(content_session_id);
CREATE INDEX idx_user_prompts_created ON user_prompts(created_at_epoch DESC);
CREATE INDEX idx_user_prompts_prompt_number ON user_prompts(prompt_number);
CREATE INDEX idx_user_prompts_lookup ON user_prompts(content_session_id, prompt_number);

CREATE TABLE IF NOT EXISTS pending_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_db_id INTEGER NOT NULL,
    content_session_id TEXT NOT NULL,
    message_type TEXT NOT NULL CHECK(message_type IN ('observation', 'summarize')),
    tool_name TEXT,
    tool_input TEXT,
    tool_response TEXT,
    cwd TEXT,
    last_user_message TEXT,
    last_assistant_message TEXT,
    prompt_number INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'processed', 'failed')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at_epoch INTEGER NOT NULL,
    started_processing_at_epoch INTEGER,
    completed_at_epoch INTEGER,
    failed_at_epoch INTEGER,
    FOREIGN KEY (session_db_id) REFERENCES sdk_sessions(id) ON DELETE CASCADE
);

CREATE INDEX idx_pending_messages_session ON pending_messages(session_db_id);
CREATE INDEX idx_pending_messages_status ON pending_messages(status);
CREATE INDEX idx_pending_messages_claude_session ON pending_messages(content_session_id);

-- Memories (Mem0-style knowledge facts)
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT NOT NULL,
    category TEXT,
    source_session TEXT,
    created_at_epoch INTEGER,
    updated_at_epoch INTEGER,
    embedding BLOB,
    access_count INTEGER DEFAULT 0,
    last_accessed_epoch INTEGER,
    superseded_by TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE INDEX idx_memories_active ON memories(is_active);
CREATE INDEX idx_memories_category ON memories(category);
CREATE INDEX idx_memories_created ON memories(created_at_epoch DESC);

-- Entity graph
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT,
    aliases TEXT,
    summary TEXT,
    first_seen_epoch INTEGER,
    last_seen_epoch INTEGER,
    observation_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS observation_entities (
    observation_id TEXT,
    entity_id TEXT,
    role TEXT,
    PRIMARY KEY (observation_id, entity_id)
);

CREATE INDEX idx_entity_name ON entities(name);
CREATE INDEX idx_entity_type ON entities(entity_type);
CREATE INDEX idx_obs_entity ON observation_entities(entity_id);

-- Self-improvement tracking
CREATE TABLE IF NOT EXISTS improvement_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    target_files TEXT,
    expected_benchmarks TEXT,
    implementation_hint TEXT,
    feasibility_score REAL,
    impact_score REAL,
    agent_track_score REAL,
    combined_score REAL,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    evaluated_at TEXT,
    implemented_at TEXT,
    rejection_reason TEXT,
    failure_reason TEXT,
    benchmark_before TEXT,
    benchmark_after TEXT,
    benchmark_delta TEXT,
    git_branch TEXT
);

CREATE TABLE IF NOT EXISTS agent_track_records (
    agent_name TEXT PRIMARY KEY,
    total_suggestions INTEGER DEFAULT 0,
    approved INTEGER DEFAULT 0,
    implemented INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    rolling_score REAL DEFAULT 0.5,
    last_suggestion_at TEXT,
    best_improvement TEXT
);

-- ════════════════════════════════════════════════
-- FTS5 Full-Text Search Virtual Tables + Triggers
-- ════════════════════════════════════════════════

-- Observations FTS
CREATE VIRTUAL TABLE observations_fts USING fts5(
    title, subtitle, narrative, text, facts, concepts,
    content='observations', content_rowid='id'
);

CREATE TRIGGER observations_ai AFTER INSERT ON observations BEGIN
    INSERT INTO observations_fts(rowid, title, subtitle, narrative, text, facts, concepts)
    VALUES (new.id, new.title, new.subtitle, new.narrative, new.text, new.facts, new.concepts);
END;

CREATE TRIGGER observations_ad AFTER DELETE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, title, subtitle, narrative, text, facts, concepts)
    VALUES('delete', old.id, old.title, old.subtitle, old.narrative, old.text, old.facts, old.concepts);
END;

CREATE TRIGGER observations_au AFTER UPDATE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, title, subtitle, narrative, text, facts, concepts)
    VALUES('delete', old.id, old.title, old.subtitle, old.narrative, old.text, old.facts, old.concepts);
    INSERT INTO observations_fts(rowid, title, subtitle, narrative, text, facts, concepts)
    VALUES (new.id, new.title, new.subtitle, new.narrative, new.text, new.facts, new.concepts);
END;

-- User Prompts FTS
CREATE VIRTUAL TABLE user_prompts_fts USING fts5(
    prompt_text, content='user_prompts', content_rowid='id'
);

CREATE TRIGGER user_prompts_ai AFTER INSERT ON user_prompts BEGIN
    INSERT INTO user_prompts_fts(rowid, prompt_text)
    VALUES (new.id, new.prompt_text);
END;

CREATE TRIGGER user_prompts_ad AFTER DELETE ON user_prompts BEGIN
    INSERT INTO user_prompts_fts(user_prompts_fts, rowid, prompt_text)
    VALUES('delete', old.id, old.prompt_text);
END;

CREATE TRIGGER user_prompts_au AFTER UPDATE ON user_prompts BEGIN
    INSERT INTO user_prompts_fts(user_prompts_fts, rowid, prompt_text)
    VALUES('delete', old.id, old.prompt_text);
    INSERT INTO user_prompts_fts(rowid, prompt_text)
    VALUES (new.id, new.prompt_text);
END;

-- Session Summaries FTS
CREATE VIRTUAL TABLE session_summaries_fts USING fts5(
    request, investigated, learned, completed, next_steps, notes,
    content='session_summaries', content_rowid='id'
);

CREATE TRIGGER session_summaries_ai AFTER INSERT ON session_summaries BEGIN
    INSERT INTO session_summaries_fts(rowid, request, investigated, learned, completed, next_steps, notes)
    VALUES (new.id, new.request, new.investigated, new.learned, new.completed, new.next_steps, new.notes);
END;

CREATE TRIGGER session_summaries_ad AFTER DELETE ON session_summaries BEGIN
    INSERT INTO session_summaries_fts(session_summaries_fts, rowid, request, investigated, learned, completed, next_steps, notes)
    VALUES('delete', old.id, old.request, old.investigated, old.learned, old.completed, old.next_steps, old.notes);
END;

CREATE TRIGGER session_summaries_au AFTER UPDATE ON session_summaries BEGIN
    INSERT INTO session_summaries_fts(session_summaries_fts, rowid, request, investigated, learned, completed, next_steps, notes)
    VALUES('delete', old.id, old.request, old.investigated, old.learned, old.completed, old.next_steps, old.notes);
    INSERT INTO session_summaries_fts(rowid, request, investigated, learned, completed, next_steps, notes)
    VALUES (new.id, new.request, new.investigated, new.learned, new.completed, new.next_steps, new.notes);
END;

-- Memories FTS
CREATE VIRTUAL TABLE memories_fts USING fts5(
    fact, content='memories', content_rowid='id'
);

CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, fact) VALUES (new.id, new.fact);
END;

CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, fact) VALUES('delete', old.id, old.fact);
END;

CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, fact) VALUES('delete', old.id, old.fact);
    INSERT INTO memories_fts(rowid, fact) VALUES (new.id, new.fact);
END;
