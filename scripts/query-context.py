#!/usr/bin/env python3
"""
Query-aware context injection for Memory v3 (markdown-first).

Runs on UserPromptSubmit hook. Reads the user's prompt, searches the
markdown index for semantically relevant content, and outputs context
that gets injected into the conversation.

Replaces the v2 version that searched SQLite observations/memories tables.
Now searches markdown files via markdown-search.py's index.

Input (stdin): {"prompt": "...", "session_id": "...", ...}
Output (stdout): Markdown-formatted relevant context (injected as system-reminder)
"""

import json
import sys
import os
import sqlite3
import time
import numpy as np
from datetime import datetime

# Markdown search index (built by markdown-search.py --index)
MD_DB_PATH = os.path.expanduser("~/.claude-mem/markdown-index.db")
LOG_PATH = os.path.expanduser("~/.claude-mem/logs/query-context.log")

# Search config
MAX_RESULTS = 15
MIN_QUERY_LENGTH = 15
FTS_WEIGHT = 0.4
SEMANTIC_WEIGHT = 0.6
SCORE_THRESHOLD = 0.10
EMBEDDING_DIM = 384

# Stopwords
stopwords = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
             'of', 'to', 'in', 'for', 'on', 'at', 'by', 'with', 'from',
             'it', 'its', 'that', 'this', 'do', 'did', 'does', 'what',
             'how', 'when', 'where', 'why', 'who', 'which', 'can', 'we',
             'i', 'my', 'our', 'you', 'your', 'me', 'us', 'and', 'or', 'not'}

# Lazy model
_model = None
_model_load_attempted = False

# Display paths
PERSONAL_OS = os.environ.get("CLAUDE_OS_PROJECT_ROOT", "")
if not PERSONAL_OS:
    PERSONAL_OS = ""
elif not PERSONAL_OS.endswith("/"):
    PERSONAL_OS += "/"

# Auto-detect memory directory by globbing ~/.claude/projects/*/memory/
import glob as _glob
_memory_matches = _glob.glob(os.path.expanduser("~/.claude/projects/*/memory/"))
AUTO_MEMORY = _memory_matches[0] if _memory_matches else ""


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def get_model():
    global _model, _model_load_attempted
    if _model_load_attempted:
        return _model
    _model_load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer
        old_fd = os.dup(1)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.close(devnull)
        try:
            _model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        finally:
            os.dup2(old_fd, 1)
            os.close(old_fd)
        return _model
    except Exception as e:
        log(f"Model load failed: {e}")
        return None


def search_fts(db, query, limit=60):
    terms = [t for t in query.split() if len(t) > 1 and t.lower() not in stopwords]
    if not terms:
        return {}

    safe_query = " OR ".join(f'"{t}"' for t in terms[:10])
    try:
        rows = db.execute("""
            SELECT CAST(fts.chunk_id AS INTEGER), fts.rank
            FROM chunks_fts fts
            WHERE chunks_fts MATCH ?
            ORDER BY fts.rank
            LIMIT ?
        """, (safe_query, limit)).fetchall()
    except Exception:
        return {}

    if not rows:
        return {}

    ranks = [abs(r[1]) for r in rows]
    max_rank = max(ranks) if ranks else 1
    return {r[0]: 1.0 - (abs(r[1]) / max_rank) if max_rank > 0 else 0 for r in rows}


def search_semantic(db, model, query, limit=60):
    if model is None:
        return {}

    query_emb = model.encode([query], normalize_embeddings=True)[0]

    rows = db.execute("""
        SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL
    """).fetchall()

    scores = []
    for cid, emb_blob in rows:
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        if len(emb) == EMBEDDING_DIM:
            sim = float(np.dot(query_emb, emb))
            scores.append((cid, sim))

    scores.sort(key=lambda x: -x[1])
    top = scores[:limit]

    if not top:
        return {}

    max_sim = top[0][1]
    min_sim = top[-1][1] if len(top) > 1 else 0
    spread = max_sim - min_sim if max_sim != min_sim else 1
    return {cid: (sim - min_sim) / spread for cid, sim in top}


def hybrid_search(db, model, query, limit=15):
    fts_scores = search_fts(db, query, limit=limit * 3)
    sem_scores = search_semantic(db, model, query, limit=limit * 3)

    all_ids = set(fts_scores.keys()) | set(sem_scores.keys())
    combined = []

    for cid in all_ids:
        fts = fts_scores.get(cid, 0)
        sem = sem_scores.get(cid, 0)
        score = FTS_WEIGHT * fts + SEMANTIC_WEIGHT * sem
        if score >= SCORE_THRESHOLD:
            combined.append((cid, score))

    combined.sort(key=lambda x: -x[1])
    return combined[:limit]


def format_results(db, results):
    if not results:
        return ""

    ids = [r[0] for r in results]
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"""
        SELECT id, file_path, section_header, chunk_text
        FROM chunks WHERE id IN ({placeholders})
    """, ids).fetchall()

    chunk_map = {r[0]: r for r in rows}

    lines = ["# Relevant Context (markdown search)\n"]

    for cid, score in results:
        chunk = chunk_map.get(cid)
        if not chunk:
            continue

        _, fpath, header, text = chunk

        # Make path relative for display
        rel_path = fpath
        for prefix in [PERSONAL_OS, AUTO_MEMORY]:
            if fpath.startswith(prefix):
                rel_path = fpath[len(prefix):]
                break

        # Truncate text for injection
        display_text = text[:500]
        if len(text) > 500:
            display_text += "..."

        lines.append(f"**[{rel_path}] {header}** (score: {score:.2f})")
        lines.append(f"{display_text}\n")

    return "\n".join(lines)


def should_search(prompt):
    if not prompt or len(prompt.strip()) < MIN_QUERY_LENGTH:
        return False

    lower = prompt.strip().lower()
    skip_patterns = [
        'good morning', 'morning routine', 'start the day',
        'yes', 'no', 'ok', 'sure', 'thanks', 'thank you',
        'continue', 'go ahead', 'proceed', 'do it',
        '/commit', '/help', '/clear',
    ]
    for pat in skip_patterns:
        if lower == pat or lower.startswith(pat + ' ') and len(lower) < 30:
            return False

    return True


def main():
    t0 = time.time()

    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    prompt = input_data.get('prompt', '')

    if not should_search(prompt):
        log(f"Skip (too short/greeting): {prompt[:50]}")
        sys.exit(0)

    if not os.path.exists(MD_DB_PATH):
        log("No markdown index found")
        sys.exit(0)

    db = sqlite3.connect(MD_DB_PATH, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")

    model = get_model()

    results = hybrid_search(db, model, prompt, limit=MAX_RESULTS)

    elapsed = time.time() - t0

    if not results:
        log(f"No results for: {prompt[:80]} ({elapsed:.1f}s)")
        db.close()
        sys.exit(0)

    context = format_results(db, results)
    db.close()

    log(f"Injected {len(results)} markdown chunks for: {prompt[:80]} ({elapsed:.1f}s)")

    print(context)
    sys.exit(0)


if __name__ == '__main__':
    main()
