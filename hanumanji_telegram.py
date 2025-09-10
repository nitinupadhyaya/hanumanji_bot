import os
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from verses import verses  # import from separate file

# ---------------- Config ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DB_FILE = "progress.db"

# ---------------- DB Helpers ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, day INTEGER)""")
    conn.commit()
    conn.close()

def get_progress(chat_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT day FROM users WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def save_progress(chat_id, day):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (chat_id, day) VALUES (?, ?)", (chat_id, day))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

# ---------------- Bot Logic ----------------
def get_next_message(chat_id):
    current_day = get_progress(chat_id)
    next_day = current_day + 1
    if f"day{next_day}" in verses:
        v = verses[f"day{next_day}"]
        save_progress(chat_id, next_day)
        return (
            f"📖 Day {next_day} Verse:\n\n"
            f"{v['verse']}\n\n"
            f"🌐 English: {v['translation_en']}\n"
            f"🇮🇳 Hindi: {v['translation_hi']}\n\n"
            f"✨ Meaning:\n{v['expanded']}"
        )
    else:
        return "🎉 You’ve completed all days of Hanuman Chalisa learning! Jai Hanuman 🙏"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    save_progress(chat_id, get_progress(chat_id))  # ensure user in DB
    await update.message.reply_text("🙏 Welcome! You will now start receiving daily verses.")
    await update.message.reply_text(get_next_message(chat_id))

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = " ".join(context.args)
    for user in get_all_users():
        try:
            await context.bot.send_message(chat_id=user, text=f"[Broadcast] {msg}")
        except Exception as e:
            print(f"⚠️ Could not send to {user}: {e}")
    await update.message.reply_text("✅ Broadcast sent.")

# ---------------- Scheduler ----------------
async def send_daily(context: ContextTypes.DEFAULT_TYPE):
    for user in get_all_users():
        msg = get_next_message(user)
        try:
            await context.bot.send_message(chat_id=user, text=msg)
        except Exception as e:
            print(f"⚠️ Could not send daily verse to {user}: {e}")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))

    scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Kolkata"))
    scheduler.add_job(lambda: app.job_queue.run_once(send_daily, 0), "cron", hour=7, minute=0)
    scheduler.start()

    app.run_polling()

if __name__ == "__main__":
    main()
