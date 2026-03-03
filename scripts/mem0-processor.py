#!/usr/bin/env python3
"""
Mem0-style memory processor for claude-mem.

Provides CLI operations for the memories table:
  --search "fact text"              Search for similar existing memories (FTS5 + semantic)
  --add "fact" --category "cat"     Insert a new memory
  --update ID --fact "new text"     Update an existing memory's fact text
  --delete ID                       Mark a memory as superseded (soft delete)
  --list                            List all active memories
  --stats                           Show memory statistics

The LLM work (fact extraction, decision-making) stays in the subagent.
This script handles only fast Python + SQLite operations.
"""

import sqlite3
import os
import sys
import json
import argparse
import time
try:
    import numpy as np
except ImportError:
    np = None
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
LOG_PATH = os.path.expanduser("~/.claude-mem/logs/mem0-processor.log")
MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# Lazy model
_model = None
_model_load_attempted = False


def log(msg):
    """Append to log file."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def get_model():
    """Lazy-load sentence transformer for embeddings."""
    global _model, _model_load_attempted
    if _model_load_attempted:
        return _model
    _model_load_attempted = True
    try:
        # Suppress stdout pollution from model loading
        old_fd = os.dup(1)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.close(devnull)
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(MODEL_NAME)
        finally:
            os.dup2(old_fd, 1)
            os.close(old_fd)
        return _model
    except Exception as e:
        log(f"Model load failed: {e}")
        return None


def embed_text(text):
    """Generate embedding for a text string. Returns bytes or None."""
    model = get_model()
    if model is None:
        return None
    emb = model.encode([text], normalize_embeddings=True)[0]
    return emb.astype(np.float32).tobytes()


def decode_embedding(blob):
    """Unpack BLOB into numpy array."""
    if blob is None:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def get_db():
    """Open database connection."""
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    return db


# ── FTS5 search ──────────────────────────────────────────────────

STOPWORDS = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
             'of', 'to', 'in', 'for', 'on', 'at', 'by', 'with', 'from',
             'it', 'its', 'that', 'this', 'do', 'did', 'does', 'what',
             'how', 'when', 'where', 'why', 'who', 'which', 'can', 'we',
             'i', 'my', 'our', 'you', 'your', 'me', 'us', 'and', 'or', 'not',
             'has', 'have', 'had', 'will', 'would', 'could', 'should', 'may'}


def search_fts(db, query, limit=10):
    """FTS5 keyword search on memories_fts. Returns [(id, score), ...]."""
    terms = [t for t in query.split() if len(t) > 1 and t.lower() not in STOPWORDS]
    if not terms:
        return []

    safe_query = " OR ".join(f'"{t}"' for t in terms[:10])
    try:
        rows = db.execute("""
            SELECT m.id, fts.rank
            FROM memories_fts fts
            JOIN memories m ON m.rowid = fts.rowid
            WHERE memories_fts MATCH ?
              AND m.is_active = 1
            ORDER BY fts.rank
            LIMIT ?
        """, (safe_query, limit)).fetchall()
    except Exception:
        return []

    if not rows:
        return []

    ranks = [abs(r[1]) for r in rows]
    max_rank = max(ranks) if ranks else 1
    return [(r[0], 1.0 - (abs(r[1]) / max_rank) if max_rank > 0 else 0) for r in rows]


def search_semantic(db, query, limit=10):
    """Semantic cosine similarity search on memories. Returns [(id, score), ...]."""
    model = get_model()
    if model is None:
        return []

    query_emb = model.encode([query], normalize_embeddings=True)[0]

    rows = db.execute("""
        SELECT id, embedding FROM memories
        WHERE embedding IS NOT NULL AND is_active = 1
    """).fetchall()

    scores = []
    for mem_id, emb_blob in rows:
        emb = decode_embedding(emb_blob)
        if emb is not None and len(emb) == EMBEDDING_DIM:
            sim = float(np.dot(query_emb, emb))
            scores.append((mem_id, sim))

    scores.sort(key=lambda x: -x[1])
    top = scores[:limit]

    if not top:
        return []

    max_sim = top[0][1]
    min_sim = top[-1][1] if len(top) > 1 else 0
    spread = max_sim - min_sim if max_sim != min_sim else 1

    return [(mid, (sim - min_sim) / spread) for mid, sim in top]


def search_memories(db, query, limit=5, fts_only=False):
    """Combined FTS5 + semantic search. Returns JSON-friendly results."""
    fts_results = search_fts(db, query, limit=limit * 3)

    if fts_only:
        sem_results = []
    else:
        sem_results = search_semantic(db, query, limit=limit * 3)

    fts_map = dict(fts_results)
    sem_map = dict(sem_results)

    all_ids = set(fts_map.keys()) | set(sem_map.keys())
    combined = []
    for mid in all_ids:
        fts_score = fts_map.get(mid, 0)
        sem_score = sem_map.get(mid, 0)
        hybrid = 0.4 * fts_score + 0.6 * sem_score
        combined.append((mid, hybrid))

    combined.sort(key=lambda x: -x[1])
    top_ids = [c[0] for c in combined[:limit]]

    if not top_ids:
        return []

    placeholders = ",".join("?" * len(top_ids))
    rows = db.execute(f"""
        SELECT id, fact, category, created_at_epoch, updated_at_epoch
        FROM memories
        WHERE id IN ({placeholders}) AND is_active = 1
    """, top_ids).fetchall()

    mem_map = {r[0]: r for r in rows}
    score_map = dict(combined)

    results = []
    for mid in top_ids:
        if mid in mem_map:
            r = mem_map[mid]
            results.append({
                "id": r[0],
                "fact": r[1],
                "category": r[2],
                "score": round(score_map.get(mid, 0), 3),
                "created_at_epoch": r[3],
                "updated_at_epoch": r[4]
            })

    return results


# ── CRUD operations ──────────────────────────────────────────────

def add_memory(db, fact, category=None, source_session=None, skip_embed=False):
    """Insert a new memory. Returns the new memory ID."""
    now_ms = int(time.time() * 1000)
    emb = None if skip_embed else embed_text(fact)

    cursor = db.execute("""
        INSERT INTO memories (fact, category, source_session,
                              created_at_epoch, updated_at_epoch, embedding)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (fact, category, source_session, now_ms, now_ms, emb))

    db.commit()
    mem_id = cursor.lastrowid
    log(f"ADD memory #{mem_id}: {fact[:80]}")
    return mem_id


