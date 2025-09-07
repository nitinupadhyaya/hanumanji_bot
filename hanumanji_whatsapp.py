import os
import sqlite3
from flask import Flask, request
from twilio.rest import Client
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from verses import verses

# ------------------- Config -------------------
ADMIN_NUMBER = os.environ.get("ADMIN_NUMBER")  # e.g. whatsapp:+9195409xxxx
account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
twilio_whatsapp = os.environ.get("TWILIO_WHATSAPP")  # "whatsapp:+14155238886"

client = Client(account_sid, auth_token)
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

# ------------------- Admin Handler -------------------
def handle_admin_message(incoming_msg):
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
            client.messages.create(
                body=f"[Broadcast] {broadcast_msg}",
                from_=twilio_whatsapp,
                to=u
            )
        return "✅ Broadcast sent!"

    return "❌ Admin command not recognized."

# ------------------- Flask Routes -------------------
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        # Meta verification
        verify_token = "manthantoken"  # must match what you enter in Meta Dashboard
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if token == verify_token:
            return challenge, 200
        return "Verification failed", 403

    elif request.method == "POST":
        data = request.get_json()
        print("📩 Incoming:", data)
        # here you’ll parse the WhatsApp messages
        return "OK", 200


# ------------------- Scheduler for Daily Push -------------------
def send_daily_verse():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT phone, day FROM users")
    users = c.fetchall()
    conn.close()

    for phone, day in users:
        next_day = day + 1
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

        client.messages.create(
            body=msg,
            from_=twilio_whatsapp,
            to=phone
        )

# ------------------- Main -------------------
if __name__ == "__main__":
    init_db()

    # Daily scheduler (7 AM IST)
    scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Kolkata"))
    scheduler.add_job(send_daily_verse, "cron", hour=7, minute=0)
    scheduler.start()

    # Run Flask app (Railway exposes automatically)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

