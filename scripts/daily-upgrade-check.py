#!/usr/bin/env python3
"""
Daily Upgrade Check — scans RSS feeds for new releases and actionable upgrades.

Runs via heartbeat daemon or launchd. Checks all ecosystem GitHub release feeds
and news sources, compares against known-installed versions, and writes a report.

Output: ~/.claude/upgrade-report.md (overwritten daily)
Notification: ntfy push if new releases found
"""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
REPORT_PATH = HOME / ".claude/upgrade-report.md"
RSS_CONFIG = HOME / "rss-news-analyzer-mcp/rss_feeds_config.json"
LOG_PATH = HOME / ".claude-mem/logs/daily-upgrade-check.log"
NTFY_TOPIC = "mojo-alerts-kk"

# Feeds to check for releases (GitHub atom feeds)
RELEASE_FEEDS = [
    "github_claude_code",
    "github_openclaw",
    "github_nanoclaw",
    "github_mem0",
    "github_claude_flow",
    "github_everything_claude_code",
    "github_awesome_claude_code",
    "github_claude_mem",
]

# Feeds to check for news
NEWS_FEEDS = [
    "anthropic_blog",
    "hacker_news",
    "techcrunch_ai",
]


def log(msg):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(f"{datetime.now().isoformat()} - {msg}\n")
    except Exception:
        pass


def fetch_feed_via_python(feed_url):
    """Fetch and parse a feed directly using feedparser."""
    try:
        import feedparser
        feed = feedparser.parse(feed_url)
        if feed.bozo and not feed.entries:
            return None
        return feed
    except ImportError:
        # feedparser not available, use urllib fallback
        return fetch_feed_raw(feed_url)


def fetch_feed_raw(feed_url):
    """Minimal feed fetch using urllib — no feedparser dependency."""
    import urllib.request
    import xml.etree.ElementTree as ET

    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "MojoOS/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8")

        root = ET.fromstring(data)
        entries = []

        # Handle Atom feeds
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip()
            updated = entry.findtext("atom:updated", "", ns).strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            content = entry.findtext("atom:content", "", ns).strip()
            entries.append({
                "title": title,
                "updated": updated,
                "link": link,
                "content": content[:500],
            })

        # Handle RSS feeds
        if not entries:
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                pubdate = (item.findtext("pubDate") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "").strip()
                entries.append({
                    "title": title,
                    "updated": pubdate,
                    "link": link,
                    "content": desc[:500],
                })

        return entries
    except Exception as e:
        log(f"Fetch failed for {feed_url}: {e}")
        return None


def get_feed_url(feed_id):
    """Look up feed URL from config."""
    try:
        with open(RSS_CONFIG) as f:
            config = json.load(f)
        for feed in config["feeds"]:
            if feed["id"] == feed_id:
                return feed["url"], feed["name"]
    except Exception:
        pass
    return None, None


