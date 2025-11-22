# handlers/stats.py

from pyrogram import filters
from config import app, Config
from database import Database

db = Database()

@app.on_message(filters.command("stats"))
async def stats_cmd(client, message):
    user_id = message.from_user.id

    # ----------------- Owner Only -----------------
    if user_id != Config.OWNER_ID:
        await message.reply_text("❌ This command is **Owner only**.")
        return

    # ----------------- Fetch Stats -----------------
    # Total users
    db.cursor.execute("SELECT COUNT(*) FROM users")
    total_users = db.cursor.fetchone()[0]

    # Total groups
    total_groups = db.get_total_groups()

    # ----------------- Prepare & Send Message -----------------
    stats_text = f"""
📊 **Bot Stats**

👥 Total Users: {total_users}
👑 Total Groups Bot Added: {total_groups}
"""
    await message.reply_text(stats_text)
