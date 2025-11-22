# handlers/checkwaifu.py
from pyrogram import filters
from pyrogram.types import Message
from config import app
from database import Database

db = Database()

# ---------------- /checkwaifu Command ----------------
@app.on_message(filters.command("checkwaifu"))
async def check_waifu(client, message: Message):
    """
    Usage: /checkwaifu <waifu_id>
    """
    try:
        waifu_id = int(message.text.split(" ", 1)[1])
    except (IndexError, ValueError):
        await message.reply_text("❌ Usage: /checkwaifu <waifu_id>")
        return

    # Ensure waifu_cards table exists
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS waifu_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            anime TEXT,
            rarity TEXT,
            event TEXT,
            media_type TEXT,
            media_file TEXT
        )
    """)
    db.conn.commit()

    # Fetch waifu details
    db.cursor.execute("SELECT * FROM waifu_cards WHERE id=?", (waifu_id,))
    waifu = db.cursor.fetchone()

    if not waifu:
        await message.reply_text("❌ Waifu not found!")
        return

    # Count how many times collected globally
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_waifus (
            user_id INTEGER,
            waifu_id INTEGER,
            PRIMARY KEY(user_id, waifu_id)
        )
    """)
    db.conn.commit()
    db.cursor.execute("SELECT COUNT(*) FROM user_waifus WHERE waifu_id=?", (waifu_id,))
    collected_count = db.cursor.fetchone()[0]

    # Build caption
    caption = (
        f"👤 Name: {waifu[1]}\n"
        f"🎥 Anime: {waifu[2]}\n"
        f"🫧 Rarity: {waifu[3]}\n"
        f"🎀 Event/Theme: {waifu[4]}\n"
        f"🆔 Waifu ID: {waifu[0]}\n"
        f"☘️ Globally Collected: {collected_count}"
    )

    # Send media with caption
    if waifu[5] == "photo":
        await message.reply_photo(waifu[6], caption=caption)
    elif waifu[5] == "video":
        await message.reply_video(waifu[6], caption=caption)
    else:
        await message.reply_text(caption)
