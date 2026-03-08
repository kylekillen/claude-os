-- Claude OS v3 — Markdown Index Schema
-- This is the only database. Indexes markdown files for hybrid search.

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    section_header TEXT,
    chunk_text TEXT NOT NULL,
    file_mtime REAL,
    content_hash TEXT,
    embedding BLOB,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    domain TEXT DEFAULT 'general',
    feedback_boost REAL DEFAULT 1.0
);

CREATE INDEX idx_chunks_filepath ON chunks(file_path);
CREATE INDEX idx_chunks_hash ON chunks(content_hash);

CREATE TABLE search_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    query_domain TEXT,
    result_ids TEXT,
    result_count INTEGER,
    searched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- FTS5 for keyword search
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    chunk_id,
    section_header,
    chunk_text
);