def update_memory(db, memory_id, new_fact, category=None, skip_embed=False):
    """Update an existing memory's fact text. Optionally re-embeds."""
    now_ms = int(time.time() * 1000)
    emb = None if skip_embed else embed_text(new_fact)

    updates = ["fact = ?", "updated_at_epoch = ?"]
    params = [new_fact, now_ms]

    if emb is not None:
        updates.append("embedding = ?")
        params.append(emb)

    if category is not None:
        updates.append("category = ?")
        params.append(category)

    params.append(memory_id)
    db.execute(f"""
        UPDATE memories SET {', '.join(updates)}
        WHERE id = ?
    """, params)

    db.commit()
    log(f"UPDATE memory #{memory_id}: {new_fact[:80]}")


def delete_memory(db, memory_id, superseded_by=None):
    """Soft-delete a memory by marking it inactive."""
    now_ms = int(time.time() * 1000)
    db.execute("""
        UPDATE memories SET is_active = 0, superseded_by = ?, updated_at_epoch = ?
        WHERE id = ?
    """, (superseded_by, now_ms, memory_id))

    db.commit()
    log(f"DELETE memory #{memory_id} (superseded_by={superseded_by})")


def list_memories(db, include_inactive=False):
    """List all memories."""
    where = "" if include_inactive else "WHERE is_active = 1"
    rows = db.execute(f"""
        SELECT id, fact, category, is_active, created_at_epoch, updated_at_epoch,
               access_count
        FROM memories
        {where}
        ORDER BY updated_at_epoch DESC
    """).fetchall()

    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "fact": r[1],
            "category": r[2],
            "is_active": bool(r[3]),
            "created_at_epoch": r[4],
            "updated_at_epoch": r[5],
            "access_count": r[6]
        })
    return results


