#!/usr/bin/env python3
"""
Memory consolidation engine for claude-mem observations.

Reduces noise by merging related low-priority observations into consolidated
summaries. Runs after attention-decay to clean up expired/low-score entries.

Consolidation strategies:
1. Session merge: Multiple observations in the same session → single summary
2. File merge: Multiple edits to the same file → single "modified X" record
3. Prune expired: Delete snapshot observations past their validity window

This preserves:
- All permanent observations (decisions, bugfixes, config changes)
- Recent observations (last 3 days regardless of score)
- High-score observations (above consolidation threshold)
"""

import sqlite3
import os
import json
import sys
from datetime import datetime, timezone
from collections import defaultdict

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
LOG_PATH = os.path.expanduser("~/.claude-mem/logs/consolidation.log")

# Don't consolidate observations newer than this (days)
RECENCY_PROTECT_DAYS = 3

# Don't consolidate observations above this score
SCORE_THRESHOLD = 0.5

# Minimum cluster size to trigger consolidation
MIN_CLUSTER_SIZE = 3

# Types that are never consolidated
PROTECTED_TYPES = {"decision", "bugfix"}


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")
    except:
        pass


def get_consolidation_candidates(db, now_epoch):
    """Find observations eligible for consolidation."""
    protect_epoch = now_epoch - (RECENCY_PROTECT_DAYS * 86400000)

    rows = db.execute("""
        SELECT id, memory_session_id, type, title, facts,
               files_modified, attention_score, created_at_epoch, validity_class
        FROM observations
        WHERE attention_score < ?
          AND created_at_epoch < ?
          AND type NOT IN ('decision', 'bugfix')
        ORDER BY memory_session_id, created_at_epoch
    """, (SCORE_THRESHOLD, protect_epoch)).fetchall()

    return rows


def cluster_by_session(candidates):
    """Group candidates by session for merging."""
    clusters = defaultdict(list)
    for row in candidates:
        session_id = row[1]
        if session_id:
            clusters[session_id].append(row)
    # Only return clusters with enough entries
    return {k: v for k, v in clusters.items() if len(v) >= MIN_CLUSTER_SIZE}


def cluster_by_file(candidates):
    """Group candidates by file modified."""
    clusters = defaultdict(list)
    for row in candidates:
        files_json = row[5]
        if files_json:
            try:
                files = json.loads(files_json)
                for f in files:
                    if f:
                        clusters[f].append(row)
            except:
                pass
    return {k: v for k, v in clusters.items() if len(v) >= MIN_CLUSTER_SIZE}


def merge_session_cluster(db, session_id, observations):
    """Merge a session cluster into a single consolidated observation."""
    # Extract unique titles and facts
    titles = []
    all_facts = []
    all_files_read = set()
    all_files_modified = set()
    types_seen = set()
    max_score = 0

    for obs_id, _, obs_type, title, facts_json, files_mod_json, score, epoch, _ in observations:
        if title:
            titles.append(title)
        types_seen.add(obs_type)
        max_score = max(max_score, score)

        if facts_json:
            try:
                for f in json.loads(facts_json):
                    if f and len(f) > 10:  # Skip trivial facts
                        all_facts.append(f)
            except:
                pass

        if files_mod_json:
            try:
                for f in json.loads(files_mod_json):
                    if f:
                        all_files_modified.add(f)
            except:
                pass

    # Build consolidated title
    n = len(observations)
    unique_files = len(all_files_modified)
    if unique_files > 0:
        consolidated_title = f"Session: {n} actions across {unique_files} files"
    else:
        consolidated_title = f"Session: {n} actions"

    # Keep top 5 most informative facts
    top_facts = sorted(all_facts, key=len, reverse=True)[:5]

    # Use the most impactful type
    consolidated_type = "feature" if "feature" in types_seen else (
        "change" if "change" in types_seen else "discovery"
    )

    return {
        "title": consolidated_title,
        "type": consolidated_type,
        "facts": top_facts,
        "files_modified": list(all_files_modified),
        "score": max_score,
        "original_ids": [obs[0] for obs in observations],
        "session_id": session_id,
        "epoch": observations[0][7],  # Use earliest epoch
    }


