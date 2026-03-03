#!/usr/bin/env python3
"""
Query-aware context injection for claude-mem.

Runs on UserPromptSubmit hook. Reads the user's prompt, searches the
observation database for semantically relevant memories, and outputs
them as context that gets injected into the conversation.

This is the fix for the "50 most recent, regardless of relevance" problem.
Instead of blind recency-based injection, we search for observations that
actually match what the user is asking about.

Input (stdin): {"prompt": "...", "session_id": "...", ...}
Output (stdout): Markdown-formatted relevant observations (injected as system-reminder)
"""

import json
import sys
import os
import sqlite3
import time
import numpy as np
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
LOG_PATH = os.path.expanduser("~/.claude-mem/logs/query-context.log")

# Search config
MAX_RESULTS = 20           # Max observations to inject per prompt
MAX_MEMORIES = 20          # Max memories to inject per prompt
MIN_QUERY_LENGTH = 15      # Skip very short prompts (greetings, "yes", etc.)
FTS_WEIGHT = 0.4
SEMANTIC_WEIGHT = 0.6
MMR_LAMBDA = 0.7           # Diversity vs relevance tradeoff (1.0 = pure relevance)
SCORE_THRESHOLD = 0.15     # Minimum hybrid score to include

# Stopwords for FTS5 query cleaning (shared by observation and memory search)
stopwords = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
             'of', 'to', 'in', 'for', 'on', 'at', 'by', 'with', 'from',
             'it', 'its', 'that', 'this', 'do', 'did', 'does', 'what',
             'how', 'when', 'where', 'why', 'who', 'which', 'can', 'we',
             'i', 'my', 'our', 'you', 'your', 'me', 'us', 'and', 'or', 'not'}


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
    """Lazy-load sentence transformer. Returns None if unavailable."""
    global _model, _model_load_attempted
    if _model_load_attempted:
        return _model
    _model_load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer
        model_name = os.environ.get("QUERY_CONTEXT_MODEL", "all-MiniLM-L6-v2")
        # Suppress model loading progress bars that leak to stdout via C-level writes
        old_fd = os.dup(1)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.close(devnull)
        try:
            _model = SentenceTransformer(model_name)
        finally:
            os.dup2(old_fd, 1)
            os.close(old_fd)
        return _model
    except Exception as e:
        log(f"Model load failed: {e}")
        return None


def decode_embedding(blob):
    """Unpack bytes from SQLite BLOB into numpy array."""
    if blob is None:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def get_embedding_dim(db):
    """Detect embedding dimension from first non-null embedding."""
    row = db.execute(
        "SELECT embedding FROM observations WHERE embedding IS NOT NULL LIMIT 1"
    ).fetchone()
    if row and row[0]:
        return len(np.frombuffer(row[0], dtype=np.float32))
    return 384  # default


