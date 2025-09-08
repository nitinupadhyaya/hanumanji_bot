import os
import sqlite3
import requests
from flask import Flask, request
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from verses import verses


# ------------------- Config -------------------
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")  # must match what you set in Meta dashboard
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")  # from Meta → System User token
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID")  # from Meta WhatsApp Business
ADMIN_NUMBER = os.environ.get("ADMIN_NUMBER")  # e.g. "9195409xxxx"

META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN") 
PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_ID")


GRAPH_API_URL = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"

app = Flask(__name__)
DB_FILE = "progress.db"

# ------------------- DB Helpers -------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (phone TEXT PRIMARY KEY, day INTEGER)''')
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

# ------------------- Messaging Helpers -------------------
def send_whatsapp_message(phone_number_id, to_number, message_text):
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "text": {"body": message_text}
    }
    response = requests.post(url, headers=headers, json=payload)
    print("📤 Sent:", response.status_code, response.text)


def handle_admin_message(incoming_msg, phone_number_id):
    incoming_msg = incoming_msg.strip()

    if incoming_msg.lower().startswith("broadcast "):
        broadcast_msg = incoming_msg[len("broadcast "):].strip()

        # Fetch all users
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT phone FROM users")
        users = [row[0] for row in c.fetchall()]
        conn.close()

        # Send broadcast
        for u in users:
            send_whatsapp_message(phone_number_id, u, f"[Broadcast] {broadcast_msg}")

        return "✅ Broadcast sent!"

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
        phone_number_id = changes["metadata"]["phone_number_id"]

        # ✅ Check if this event contains a message
        if "messages" in changes:
            from_number = changes["messages"][0]["from"]   # e.g., "919540964715"
            message_text = changes["messages"][0]["text"]["body"].strip()

            # Admin check (normalize)
            if from_number == ADMIN_NUMBER.replace("whatsapp:", ""):
                print("👑 Admin detected")
                response = handle_admin_message(message_text, phone_number_id)
                send_whatsapp_message(phone_number_id, from_number, response)
                return "EVENT_RECEIVED", 200

            # ✅ Normal user logic
            if message_text.lower() in ["start", "next"]:
                msg = get_next_message(from_number)
            else:
                msg = "🙏 Send *start* to begin or *next* for the next verse."

            send_whatsapp_message(phone_number_id, from_number, msg)

        else:
            print("ℹ️ Webhook event has no messages field (maybe status update). Ignoring.")

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

        # Send via Meta API (using your phone_number_id — pick first user’s metadata later)
        # For now, use a fixed phone_number_id (you can store it as ENV)
        PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
        if PHONE_NUMBER_ID:
            send_whatsapp_message(PHONE_NUMBER_ID, phone, msg)
        else:
            print("⚠️ PHONE_NUMBER_ID not set, skipping daily verse send.")

# ------------------- Main -------------------
if __name__ == "__main__":
    init_db()

    # Daily scheduler (7 AM IST)
    scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Kolkata"))
    scheduler.add_job(send_daily_verse, "cron", hour=7, minute=0)
    scheduler.start()

    # Run Flask app (Railway exposes automatically)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
