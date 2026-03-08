#!/usr/bin/env python3
"""
Unified Telegram notification module for all Mojo systems.

All bots, monitors, and daemons import this to send formatted
Telegram messages. Matches the Locksy copybot style.

Usage:
    from mojo_notify import notify, notify_trading, notify_system

    notify("Plain message")
    notify_trading("Spotify Edge", "Daily Report", body_lines)
    notify_system("Heartbeat", "Task complete", summary)
"""

import json
import os
import urllib.request
from pathlib import Path
from datetime import datetime

# Load credentials once
_TOKEN = None
_CHAT_ID = None


def _load_creds():
    global _TOKEN, _CHAT_ID
    if _TOKEN and _CHAT_ID:
        return _TOKEN, _CHAT_ID

    env_path = Path.home() / ".config/personal-os/telegram.env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    _TOKEN = line.split("=", 1)[1].strip().strip("\"'")
                elif line.startswith("TELEGRAM_USER_ID="):
                    _CHAT_ID = line.split("=", 1)[1].strip().strip("\"'")
    return _TOKEN, _CHAT_ID


def notify(message, parse_mode="Markdown"):
    """Send a plain Telegram message. Returns True on success."""
    token, chat_id = _load_creds()
    if not token or not chat_id:
        return False

    msg_data = {"chat_id": chat_id, "text": message}
    if parse_mode:
        msg_data["parse_mode"] = parse_mode
    payload = json.dumps(msg_data).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"[mojo_notify] Telegram send failed: {e}")
        return False


def notify_trading(source, title, lines, emoji="📊"):
    """
    Send a formatted trading notification.

    Args:
        source: Bot name (e.g., "Spotify Edge", "Hedge Fund")
        title: Report title (e.g., "Daily Report", "Signal: BUY")
        lines: List of body lines (plain text, no markdown needed)
        emoji: Header emoji
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"{emoji} *{source} — {title}*\n_{ts}_"
    body = "\n".join(lines)
    return notify(f"{header}\n\n{body}")


def notify_system(source, title, body, emoji="🔧"):
    """
    Send a formatted system notification.

    Args:
        source: System name (e.g., "Heartbeat", "Upgrade Check")
        title: What happened (e.g., "Task Complete", "New Release")
        body: Detail text
        emoji: Header emoji
    """
    ts = datetime.now().strftime("%H:%M")
    header = f"{emoji} *{source} — {title}* ({ts})"
    return notify(f"{header}\n\n{body}")


def notify_email(priority, sender, subject, preview=""):
    """
    Send an email alert notification.

    Args:
        priority: "HIGH" or "MEDIUM"
        sender: Email sender
        subject: Email subject
        preview: Optional preview text
    """
    emoji = "🔴" if priority == "HIGH" else "🟡"
    msg = f"{emoji} *New Email*\n\n*From:* {sender}\n*Subject:* {subject}"
    if preview:
        msg += f"\n\n_{preview[:200]}_"
    msg += "\n\n_Reply here to act on this._"
    return notify(msg)


if __name__ == "__main__":
    # Quick test
    success = notify_system("mojo_notify", "Test", "Notification system working.")
    print(f"Test send: {'OK' if success else 'FAILED'}")