def is_recent(date_str, hours=48):
    """Check if a date string is within the last N hours."""
    if not date_str:
        return False
    try:
        # Try ISO format
        for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%S%z", "%a, %d %b %Y %H:%M:%S %z",
                    "%a, %d %b %Y %H:%M:%S GMT"]:
            try:
                dt = datetime.strptime(date_str[:30], fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
                return dt > cutoff
            except ValueError:
                continue
    except Exception:
        pass
    return False


def get_installed_version():
    """Get currently installed Claude Code version."""
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def send_ntfy(title, message):
    """Send push notification via ntfy."""
    try:
        import urllib.request
        data = message.encode("utf-8")
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=data,
            headers={"Title": title, "Priority": "default", "Tags": "rocket"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=10)
        log(f"ntfy sent: {title}")
    except Exception as e:
        log(f"ntfy failed: {e}")


def main():
    log("Starting daily upgrade check")

    report_lines = [
        "# Mojo OS — Daily Upgrade Report",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} MT",
        f"Claude Code: {get_installed_version()}",
        "",
    ]

    new_releases = []
    all_releases = {}

    # ── Check release feeds ──
    report_lines.append("## Ecosystem Releases (last 48h)")
    report_lines.append("")

    for feed_id in RELEASE_FEEDS:
        url, name = get_feed_url(feed_id)
        if not url:
            continue

        entries = fetch_feed_raw(url)
        if not entries:
            log(f"No entries from {feed_id}")
            continue

        recent = [e for e in entries if is_recent(e.get("updated"), hours=48)]
        all_releases[feed_id] = entries[:5]  # Store latest 5 for reference

        if recent:
            report_lines.append(f"### {name}")
            for entry in recent[:3]:
                title = entry.get("title", "Untitled")
                link = entry.get("link", "")
                updated = entry.get("updated", "")[:10]
                content_preview = entry.get("content", "")[:200]
                report_lines.append(f"- **{title}** ({updated})")
                if link:
                    report_lines.append(f"  {link}")
                if content_preview:
                    # Strip HTML tags crudely
                    import re
                    clean = re.sub(r'<[^>]+>', '', content_preview).strip()
                    if clean:
                        report_lines.append(f"  > {clean[:150]}")
                report_lines.append("")
                new_releases.append({"source": name, "title": title, "link": link})

    if not new_releases:
        report_lines.append("*No new releases in the last 48 hours.*")
        report_lines.append("")

    # ── Check news feeds for relevant articles ──
    report_lines.append("## AI/Claude News Highlights (last 48h)")
    report_lines.append("")

    ai_keywords = ["claude", "anthropic", "mcp", "ai agent", "prediction market",
                    "claude code", "autonomous", "coding agent"]
    news_found = False

    for feed_id in NEWS_FEEDS:
        url, name = get_feed_url(feed_id)
        if not url:
            continue

        entries = fetch_feed_raw(url)
        if not entries:
            continue

        relevant = []
        for entry in entries:
            if not is_recent(entry.get("updated"), hours=48):
                continue
            text = f"{entry.get('title', '')} {entry.get('content', '')}".lower()
            matched = [kw for kw in ai_keywords if kw in text]
            if matched:
                relevant.append((entry, matched))

        if relevant:
            report_lines.append(f"### {name}")
            for entry, keywords in relevant[:5]:
                title = entry.get("title", "Untitled")
                link = entry.get("link", "")
                report_lines.append(f"- **{title}**")
                if link:
                    report_lines.append(f"  {link}")
                report_lines.append(f"  Keywords: {', '.join(keywords)}")
                report_lines.append("")
            news_found = True

    if not news_found:
        report_lines.append("*No relevant AI/Claude news in the last 48 hours.*")
        report_lines.append("")

    # ── Latest versions reference ──
    report_lines.append("## Latest Known Versions")
    report_lines.append("")
    report_lines.append("| Project | Latest Release |")
    report_lines.append("|---------|---------------|")

    for feed_id, entries in all_releases.items():
        _, name = get_feed_url(feed_id)
        if entries:
            latest = entries[0].get("title", "unknown")
            report_lines.append(f"| {name} | {latest} |")

    report_lines.append("")

    # ── Action items ──
    report_lines.append("## Action Items")
    report_lines.append("")

    if new_releases:
        report_lines.append("New releases to review:")
        for rel in new_releases:
            report_lines.append(f"- [ ] {rel['source']}: {rel['title']}")
        report_lines.append("")
    else:
        report_lines.append("*No action items — all quiet.*")

    # Write report
    report = "\n".join(report_lines)
    REPORT_PATH.write_text(report)
    log(f"Report written: {len(new_releases)} new releases, {len(report)} chars")

    # Send notification if new releases found
    if new_releases:
        summary = ", ".join(f"{r['source']}" for r in new_releases[:3])
        send_ntfy(
            f"Mojo: {len(new_releases)} new release(s)",
            f"New from: {summary}\nSee ~/.claude/upgrade-report.md"
        )

    # Print summary
    print(f"Upgrade check complete: {len(new_releases)} new releases found")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
