#!/usr/bin/env python3
"""
Hybrid search engine for claude-mem observations.

Combines FTS5 keyword search with sentence-transformer semantic search.
- FTS5: fast exact/partial keyword matching via SQLite
- Semantic: cosine similarity on 384-dim MiniLM embeddings

Usage:
    # Embed all observations (run once, then incrementally)
    python3 hybrid-search.py --embed-all

    # Embed only new observations (no embedding yet)
    python3 hybrid-search.py --embed-new

    # Search
    python3 hybrid-search.py --query "kalshi weather oracle risk"

    # Search with options
    python3 hybrid-search.py --query "bug fix" --top 10 --mode hybrid
    python3 hybrid-search.py --query "trading bot" --mode semantic
    python3 hybrid-search.py --query "attention decay" --mode keyword
"""

import sqlite3
import os
import sys
import json
import struct
import argparse
import time
import numpy as np
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# Weights for hybrid scoring
FTS_WEIGHT = 0.4
SEMANTIC_WEIGHT = 0.6

# Lazy-loaded model
_model = None


def get_model():
    """Lazy-load the sentence transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def observation_to_text(title, subtitle, facts_json, narrative):
    """Convert observation fields into a single text for embedding."""
    parts = []
    if title:
        parts.append(title)
    if subtitle:
        parts.append(subtitle)
    if facts_json:
        try:
            facts = json.loads(facts_json)
            for f in facts[:5]:  # Top 5 facts
                if f and len(str(f)) > 10:
                    parts.append(str(f)[:200])
        except (json.JSONDecodeError, TypeError):
            pass
    if narrative and len(narrative) > 10:
        parts.append(narrative[:300])
    return " | ".join(parts) if parts else ""


def encode_embedding(embedding):
    """Pack numpy array into bytes for SQLite BLOB storage."""
    return embedding.astype(np.float32).tobytes()


def decode_embedding(blob):
    """Unpack bytes from SQLite BLOB into numpy array."""
    if blob is None:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def embed_observations(db, model, ids=None, batch_size=64):
    """Generate embeddings for observations. If ids=None, embed all without embeddings."""
    if ids is None:
        rows = db.execute("""
            SELECT id, title, subtitle, facts, narrative
            FROM observations
            WHERE embedding IS NULL
            ORDER BY id
        """).fetchall()
    else:
        placeholders = ",".join("?" * len(ids))
        rows = db.execute(f"""
            SELECT id, title, subtitle, facts, narrative
            FROM observations
            WHERE id IN ({placeholders})
            ORDER BY id
        """, ids).fetchall()

    if not rows:
        print("No observations need embedding")
        return 0

    total = len(rows)
    embedded = 0

    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        texts = [observation_to_text(r[1], r[2], r[3], r[4]) for r in batch]
        obs_ids = [r[0] for r in batch]

        # Filter out empty texts
        valid = [(oid, txt) for oid, txt in zip(obs_ids, texts) if txt.strip()]
        if not valid:
            continue

        valid_ids, valid_texts = zip(*valid)

        # Batch encode
        embeddings = model.encode(valid_texts, show_progress_bar=False, normalize_embeddings=True)

        # Store
        for oid, emb in zip(valid_ids, embeddings):
            db.execute(
                "UPDATE observations SET embedding = ? WHERE id = ?",
                (encode_embedding(emb), oid)
            )

        embedded += len(valid)
        if (i + batch_size) % (batch_size * 4) == 0 or i + batch_size >= total:
            db.commit()
            print(f"  Embedded {min(i + batch_size, total)}/{total} observations")

    db.commit()
    return embedded


def search_fts(db, query, limit=50):
    """Keyword search using FTS5. Returns {id: rank_score}."""
    # FTS5 rank is negative (more negative = better match)
    rows = db.execute("""
        SELECT obs.id, fts.rank
        FROM observations_fts fts
        JOIN observations obs ON obs.rowid = fts.rowid
        WHERE observations_fts MATCH ?
        ORDER BY fts.rank
        LIMIT ?
    """, (query, limit)).fetchall()

    if not rows:
        return {}

    # Normalize ranks to 0-1 (best match = 1.0)
    ranks = [abs(r[1]) for r in rows]
    max_rank = max(ranks) if ranks else 1
    return {r[0]: 1.0 - (abs(r[1]) / max_rank) if max_rank > 0 else 0 for r in rows}


def search_semantic(db, model, query, limit=50):
    """Semantic search using cosine similarity. Returns {id: similarity_score}."""
    # Encode query
    query_emb = model.encode([query], normalize_embeddings=True)[0]

    # Get all observations with embeddings
    rows = db.execute("""
        SELECT id, embedding FROM observations
        WHERE embedding IS NOT NULL
    """).fetchall()

    if not rows:
        return {}

    # Compute similarities
    scores = []
    for obs_id, emb_blob in rows:
        emb = decode_embedding(emb_blob)
        if emb is not None and len(emb) == EMBEDDING_DIM:
            # Cosine similarity (embeddings are normalized, so dot product = cosine)
            sim = float(np.dot(query_emb, emb))
            scores.append((obs_id, sim))

    # Sort by similarity, take top N
    scores.sort(key=lambda x: -x[1])
    top = scores[:limit]

    # Normalize to 0-1 range
    if not top:
        return {}
    max_sim = top[0][1]
    min_sim = top[-1][1] if len(top) > 1 else 0
    spread = max_sim - min_sim if max_sim != min_sim else 1

    return {oid: (sim - min_sim) / spread for oid, sim in top}


def mmr_rerank(results, db, model, limit=20, lam=0.7):
    """
    Maximal Marginal Relevance re-ranking for diversity.
    Prevents all results clustering around one topic.
    λ=1.0 means pure relevance, λ=0.0 means pure diversity.
    """
    if model is None or len(results) <= limit:
        return results[:limit]

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
        if emb is not None and len(emb) == EMBEDDING_DIM:
            emb_map[oid] = emb

    score_map = {r[0]: r[1] for r in results}
    selected = []
    remaining = [r[0] for r in results if r[0] in emb_map]

    while len(selected) < limit and remaining:
        best_id = None
        best_mmr = -float('inf')

        for oid in remaining:
            relevance = score_map.get(oid, 0)
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


def hybrid_search(db, model, query, limit=20, mode="hybrid"):
    """
    Combined FTS5 + semantic search with optional MMR diversity re-ranking.

    Modes:
    - hybrid: weighted combination of FTS5 and semantic scores
    - keyword: FTS5 only
    - semantic: semantic only
    """
    fts_scores = {}
    sem_scores = {}

    if mode in ("hybrid", "keyword"):
        fts_scores = search_fts(db, query, limit=limit * 3)

    if mode in ("hybrid", "semantic"):
        sem_scores = search_semantic(db, model, query, limit=limit * 3)

    # Combine scores
    all_ids = set(fts_scores.keys()) | set(sem_scores.keys())
    combined = []

    for oid in all_ids:
        fts = fts_scores.get(oid, 0)
        sem = sem_scores.get(oid, 0)

        if mode == "hybrid":
            score = FTS_WEIGHT * fts + SEMANTIC_WEIGHT * sem
        elif mode == "keyword":
            score = fts
        else:
            score = sem

        combined.append((oid, score, fts, sem))

    combined.sort(key=lambda x: -x[1])

    # Apply MMR diversity re-ranking when semantic search is available
    if model is not None and mode in ("hybrid", "semantic") and len(combined) > limit:
        combined = mmr_rerank(combined, db, model, limit=limit, lam=0.7)

    return combined[:limit]


def display_results(db, results, verbose=False):
    """Display search results."""
    if not results:
        print("No results found.")
        return

    ids = [r[0] for r in results]
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"""
        SELECT id, type, title, subtitle, attention_score, created_at_epoch
        FROM observations
        WHERE id IN ({placeholders})
    """, ids).fetchall()

    # Index by id
    obs_map = {r[0]: r for r in rows}
    now_epoch = int(datetime.now(timezone.utc).timestamp() * 1000)

    print(f"\n{'#':>5} {'Type':<10} {'Score':>6} {'FTS':>5} {'Sem':>5} {'Attn':>5} {'Age':>5} Title")
    print("-" * 95)

    for oid, score, fts, sem in results:
        obs = obs_map.get(oid)
        if not obs:
            continue
        _, obs_type, title, subtitle, attn, epoch = obs
        age_d = (now_epoch - (epoch or now_epoch)) / 86400000
        print(
            f"#{oid:>4} {obs_type:<10} {score:>6.3f} {fts:>5.2f} {sem:>5.2f} "
            f"{attn:>5.2f} {age_d:>4.0f}d {(title or '')[:40]}"
        )
        if verbose and subtitle:
            print(f"      {subtitle[:80]}")


def main():
    parser = argparse.ArgumentParser(description="Hybrid search for claude-mem observations")
    parser.add_argument("--embed-all", action="store_true", help="Embed all observations without embeddings")
    parser.add_argument("--embed-new", action="store_true", help="Alias for --embed-all")
    parser.add_argument("--force", action="store_true", help="Force re-embed all observations (use with --embed-all for model upgrades)")
    parser.add_argument("--query", "-q", type=str, help="Search query")
    parser.add_argument("--top", "-n", type=int, default=15, help="Number of results")
    parser.add_argument("--mode", choices=["hybrid", "keyword", "semantic"], default="hybrid")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")

    if args.embed_all or args.embed_new:
        print("Loading sentence-transformer model...")
        model = get_model()
        if args.force:
            # Clear all embeddings to force re-embed (for model upgrades)
            db.execute("UPDATE observations SET embedding = NULL")
            db.commit()
            print("Cleared all existing embeddings for re-embedding")
        t0 = time.time()
        count = embed_observations(db, model)
        elapsed = time.time() - t0
        print(f"Embedded {count} observations in {elapsed:.1f}s")
        # Report coverage
        total = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        with_emb = db.execute("SELECT COUNT(*) FROM observations WHERE embedding IS NOT NULL").fetchone()[0]
        print(f"Coverage: {with_emb}/{total} ({100*with_emb/total:.1f}%)")

    if args.query:
        model = get_model() if args.mode in ("hybrid", "semantic") else None
        t0 = time.time()
        results = hybrid_search(db, model, args.query, limit=args.top, mode=args.mode)
        elapsed = time.time() - t0
        display_results(db, results, verbose=args.verbose)
        print(f"\n({elapsed:.2f}s, mode={args.mode})")

    db.close()


if __name__ == "__main__":
    main()
