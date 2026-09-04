import sqlite3
import threading
from datetime import datetime

import requests

from config_loader import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_IDS, LOG_FILE, DB_FILE

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _all_recipients():
    """Static .env chat IDs plus anyone who self-registered from their
    phone via telegram_bot.py's /start - deduplicated, in case someone's
    listed both ways.
    """

    chat_ids = list(TELEGRAM_CHAT_IDS)

    try:
        conn = sqlite3.connect(DB_FILE)
        rows = conn.execute("SELECT chat_id FROM telegram_subscribers").fetchall()
        conn.close()
    except sqlite3.OperationalError:
        # telegram_bot.py hasn't run yet, so the table doesn't exist -
        # static .env recipients still work fine without it.
        return chat_ids

    for (chat_id,) in rows:
        if chat_id not in chat_ids:
            chat_ids.append(chat_id)

    return chat_ids


def _log_error(context, detail):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] TELEGRAM ERROR ({context}): {detail}\n"

    print(line.strip())

    with open(LOG_FILE, "a") as f:
        f.write(line)


def _check_response(context, chat_id, response):
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not response.ok or not payload.get("ok", False):
        _log_error(context, f"chat_id={chat_id}: HTTP {response.status_code} - {payload}")
        return False

    return True


def _send_message_one(chat_id, message):
    try:
        response = requests.post(
            f"{API_BASE}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": message
            },
            timeout=5
        )
    except requests.RequestException as e:
        _log_error("sendMessage", f"chat_id={chat_id}: {e}")
        return

    _check_response("sendMessage", chat_id, response)


def _send_photo_one(chat_id, photo_path):
    try:
        with open(photo_path, "rb") as photo:
            response = requests.post(
                f"{API_BASE}/sendPhoto",
                files={"photo": photo},
                data={"chat_id": chat_id},
                timeout=10
            )
    except (requests.RequestException, OSError) as e:
        _log_error("sendPhoto", f"chat_id={chat_id}: {e}")
        return

    _check_response("sendPhoto", chat_id, response)


def send_message(message):
    """Fan out to every configured recipient without blocking the caller.

    recognize_rtsp.py's main detection loop calls this inline between
    frames - one recipient's slow/unreachable connection (up to the 5s
    request timeout each) used to stall detection of the next person, and
    that only gets worse with more recipients, so each send runs in its
    own daemon thread instead of sequentially on the caller's thread.
    """

    chat_ids = _all_recipients()

    if not TELEGRAM_BOT_TOKEN or not chat_ids:
        print("Telegram not configured, skipping message")
        return

    for chat_id in chat_ids:
        threading.Thread(
            target=_send_message_one, args=(chat_id, message), daemon=True
        ).start()


def send_photo(photo_path):
    """Fan out to every configured recipient without blocking the caller.

    See send_message() - same reasoning, plus each thread opens its own
    read handle on photo_path so concurrent sends don't interfere.
    """

    chat_ids = _all_recipients()

    if not TELEGRAM_BOT_TOKEN or not chat_ids:
        print("Telegram not configured, skipping photo")
        return

    for chat_id in chat_ids:
        threading.Thread(
            target=_send_photo_one, args=(chat_id, photo_path), daemon=True
        ).start()
