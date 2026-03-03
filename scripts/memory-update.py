#!/usr/bin/env python3
"""
Mem0-style memory update operations for claude-mem.

Runs on Stop hook after session summary. For each session's observations:
1. Hash content to detect exact duplicates
2. Search for similar existing observations
3. Apply operations: ADD (new), UPDATE (merge), DELETE (supersede), NOOP (skip)

This prevents memory bloat by maintaining a coherent knowledge base
instead of blindly accumulating duplicate observations.
"""

import sqlite3
import os
import sys
import json
import hashlib
import time
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
LOG_PATH = os.path.expanduser("~/.claude-mem/logs/memory-update.log")

# Similarity thresholds for operations
EXACT_DUPE_THRESHOLD = 0.95    # FTS5 score above this = likely exact duplicate
HIGH_SIMILARITY_THRESHOLD = 0.7  # Above this = candidate for UPDATE
CONTRADICTION_KEYWORDS = ['fixed', 'corrected', 'was wrong', 'actually', 'instead',
                          'not true', 'incorrect', 'changed from', 'no longer']


def log(msg):
    """Append to log file."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def content_hash(title, subtitle, facts_json, narrative):
    """Generate a normalized content hash for deduplication."""
    parts = []
    if title:
        parts.append(title.strip().lower())
    if subtitle:
        parts.append(subtitle.strip().lower())
    if facts_json:
        try:
            facts = json.loads(facts_json)
            for f in sorted(str(x).strip().lower() for x in facts if x):
                parts.append(f)
        except (json.JSONDecodeError, TypeError):
            pass
    if narrative:
        parts.append(narrative.strip().lower()[:500])

    text = "|".join(parts)
    return hashlib.md5(text.encode()).hexdigest()


def find_similar(db, obs_id, title, subtitle, limit=5):
    """Find similar existing observations using FTS5."""
    query_text = f"{title or ''} {subtitle or ''}"
    if len(query_text.strip()) < 10:
        return []

    # Quote each term for safe FTS5 query
    terms = query_text.split()
    safe_terms = [f'"{t}"' for t in terms if len(t) > 2]
    if not safe_terms:
        return []

    fts_query = " OR ".join(safe_terms[:8])  # Limit terms to avoid query explosion

    try:
        rows = db.execute("""
            SELECT obs.id, obs.title, obs.subtitle, obs.type, obs.content_hash,
                   obs.created_at_epoch, fts.rank
            FROM observations_fts fts
            JOIN observations obs ON obs.rowid = fts.rowid
            WHERE observations_fts MATCH ?
              AND obs.id != ?
              AND obs.valid_until_epoch IS NULL
            ORDER BY fts.rank
            LIMIT ?
        """, (fts_query, obs_id, limit)).fetchall()
        return rows
    except Exception:
        return []


def detect_contradiction(new_narrative, old_title, old_subtitle):
    """Heuristic: does the new observation contradict the old one?"""
    if not new_narrative:
        return False
    lower = new_narrative.lower()
    return any(kw in lower for kw in CONTRADICTION_KEYWORDS)


def decide_operation(obs, similar_results, existing_hashes):
    """
    Decide what to do with an observation.
    Returns: ('ADD'|'UPDATE'|'DELETE'|'NOOP', target_id_or_None, reason)
    """
    obs_id, title, subtitle, facts_json, narrative, obs_type, obs_hash = obs

    # 1. Exact hash duplicate → NOOP
    if obs_hash and obs_hash in existing_hashes:
        return ('NOOP', None, f'exact duplicate of #{existing_hashes[obs_hash]}')

    # 2. Check similar observations
    if not similar_results:
        return ('ADD', None, 'no similar observations found')

    best_match = similar_results[0]
    match_id, match_title, match_subtitle, match_type, match_hash, match_epoch, match_rank = best_match
    similarity = abs(match_rank)  # FTS rank as proxy for similarity

    # Very high similarity = likely duplicate content
    if similarity > 15:  # High FTS5 rank = very relevant
        # Check if this is a correction/update
        if detect_contradiction(narrative, match_title, match_subtitle):
            return ('DELETE', match_id, f'supersedes #{match_id} ({match_title[:40]})')

        # Same type + high similarity = UPDATE
        if match_type == obs_type:
            return ('UPDATE', match_id, f'updates #{match_id} ({match_title[:40]})')

        # Different type but high similarity = ADD (different perspective)
        return ('ADD', None, f'different perspective from #{match_id}')

    return ('ADD', None, 'sufficiently different from existing observations')


def apply_operations(db):
    """Process recent observations and apply Mem0-style operations."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    three_hours_ago = now_ms - (3 * 60 * 60 * 1000)

    # Get recent observations (last 3 hours, no hash yet)
    recent = db.execute("""
        SELECT id, title, subtitle, facts, narrative, type, content_hash
        FROM observations
        WHERE created_at_epoch > ?
          AND (content_hash IS NULL OR content_hash = '')
        ORDER BY created_at_epoch DESC
    """, (three_hours_ago,)).fetchall()

    if not recent:
        log("No unhashed recent observations to process")
        return 0, 0, 0, 0

    # Build existing hash index (for dedup)
    existing_hashes = {}
    rows = db.execute("""
        SELECT id, content_hash FROM observations
        WHERE content_hash IS NOT NULL AND content_hash != ''
          AND valid_until_epoch IS NULL
    """).fetchall()
    for oid, h in rows:
        existing_hashes[h] = oid

    stats = {'ADD': 0, 'UPDATE': 0, 'DELETE': 0, 'NOOP': 0}

    for obs in recent:
        obs_id = obs[0]
        title, subtitle, facts_json, narrative = obs[1], obs[2], obs[3], obs[4]

        # Compute and store content hash
        h = content_hash(title, subtitle, facts_json, narrative)
        db.execute("UPDATE observations SET content_hash = ? WHERE id = ?", (h, obs_id))

        # Rebuild obs tuple with hash
        obs_with_hash = (obs_id, title, subtitle, facts_json, narrative, obs[5], h)

        # Find similar existing observations
        similar = find_similar(db, obs_id, title, subtitle)

        # Decide operation
        operation, target_id, reason = decide_operation(obs_with_hash, similar, existing_hashes)

        if operation == 'NOOP':
            # Mark as duplicate — set low attention and expiry
            db.execute("""
                UPDATE observations
                SET attention_score = 0.01, valid_until_epoch = ?
                WHERE id = ?
            """, (now_ms, obs_id))
            log(f"NOOP #{obs_id}: {reason}")

        elif operation == 'UPDATE':
            # Merge: keep the newer observation, mark old as superseded
            db.execute("""
                UPDATE observations
                SET supersedes_id = ?, updated_at_epoch = ?
                WHERE id = ?
            """, (target_id, now_ms, obs_id))
            # Mark the old observation as superseded
            db.execute("""
                UPDATE observations
                SET valid_until_epoch = ?, attention_score = attention_score * 0.5
                WHERE id = ?
            """, (now_ms, target_id))
            log(f"UPDATE #{obs_id}: {reason}")

        elif operation == 'DELETE':
            # New info contradicts old — supersede old observation
            db.execute("""
                UPDATE observations
                SET supersedes_id = ?, updated_at_epoch = ?
                WHERE id = ?
            """, (target_id, now_ms, obs_id))
            db.execute("""
                UPDATE observations
                SET valid_until_epoch = ?, attention_score = 0.1
                WHERE id = ?
            """, (now_ms, target_id))
            log(f"DELETE #{obs_id} supersedes #{target_id}: {reason}")

        else:  # ADD
            # Just store the hash, observation is new
            existing_hashes[h] = obs_id
            log(f"ADD #{obs_id}: {reason}")

        stats[operation] += 1

    db.commit()
    return stats['ADD'], stats['UPDATE'], stats['DELETE'], stats['NOOP']


def main():
    t0 = time.time()

    if not os.path.exists(DB_PATH):
        log("No database found")
        return

    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")

    added, updated, deleted, noops = apply_operations(db)
    elapsed = time.time() - t0

    total = added + updated + deleted + noops
    log(f"Processed {total} observations: {added} ADD, {updated} UPDATE, {deleted} DELETE, {noops} NOOP ({elapsed:.1f}s)")

    if total > 0:
        print(f"Memory update: {added} new, {updated} updated, {deleted} superseded, {noops} duplicates ({elapsed:.1f}s)")

    db.close()


if __name__ == '__main__':
    main()
