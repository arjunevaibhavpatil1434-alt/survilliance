#!/usr/bin/env python3
"""Telegram self-registration bot.

Lets a member join alerts from their phone - open @<bot username> in
Telegram and send /start - instead of an admin manually collecting chat
IDs and editing .env. Registered chat_ids land in the telegram_subscribers
table in faces.db; notify.py merges them with the static TELEGRAM_CHAT_ID
list from .env when sending KNOWN/UNKNOWN FACE alerts. /stop unsubscribes.

Long-polls Telegram's getUpdates rather than running a webhook, since this
box has no public HTTPS endpoint to receive one on.
"""
import sqlite3
import time

import requests

from config_loader import TELEGRAM_BOT_TOKEN, DB_FILE

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

POLL_TIMEOUT = 30

RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 60


def ensure_schema():
    conn = sqlite3.connect(DB_FILE)

    # The dashboard/recognize_rtsp.py services also create their own
    # tables on startup independently - this one must not depend on
    # start order either.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_subscribers (
            chat_id TEXT PRIMARY KEY,
            display_name TEXT,
            joined_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def add_subscriber(chat_id, display_name):
    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        """
        INSERT INTO telegram_subscribers (chat_id, display_name, joined_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(chat_id) DO UPDATE SET display_name = excluded.display_name
        """,
        (str(chat_id), display_name),
    )

    conn.commit()
    conn.close()


def remove_subscriber(chat_id):
    conn = sqlite3.connect(DB_FILE)

    conn.execute(
        "DELETE FROM telegram_subscribers WHERE chat_id = ?",
        (str(chat_id),),
    )

    conn.commit()
    conn.close()


def send_reply(chat_id, text):
    try:
        requests.post(
            f"{API_BASE}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=5,
        )
    except requests.RequestException as e:
        print(f"Reply to {chat_id} failed: {e}", flush=True)


def handle_update(update):
    message = update.get("message")

    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip().lower()

    if chat_id is None:
        return

    display_name = chat.get("username") or chat.get("first_name") or str(chat_id)

    if text.startswith("/start"):
        add_subscriber(chat_id, display_name)
        print(f"New subscriber: {display_name} ({chat_id})", flush=True)
        send_reply(
            chat_id,
            "You're now subscribed to surveillance alerts (known/unknown "
            "face detections). Send /stop at any time to unsubscribe.",
        )

    elif text.startswith("/stop"):
        remove_subscriber(chat_id)
        print(f"Unsubscribed: {display_name} ({chat_id})", flush=True)
        send_reply(chat_id, "You've been unsubscribed. Send /start to rejoin.")


def poll_loop():
    """Long-poll getUpdates forever, retrying with backoff on failure.

    Telegram itself (or the network to it) can go away independently of
    this process - retry here instead of exiting, same reasoning as the
    reconnect loops in recognize_rtsp.py/camera_rtsp_server.py.
    """

    offset = None
    delay = RECONNECT_DELAY

    while True:

        params = {"timeout": POLL_TIMEOUT}

        if offset is not None:
            params["offset"] = offset

        try:
            response = requests.get(
                f"{API_BASE}/getUpdates",
                params=params,
                timeout=POLL_TIMEOUT + 10,
            )
            response.raise_for_status()
            payload = response.json()

        except requests.RequestException as e:
            print(f"getUpdates failed: {e}, retrying in {delay}s...", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY)
            continue

        delay = RECONNECT_DELAY

        for update in payload.get("result", []):

            offset = update["update_id"] + 1

            try:
                handle_update(update)
            except Exception as e:
                print(f"Error handling update {update.get('update_id')}: {e}", flush=True)


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

    ensure_schema()

    print("Telegram registration bot started, polling for /start and /stop...", flush=True)

    poll_loop()


if __name__ == "__main__":
    main()