def stats(db):
    """Return memory statistics."""
    total = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    active = db.execute("SELECT COUNT(*) FROM memories WHERE is_active = 1").fetchone()[0]
    inactive = total - active
    embedded = db.execute(
        "SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL AND is_active = 1"
    ).fetchone()[0]

    cats = db.execute("""
        SELECT category, COUNT(*) FROM memories
        WHERE is_active = 1
        GROUP BY category ORDER BY COUNT(*) DESC
    """).fetchall()

    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "embedded": embedded,
        "categories": {c[0] or "uncategorized": c[1] for c in cats}
    }


def embed_unembedded(db):
    """Embed any memories that don't have embeddings yet."""
    rows = db.execute("""
        SELECT id, fact FROM memories
        WHERE embedding IS NULL AND is_active = 1
    """).fetchall()

    if not rows:
        return 0

    count = 0
    for mem_id, fact in rows:
        emb = embed_text(fact)
        if emb:
            db.execute("UPDATE memories SET embedding = ? WHERE id = ?", (emb, mem_id))
            count += 1

    db.commit()
    log(f"Embedded {count} memories")
    return count


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mem0-style memory processor")

    # Operations
    parser.add_argument("--search", type=str, help="Search for similar memories")
    parser.add_argument("--add", type=str, help="Add a new memory fact")
    parser.add_argument("--update", type=int, help="Update memory by ID")
    parser.add_argument("--delete", type=int, help="Delete (soft) memory by ID")
    parser.add_argument("--list", action="store_true", help="List all active memories")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--embed-all", action="store_true", help="Embed unembedded memories")

    # Parameters
    parser.add_argument("--fact", type=str, help="New fact text (for --update)")
    parser.add_argument("--category", type=str, help="Category (for --add or --update)")
    parser.add_argument("--session", type=str, help="Source session ID (for --add)")
    parser.add_argument("--superseded-by", type=str, help="ID that supersedes (for --delete)")
    parser.add_argument("--limit", type=int, default=5, help="Max results for --search")
    parser.add_argument("--include-inactive", action="store_true", help="Include inactive in --list")
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding (faster, embed later via --embed-all)")
    parser.add_argument("--fts-only", action="store_true", help="FTS-only search (no model loading, much faster)")

    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(json.dumps({"error": "Database not found"}))
        sys.exit(1)

    db = get_db()

    try:
        if args.search:
            results = search_memories(db, args.search, limit=args.limit,
                                      fts_only=args.fts_only)
            print(json.dumps(results, indent=2))

        elif args.add:
            mem_id = add_memory(db, args.add, category=args.category,
                                source_session=args.session,
                                skip_embed=args.no_embed)
            print(json.dumps({"status": "added", "id": mem_id, "fact": args.add}))

        elif args.update is not None:
            if not args.fact:
                print(json.dumps({"error": "--update requires --fact"}))
                sys.exit(1)
            update_memory(db, args.update, args.fact, category=args.category,
                            skip_embed=args.no_embed)
            print(json.dumps({"status": "updated", "id": args.update, "fact": args.fact}))

        elif args.delete is not None:
            delete_memory(db, args.delete, superseded_by=args.superseded_by)
            print(json.dumps({"status": "deleted", "id": args.delete}))

        elif args.list:
            memories = list_memories(db, include_inactive=args.include_inactive)
            print(json.dumps(memories, indent=2))

        elif args.stats:
            s = stats(db)
            print(json.dumps(s, indent=2))

        elif args.embed_all:
            count = embed_unembedded(db)
            print(json.dumps({"status": "embedded", "count": count}))

        else:
            parser.print_help()

    finally:
        db.close()


if __name__ == '__main__':
    main()