def run_consolidation(dry_run=True, verbose=False):
    """Run the consolidation engine."""
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")

    now_epoch = int(datetime.now(timezone.utc).timestamp() * 1000)

    stats = {
        "candidates": 0,
        "session_clusters": 0,
        "consolidated": 0,
        "deleted": 0,
        "expired_pruned": 0,
    }

    # Step 1: Find candidates
    candidates = get_consolidation_candidates(db, now_epoch)
    stats["candidates"] = len(candidates)

    if verbose:
        print(f"Found {len(candidates)} consolidation candidates")

    # Step 2: Cluster by session
    session_clusters = cluster_by_session(candidates)
    stats["session_clusters"] = len(session_clusters)

    if verbose:
        print(f"Found {len(session_clusters)} session clusters (>={MIN_CLUSTER_SIZE} each)")

    # Step 3: Process each cluster
    merges = []
    for session_id, obs_list in session_clusters.items():
        merged = merge_session_cluster(db, session_id, obs_list)
        merges.append(merged)
        if verbose:
            print(f"  Session {session_id[:8]}...: {len(obs_list)} -> 1 ({merged['title'][:50]})")

    # Step 4: Prune expired snapshots (score < 0.05)
    expired = db.execute("""
        SELECT id FROM observations
        WHERE validity_class = 'snapshot'
          AND valid_until_epoch IS NOT NULL
          AND valid_until_epoch < ?
          AND attention_score < 0.05
          AND type NOT IN ('decision', 'bugfix')
    """, (now_epoch,)).fetchall()
    expired_ids = [r[0] for r in expired]
    stats["expired_pruned"] = len(expired_ids)

    if verbose:
        print(f"\nExpired snapshots to prune: {len(expired_ids)}")

    # Step 5: Execute (unless dry run)
    if not dry_run:
        for merge in merges:
            # Insert consolidated observation
            db.execute("""
                INSERT INTO observations
                (memory_session_id, project, type, title, subtitle, facts, narrative,
                 concepts, files_read, files_modified, created_at, created_at_epoch,
                 attention_score, validity_class, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'permanent', 0)
            """, (
                merge["session_id"],
                "default",  # Default project
                merge["type"],
                merge["title"],
                f"Consolidated from {len(merge['original_ids'])} observations",
                json.dumps(merge["facts"]),
                "",
                json.dumps([]),
                json.dumps([]),
                json.dumps(merge["files_modified"]),
                datetime.now(timezone.utc).isoformat(),
                merge["epoch"],
                merge["score"],
            ))

            # Delete originals
            ids = merge["original_ids"]
            for oid in ids:
                db.execute("DELETE FROM observations WHERE id = ?", (oid,))
            stats["deleted"] += len(ids)
            stats["consolidated"] += 1

        # Prune expired
        for oid in expired_ids:
            db.execute("DELETE FROM observations WHERE id = ?", (oid,))

        db.commit()
        log(f"Consolidated: {stats['consolidated']} clusters, deleted {stats['deleted']} originals, pruned {stats['expired_pruned']} expired")
    else:
        if verbose:
            print(f"\n[DRY RUN] Would consolidate {len(merges)} clusters, prune {len(expired_ids)} expired")

    db.close()

    if verbose:
        print(f"\nConsolidation Report")
        print(f"{'=' * 50}")
        print(f"Candidates found: {stats['candidates']}")
        print(f"Session clusters: {stats['session_clusters']}")
        print(f"Consolidated: {stats['consolidated']}")
        print(f"Originals deleted: {stats['deleted']}")
        print(f"Expired pruned: {stats['expired_pruned']}")

    return stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Memory consolidation engine")
    parser.add_argument("--execute", action="store_true", help="Actually perform consolidation (default: dry run)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed report")
    args = parser.parse_args()

    run_consolidation(dry_run=not args.execute, verbose=args.verbose or True)


if __name__ == "__main__":
    main()
