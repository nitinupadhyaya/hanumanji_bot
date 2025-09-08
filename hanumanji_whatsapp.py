import os
import sqlite3
import requests
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from verses import verses


# ------------------- Config -------------------
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID")
ADMIN_NUMBER = os.environ.get("ADMIN_NUMBER")  # e.g. "9195409xxxx"
ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")

GRAPH_API_URL = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"

app = Flask(__name__)
DB_FILE = "progress.db"

# ------------------- DB Helpers -------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS users
           (phone TEXT PRIMARY KEY, day INTEGER)"""
    )
    conn.commit()
    conn.close()

def get_progress(phone):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT day FROM users WHERE phone=?", (phone,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

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

def add_user_if_new(phone):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT phone FROM users WHERE phone=?", (phone,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (phone, day) VALUES (?, ?)", (phone, 0))
        conn.commit()
        print(f"🆕 Added new user: {phone}")
    conn.close()

# ------------------- Messaging Helpers -------------------
def send_whatsapp_message(phone_number_id, to_number, message_text):
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "text": {"body": message_text},
    }
    response = requests.post(url, headers=headers, json=payload)
    print("📤 Sent:", response.status_code, response.text)

def handle_admin_message(incoming_msg, phone_number_id):
    incoming_msg = incoming_msg.strip()

    if incoming_msg.lower().startswith("broadcast "):
        broadcast_msg = incoming_msg[len("broadcast "):].strip()

        users = get_all_users()
        for u in users:
            send_whatsapp_message(phone_number_id, u, f"[Broadcast] {broadcast_msg}")

        return "✅ Broadcast sent!"
    else:
        return "❌ Admin command not recognized."

# ------------------- Learning Logic -------------------
def get_next_message(phone):
    current_day = get_progress(phone)
    next_day = current_day + 1

    if f"day{next_day}" in verses:
        verse = verses[f"day{next_day}"]
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
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📩 Webhook received:", data)

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]["value"]

        if "messages" not in changes:
            print("ℹ️ Webhook event has no messages field (maybe status update). Ignoring.")
            return "EVENT_RECEIVED", 200

        phone_number_id = changes["metadata"]["phone_number_id"]
        from_number = changes["messages"][0]["from"]
        message_text = changes["messages"][0]["text"]["body"].strip()

        # Normalize numbers
        clean_from = from_number.lstrip("+")
        clean_admin = ADMIN_NUMBER.lstrip("+")

        # ✅ If admin → handle only admin commands
        if clean_from == clean_admin:
            reply = handle_admin_message(message_text, phone_number_id)
            send_whatsapp_message(phone_number_id, from_number, reply)
            print(f"📢 Admin command processed: {message_text}")
            return "EVENT_RECEIVED", 200

        # ✅ Normal user flow
        add_user_if_new(from_number)
        verse = get_next_message(from_number)
        send_whatsapp_message(phone_number_id, from_number, verse)
        print(f"📤 Sent verse to {from_number}")

    except Exception as e:
        print("⚠️ Error processing webhook:", e)

    return "EVENT_RECEIVED", 200

# ------------------- Scheduler for Daily Push -------------------
def send_daily_verse():
    users = get_all_users()
    for phone in users:
        current_day = get_progress(phone)
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

        send_whatsapp_message(WHATSAPP_PHONE_ID, phone, msg)

# ------------------- Main -------------------
if __name__ == "__main__":
    init_db()

    scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Kolkata"))
    scheduler.add_job(send_daily_verse, "cron", hour=7, minute=0)
    scheduler.start()

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