def search_fts(db, query, limit=60):
    """FTS5 keyword search. Returns {id: normalized_score}."""
    terms = [t for t in query.split() if len(t) > 1 and t.lower() not in stopwords]
    if not terms:
        return {}

    safe_query = " OR ".join(f'"{t}"' for t in terms[:10])
    try:
        rows = db.execute("""
            SELECT obs.id, fts.rank
            FROM observations_fts fts
            JOIN observations obs ON obs.rowid = fts.rowid
            WHERE observations_fts MATCH ?
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
    """Semantic cosine similarity search. Returns {id: score}."""
    if model is None:
        return {}

    emb_dim = get_embedding_dim(db)
    query_emb = model.encode([query], normalize_embeddings=True)[0]

    # Only compare against correct-dimension embeddings
    rows = db.execute("""
        SELECT id, embedding FROM observations
        WHERE embedding IS NOT NULL
    """).fetchall()

    scores = []
    for obs_id, emb_blob in rows:
        emb = decode_embedding(emb_blob)
        if emb is not None and len(emb) == emb_dim:
            sim = float(np.dot(query_emb[:len(emb)], emb))
            scores.append((obs_id, sim))

    scores.sort(key=lambda x: -x[1])
    top = scores[:limit]

    if not top:
        return {}

    max_sim = top[0][1]
    min_sim = top[-1][1] if len(top) > 1 else 0
    spread = max_sim - min_sim if max_sim != min_sim else 1

    return {oid: (sim - min_sim) / spread for oid, sim in top}


def mmr_rerank(results, db, model, query, emb_dim, limit=20, lam=0.7):
    """
    Maximal Marginal Relevance re-ranking for diversity.
    Prevents all results clustering around one topic.
    """
    if model is None or len(results) <= limit:
        return results[:limit]

    query_emb = model.encode([query], normalize_embeddings=True)[0]

    # Get embeddings for all result candidates
    result_ids = [r[0] for r in results]
    placeholders = ",".join("?" * len(result_ids))
    rows = db.execute(f"""
        SELECT id, embedding FROM observations
        WHERE id IN ({placeholders}) AND embedding IS NOT NULL
    """, result_ids).fetchall()

    emb_map = {}
    for oid, blob in rows:
        emb = decode_embedding(blob)
        if emb is not None and len(emb) == emb_dim:
            emb_map[oid] = emb

    # Score map from hybrid results
    score_map = {r[0]: r[1] for r in results}

    selected = []
    remaining = [r[0] for r in results if r[0] in emb_map]

    while len(selected) < limit and remaining:
        best_id = None
        best_mmr = -float('inf')

        for oid in remaining:
            relevance = score_map.get(oid, 0)

            # Max similarity to already selected
            if selected:
                max_sim = max(
                    float(np.dot(emb_map[oid], emb_map[sid]))
                    for sid in selected if sid in emb_map
                )
            else:
                max_sim = 0

            mmr = lam * relevance - (1 - lam) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_id = oid

        if best_id:
            selected.append(best_id)
            remaining.remove(best_id)
        else:
            break

    # Rebuild results in MMR order
    score_lookup = {r[0]: r for r in results}
    return [score_lookup[oid] for oid in selected if oid in score_lookup]


def hybrid_search(db, model, query, limit=20):
    """Combined FTS5 + semantic search with MMR diversity."""
    fts_scores = search_fts(db, query, limit=limit * 3)
    sem_scores = search_semantic(db, model, query, limit=limit * 3)

    all_ids = set(fts_scores.keys()) | set(sem_scores.keys())
    combined = []

    for oid in all_ids:
        fts = fts_scores.get(oid, 0)
        sem = sem_scores.get(oid, 0)
        score = FTS_WEIGHT * fts + SEMANTIC_WEIGHT * sem
        if score >= SCORE_THRESHOLD:
            combined.append((oid, score, fts, sem))

    combined.sort(key=lambda x: -x[1])

    # Apply MMR diversity re-ranking
    if model is not None and len(combined) > limit:
        emb_dim = get_embedding_dim(db)
        combined = mmr_rerank(combined, db, model, query, emb_dim, limit=limit, lam=MMR_LAMBDA)

    return combined[:limit]


def search_memories_fts(db, query, limit=60):
    """FTS5 keyword search on memories table. Returns {id: normalized_score}."""
    terms = [t for t in query.split() if len(t) > 1 and t.lower() not in stopwords]
    if not terms:
        return {}

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
        return {}

    if not rows:
        return {}

    ranks = [abs(r[1]) for r in rows]
    max_rank = max(ranks) if ranks else 1
    return {r[0]: 1.0 - (abs(r[1]) / max_rank) if max_rank > 0 else 0 for r in rows}


def search_memories_semantic(db, model, query, limit=60):
    """Semantic cosine similarity search on memories. Returns {id: score}."""
    if model is None:
        return {}

    query_emb = model.encode([query], normalize_embeddings=True)[0]

    rows = db.execute("""
        SELECT id, embedding FROM memories
        WHERE embedding IS NOT NULL AND is_active = 1
    """).fetchall()

    scores = []
    for mid, emb_blob in rows:
        emb = decode_embedding(emb_blob)
        if emb is not None and len(emb) == len(query_emb):
            sim = float(np.dot(query_emb, emb))
            scores.append((mid, sim))

    scores.sort(key=lambda x: -x[1])
    top = scores[:limit]

    if not top:
        return {}

    max_sim = top[0][1]
    min_sim = top[-1][1] if len(top) > 1 else 0
    spread = max_sim - min_sim if max_sim != min_sim else 1

    return {mid: (sim - min_sim) / spread for mid, sim in top}


def hybrid_search_memories(db, model, query, limit=20):
    """Combined FTS5 + semantic search for memories."""
    fts_scores = search_memories_fts(db, query, limit=limit * 3)
    sem_scores = search_memories_semantic(db, model, query, limit=limit * 3)

    all_ids = set(fts_scores.keys()) | set(sem_scores.keys())
    combined = []

    for mid in all_ids:
        fts = fts_scores.get(mid, 0)
        sem = sem_scores.get(mid, 0)
        score = FTS_WEIGHT * fts + SEMANTIC_WEIGHT * sem
        if score >= SCORE_THRESHOLD:
            combined.append((mid, score, fts, sem))

    combined.sort(key=lambda x: -x[1])
    return combined[:limit]


def format_memories(db, memory_results):
    """Format memory search results as markdown for context injection."""
    if not memory_results:
        return ""

    ids = [r[0] for r in memory_results]
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"""
        SELECT id, fact, category FROM memories
        WHERE id IN ({placeholders}) AND is_active = 1
    """, ids).fetchall()

    mem_map = {r[0]: r for r in rows}

    lines = []
    lines.append("# Key Memories (knowledge facts)")
    lines.append("")

    for mid, score, *_ in memory_results:
        mem = mem_map.get(mid)
        if not mem:
            continue
        _, fact, category = mem
        cat_label = f" [{category}]" if category else ""
        lines.append(f"- **M{mid}**{cat_label}: {fact}")

    lines.append("")
    return "\n".join(lines)


def format_observations(db, results):
    """Format search results as compact markdown for context injection."""
    if not results:
        return ""

    ids = [r[0] for r in results]
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"""
        SELECT id, type, title, subtitle, facts, narrative,
               attention_score, created_at_epoch, files_modified
        FROM observations
        WHERE id IN ({placeholders})
    """, ids).fetchall()

    obs_map = {r[0]: r for r in rows}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    lines = []
    lines.append("# Relevant Observations (query-matched)")
    lines.append("")

    for oid, score, _fts, _sem in results:
        obs = obs_map.get(oid)
        if not obs:
            continue

        _, obs_type, title, subtitle, facts_json, narrative, _attn, epoch, files_mod = obs

        # Type indicator
        type_map = {
            'bugfix': 'B', 'decision': 'D', 'feature': 'F',
            'discovery': 'I', 'change': 'C', 'refactor': 'R'
        }
        t = type_map.get(obs_type, '?')

        lines.append(f"**#{oid}** [{t}] {title or 'Untitled'}")

        if files_mod:
            lines.append(f"  File: `{files_mod[:100]}`")

        if subtitle:
            lines.append(f"  {subtitle[:150]}")

        # Include key facts
        if facts_json:
            try:
                facts = json.loads(facts_json)
                for f in facts[:3]:
                    if f and len(str(f)) > 10:
                        lines.append(f"  - {str(f)[:200]}")
            except (json.JSONDecodeError, TypeError):
                pass

        # Include narrative for high-scoring results
        if narrative and score > 0.4:
            lines.append(f"  {narrative[:300]}")

        lines.append("")

    return "\n".join(lines)


def should_search(prompt):
    """Determine if this prompt warrants a memory search."""
    if not prompt or len(prompt.strip()) < MIN_QUERY_LENGTH:
        return False

    # Skip pure greetings, confirmations, very short responses
    lower = prompt.strip().lower()
    skip_patterns = [
        'good morning', 'morning routine', 'start the day',  # handled by skills
        'yes', 'no', 'ok', 'sure', 'thanks', 'thank you',
        'continue', 'go ahead', 'proceed', 'do it',
        '/commit', '/help', '/clear',  # slash commands
    ]
    for pat in skip_patterns:
        if lower == pat or lower.startswith(pat + ' ') and len(lower) < 30:
            return False

    return True


def entity_search(db, prompt, limit=5):
    """Find observations linked to entities mentioned in the prompt."""
    try:
        # Get all entity names and aliases
        rows = db.execute("SELECT id, name, aliases FROM entities").fetchall()
    except Exception:
        return []

    prompt_lower = prompt.lower()
    matched_eids = set()

    for eid, name, aliases_json in rows:
        if name.lower() in prompt_lower:
            matched_eids.add(eid)
        if aliases_json:
            try:
                for alias in json.loads(aliases_json):
                    if alias.lower() in prompt_lower:
                        matched_eids.add(eid)
            except (json.JSONDecodeError, TypeError):
                pass

    if not matched_eids:
        return []

    # Get observation IDs linked to matched entities
    placeholders = ",".join("?" * len(matched_eids))
    obs_rows = db.execute(f"""
        SELECT DISTINCT oe.observation_id
        FROM observation_entities oe
        JOIN observations o ON o.id = oe.observation_id
        WHERE oe.entity_id IN ({placeholders})
          AND o.valid_until_epoch IS NULL
        ORDER BY o.created_at_epoch DESC
        LIMIT ?
    """, list(matched_eids) + [limit]).fetchall()

    return [r[0] for r in obs_rows]


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

    if not os.path.exists(DB_PATH):
        log("No database found")
        sys.exit(0)

    db = sqlite3.connect(DB_PATH, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")

    # Load model for semantic search (memories + observations)
    model = get_model()

    # Search memories first (clean facts, high signal)
    memory_results = hybrid_search_memories(db, model, prompt, limit=MAX_MEMORIES)

    # Hybrid search observations
    results = hybrid_search(db, model, prompt, limit=MAX_RESULTS)

    # Entity-boosted retrieval: if prompt mentions known entities,
    # pull in their linked observations too
    entity_obs = entity_search(db, prompt, limit=5)
    if entity_obs:
        existing_ids = {r[0] for r in results}
        for obs_id in entity_obs:
            if obs_id not in existing_ids:
                results.append((obs_id, 0.3, 0, 0))  # Add with moderate score
                existing_ids.add(obs_id)

    elapsed = time.time() - t0

    if not results and not memory_results:
        log(f"No results for: {prompt[:80]} ({elapsed:.1f}s)")
        db.close()
        sys.exit(0)

    # Format and output — memories first (higher signal), then observations
    parts = []
    if memory_results:
        parts.append(format_memories(db, memory_results))
    if results:
        parts.append(format_observations(db, results))

    context = "\n".join(parts)
    db.close()

    log(f"Injected {len(memory_results)} memories + {len(results)} observations for: {prompt[:80]} ({elapsed:.1f}s)")

    # Output context — Claude Code injects this as system-reminder
    print(context)
    sys.exit(0)


if __name__ == '__main__':
    main()
