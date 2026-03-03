#!/usr/bin/env python3
"""
Attention decay engine for claude-mem observations.

Implements exponential decay with type-based weighting:
  score = type_weight * exp(-age_days / half_life) * access_boost

Run periodically (hourly via heartbeat or launchd) to:
1. Recalculate attention scores for all observations
2. Prune observations below the threshold
3. Report statistics

Type weights reflect information value:
- decisions/bugfixes persist longest (high weight, long half-life)
- features/refactors are medium
- discoveries/changes decay fastest (most are routine)

Access boost: each access adds 0.1 to the multiplier, capped at 2.0
"""

import sqlite3
import math
import os
import sys
import json
from datetime import datetime, timezone

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
LOG_PATH = os.path.expanduser("~/.claude-mem/logs/attention-decay.log")

# --- Configuration ---

# Half-life in days: how long until score drops to 50%
TYPE_HALF_LIFE = {
    "decision": 30,    # Decisions stay relevant for a month
    "bugfix": 21,      # Bugfixes relevant ~3 weeks
    "feature": 14,     # Features relevant ~2 weeks
    "refactor": 14,
    "discovery": 7,    # Discoveries are usually transient
    "change": 5,       # File changes are most transient
}

# Base weight by type (importance multiplier)
TYPE_WEIGHT = {
    "decision": 2.0,
    "bugfix": 1.8,
    "feature": 1.5,
    "refactor": 1.2,
    "discovery": 1.0,
    "change": 0.8,
}

# Minimum score before pruning (0.0 = keep everything)
PRUNE_THRESHOLD = 0.01

# Maximum access boost multiplier
MAX_ACCESS_BOOST = 2.0

# Access boost per access (additive to 1.0 base)
ACCESS_BOOST_PER = 0.1


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")
    except:
        pass


def calculate_score(obs_type, age_days, access_count):
    """Calculate attention score for an observation."""
    half_life = TYPE_HALF_LIFE.get(obs_type, 7)
    weight = TYPE_WEIGHT.get(obs_type, 1.0)

    # Exponential decay
    decay = math.exp(-age_days * math.log(2) / half_life)

    # Access boost (capped)
    access_boost = min(1.0 + access_count * ACCESS_BOOST_PER, MAX_ACCESS_BOOST)

    return weight * decay * access_boost


def run_decay(prune=False, verbose=False):
    """Recalculate all attention scores and optionally prune."""
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA journal_mode=WAL")

    now_epoch = int(datetime.now(timezone.utc).timestamp() * 1000)  # milliseconds

    # Get all observations
    rows = db.execute("""
        SELECT id, type, created_at_epoch, access_count, attention_score,
               validity_class, valid_until_epoch
        FROM observations
        ORDER BY created_at_epoch DESC
    """).fetchall()

    if not rows:
        print("No observations to process")
        db.close()
        return

    updates = []
    prune_ids = []
    stats = {"total": 0, "updated": 0, "pruned": 0, "expired": 0, "by_type": {}}

    for obs_id, obs_type, created_epoch, access_count, old_score, validity_class, valid_until in rows:
        stats["total"] += 1
        age_days = max((now_epoch - (created_epoch or now_epoch)) / 86400000, 0)  # ms to days
        new_score = calculate_score(obs_type, age_days, access_count or 0)

        # Apply expiry penalty: expired observations get 10% of their score
        if valid_until and now_epoch > valid_until:
            new_score *= 0.1
            stats["expired"] += 1

        # Track by type
        if obs_type not in stats["by_type"]:
            stats["by_type"][obs_type] = {"count": 0, "avg_score": 0, "min_score": 999}
        stats["by_type"][obs_type]["count"] += 1
        stats["by_type"][obs_type]["avg_score"] += new_score
        stats["by_type"][obs_type]["min_score"] = min(
            stats["by_type"][obs_type]["min_score"], new_score
        )

        if prune and new_score < PRUNE_THRESHOLD:
            prune_ids.append(obs_id)
            stats["pruned"] += 1
        else:
            updates.append((new_score, obs_id))
            stats["updated"] += 1

    # Batch update scores
    db.executemany(
        "UPDATE observations SET attention_score = ? WHERE id = ?",
        updates
    )

    # Prune if requested
    if prune and prune_ids:
        placeholders = ",".join("?" * len(prune_ids))
        db.execute(f"DELETE FROM observations WHERE id IN ({placeholders})", prune_ids)

    db.commit()
    db.close()

    # Finalize averages
    for t in stats["by_type"]:
        cnt = stats["by_type"][t]["count"]
        if cnt > 0:
            stats["by_type"][t]["avg_score"] = round(
                stats["by_type"][t]["avg_score"] / cnt, 4
            )
        stats["by_type"][t]["min_score"] = round(
            stats["by_type"][t]["min_score"], 4
        )

    # Report
    log(f"Decay run: {stats['total']} total, {stats['updated']} updated, {stats['pruned']} pruned")

    if verbose:
        print(f"\nAttention Decay Report")
        print(f"{'=' * 50}")
        print(f"Total observations: {stats['total']}")
        print(f"Updated: {stats['updated']}")
        print(f"Pruned: {stats['pruned']}")
        print(f"\nBy type:")
        for t, s in sorted(stats["by_type"].items(), key=lambda x: -x[1]["avg_score"]):
            print(f"  {t:<12} count={s['count']:>5}  avg_score={s['avg_score']:.4f}  min={s['min_score']:.4f}")

    return stats


def show_top(n=20):
    """Show top-N observations by attention score."""
    db = sqlite3.connect(DB_PATH, timeout=5)
    rows = db.execute("""
        SELECT id, type, title, attention_score, access_count,
               created_at, created_at_epoch
        FROM observations
        ORDER BY attention_score DESC
        LIMIT ?
    """, (n,)).fetchall()
    db.close()

    now_epoch = int(datetime.now(timezone.utc).timestamp() * 1000)  # milliseconds
    print(f"\nTop {n} observations by attention score:")
    print(f"{'ID':>5} {'Type':<12} {'Score':>7} {'Age':>6} {'Title'}")
    print("-" * 80)
    for obs_id, obs_type, title, score, access, created, epoch in rows:
        age_d = (now_epoch - (epoch or now_epoch)) / 86400000  # ms to days
        print(f"#{obs_id:>4} {obs_type:<12} {score:>7.4f} {age_d:>5.1f}d {(title or '')[:45]}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Attention decay for claude-mem observations")
    parser.add_argument("--prune", action="store_true", help="Delete low-score observations")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed report")
    parser.add_argument("--top", type=int, default=0, help="Show top N by score")
    args = parser.parse_args()

    stats = run_decay(prune=args.prune, verbose=args.verbose or args.top > 0)

    if args.top > 0:
        show_top(args.top)


if __name__ == "__main__":
    main()
