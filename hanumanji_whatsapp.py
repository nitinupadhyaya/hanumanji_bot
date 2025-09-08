import os
import sqlite3
import requests
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from verses import verses

# ------------------- Config -------------------
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "hanumanjitoken")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")  # required
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")      # required
ADMIN_NUMBER = os.environ.get("ADMIN_NUMBER", "")        # e.g. +919540964715 or 919540964715

if not META_ACCESS_TOKEN:
    print("⚠️ WARNING: META_ACCESS_TOKEN not set. Messaging will fail until you set it.")
if not PHONE_NUMBER_ID:
    print("⚠️ WARNING: PHONE_NUMBER_ID not set. Messaging will fail until you set it.")

app = Flask(__name__)
DB_FILE = "progress.db"


# ------------------- Small utilities -------------------
def normalize_number(n: str) -> str:
    """Return only digits (E.164 without +)."""
    if not n:
        return ""
    return "".join(ch for ch in n if ch.isdigit())


ADMIN_NUMBER_CLEAN = normalize_number(ADMIN_NUMBER)


# ------------------- DB Helpers -------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (phone TEXT PRIMARY KEY, day INTEGER)''')
    conn.commit()
    conn.close()


def get_progress(phone):
    """Return None if user not in DB, else integer day."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT day FROM users WHERE phone=?", (phone,))
    row = c.fetchone()
    conn.close()
    return None if row is None else row[0]


def save_progress(phone, day):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (phone, day) VALUES (?, ?)", (phone, day))
    conn.commit()
    conn.close()


def get_all_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT phone FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users


# ------------------- Messaging Helpers -------------------
def send_whatsapp_message(phone_number_id: str, to_number: str, message_text: str) -> (int, dict):
    """
    Send text message via Meta Graph API.
    to_number should be numeric E.164 without '+' (e.g. 9198xxxx).
    Returns (status_code, json_or_text).
    """
    if not META_ACCESS_TOKEN or not phone_number_id:
        print("⚠️ Missing token or phone_number_id; cannot send.")
        return 0, {"error": "missing token or phone_number_id"}

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "text": {"body": message_text}
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        try:
            resp_json = resp.json()
        except Exception:
            resp_json = resp.text
        print(f"📤 Sent to {to_number}: {resp.status_code} {resp_json}")
        return resp.status_code, resp_json
    except Exception as e:
        print(f"❌ Error sending to {to_number}: {e}")
        return 0, {"error": str(e)}


# ------------------- Admin Helpers -------------------
def handle_admin_message(incoming_msg: str, phone_number_id: str) -> str:
    incoming_msg = incoming_msg.strip()
    if incoming_msg.lower().startswith("broadcast "):
        broadcast_msg = incoming_msg[len("broadcast "):].strip()
        users = get_all_users()

        if not users:
            return "⚠️ No users found in DB to broadcast."

        successes = 0
        failures = 0
        for u in users:
            to_num = normalize_number(u)
            status, body = send_whatsapp_message(phone_number_id, to_num, f"[Broadcast] {broadcast_msg}")
            if 200 <= status < 300:
                successes += 1
            else:
                failures += 1
                print(f"❌ Broadcast failed for {u}: {status} {body}")

        return f"✅ Broadcast attempted. Success: {successes}, Failures: {failures}"

    return "❌ Admin command not recognized. Use: broadcast <message>"


# ------------------- Learning Logic -------------------
def get_next_message(phone):
    """
    Advance the user's day by 1 and return the message for that day.
    If user was not in DB, treat as day 0 and send day1.
    """
    current = get_progress(phone)
    if current is None:
        current = 0

    next_day = current + 1
    day_key = f"day{next_day}"

    if day_key in verses:
        verse = verses[day_key]
        save_progress(phone, next_day)
        return (
            f"📖 Day {next_day} Verse:\n\n"
            f"{verse['verse']}\n\n"
            f"🌐 English: {verse['translation_en']}\n"
            f"🇮🇳 Hindi: {verse['translation_hi']}\n\n"
            f"✨ Meaning:\n{verse['expanded']}"
        )
    else:
        return "🎉 You’ve completed all 7 days of learning! Jai Hanuman 🙏"


# ------------------- Flask Routes -------------------
@app.route("/", methods=["GET"])
def index():
    return "Hanumanji Bot (healthy)", 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # GET -> verification handshake
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("✅ Webhook verified by Meta.")
            return challenge, 200
        else:
            return "Verification failed", 403

    # POST -> incoming events
    data = request.get_json()
    print("📩 Webhook received:", data)

    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0].get("value", {})

        # Ignore non-message events (e.g., statuses)
        if "messages" not in changes:
            print("ℹ️ Webhook event has no messages field (status update). Ignoring.")
            return "EVENT_RECEIVED", 200

        phone_number_id_from_payload = changes.get("metadata", {}).get("phone_number_id")
        phone_number_id = phone_number_id_from_payload or PHONE_NUMBER_ID
        if not phone_number_id:
            print("⚠️ No phone_number_id available (payload nor env). Can't send replies.")
            return "EVENT_RECEIVED", 200

        msg = changes["messages"][0]
        from_number_raw = msg.get("from", "")
        # message content: text or other types
        if "text" in msg and "body" in msg["text"]:
            message_text = msg["text"]["body"].strip()
        else:
            # handle button/interactive or unsupported types
            message_text = msg.get("type", "unsupported").strip()

        print(f"➡️ Message from {from_number_raw}: {message_text}")

        # Normalize numbers for comparison & storage
        from_number = normalize_number(from_number_raw)
        admin_clean = ADMIN_NUMBER_CLEAN

        # Auto-register if new (save as numeric string)
        if get_progress(from_number) is None:
            save_progress(from_number, 0)
            print(f"🆕 Registered new user: {from_number}")
            # Auto-send Day 1 immediately on first contact
            first_reply = get_next_message(from_number)
            send_whatsapp_message(phone_number_id, from_number, first_reply)
            return "EVENT_RECEIVED", 200

        # Admin commands (admin must match numeric-only)
        if admin_clean and from_number == admin_clean:
            # handle admin action
            reply = handle_admin_message(message_text, phone_number_id)
            send_whatsapp_message(phone_number_id, from_number, reply)
            print(f"📢 Admin command processed: {message_text}")
            return "EVENT_RECEIVED", 200

        # Normal user flow
        if message_text.lower() in ["start", "next"]:
            reply = get_next_message(from_number)
            send_whatsapp_message(phone_number_id, from_number, reply)
            print(f"📤 Sent verse to {from_number}")
        else:
            # polite help message
            send_whatsapp_message(phone_number_id, from_number, "🙏 Send 'start' to begin or 'next' for the next verse.")
            print(f"ℹ️ Help message sent to {from_number}")

    except Exception as e:
        print("⚠️ Error processing webhook:", e)

    return "EVENT_RECEIVED", 200


# Admin endpoint to manually trigger daily job (protected by VERIFY_TOKEN)
@app.route("/admin/trigger_daily", methods=["POST"])
def admin_trigger_daily():
    secret = request.args.get("secret", "")
    if secret != VERIFY_TOKEN:
        return "Forbidden", 403
    send_daily_verse()
    return "Triggered daily send", 200


# ------------------- Scheduler for Daily Push -------------------
def send_daily_verse():
    users = get_all_users()
    print(f"🔁 send_daily_verse: found {len(users)} users.")
    successes = 0
    failures = 0
    for phone in users:
        current_day = get_progress(phone) or 0
        next_day = current_day + 1
        if f"day{next_day}" in verses:
            verse = verses[f"day{next_day}"]
            save_progress(phone, next_day)
            msg = (
                f"☀️ Good Morning!\n📖 Day {next_day} Verse:\n\n"
                f"{verse['verse']}\n\n"
                f"🌐 English: {verse['translation_en']}\n"
                f"🇮🇳 Hindi: {verse['translation_hi']}\n\n"
                f"✨ Meaning:\n{verse['expanded']}"
            )
        else:
            msg = "🎉 You’ve completed all 7 days of learning! Jai Hanuman 🙏"

        status, body = send_whatsapp_message(PHONE_NUMBER_ID, phone, msg)
        if 200 <= status < 300:
            successes += 1
        else:
            failures += 1
            print(f"❌ Failed to send daily verse to {phone}: {status} {body}")

    print(f"🔁 Daily send finished. Successes: {successes}, Failures: {failures}")


# ------------------- Main -------------------
if __name__ == "__main__":
    init_db()

    # Daily scheduler (7 AM IST)
    scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Kolkata"))
    # production: keep cron(7:00)
    scheduler.add_job(send_daily_verse, "cron", hour=7, minute=0)
    # for quick tests: you can temporarily use interval:
    # scheduler.add_job(send_daily_verse, "interval", minutes=1)
    scheduler.start()

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
