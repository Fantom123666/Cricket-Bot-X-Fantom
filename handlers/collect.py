# handlers/collect.py

import sqlite3
from pyrogram import filters
from pyrogram.types import Message
from config import Config, app

DB_PATH = "waifu_bot.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# ---------------- /collect Command ----------------
@app.on_message(filters.command("collect") & filters.group)
async def collect_card(client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Get current drop
    try:
        cursor.execute("SELECT waifu_id, collected_by FROM current_drops WHERE chat_id=?", (chat_id,))
        row = cursor.fetchone()
        if not row:
            await message.reply_text("❌ No active card to collect right now. Please wait for the next drop.")
            return
    except Exception as e:
        print(f"❌ Error fetching current drop: {e}")
        return

    waifu_id, collected_by = row
    if collected_by is not None:
        await message.reply_text("❌ This card has already been collected by someone else!")
        return

    # Parse user's guess
    try:
        guess = message.text.split(" ", 1)[1].strip().lower()
    except IndexError:
        await message.reply_text("❌ Usage: /collect <waifu_name>")
        return

    # Fetch card info
    try:
        cursor.execute(
            "SELECT id, name, anime, rarity, event, media_type, media_file FROM waifu_cards WHERE id=?",
            (waifu_id,)
        )
        card = cursor.fetchone()
        if not card:
            return
    except Exception as e:
        print(f"❌ Error fetching card info: {e}")
        return

    # Partial match check
    if guess in card[1].lower():
        # Mark as collected
        cursor.execute(
            "UPDATE current_drops SET collected_by=? WHERE chat_id=?",
            (user_id, chat_id)
        )
        conn.commit()

        # Save to user's collection
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_waifus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                waifu_id INTEGER,
                amount INTEGER DEFAULT 1
            )
        """)
        cursor.execute("SELECT amount FROM user_waifus WHERE user_id=? AND waifu_id=?", (user_id, waifu_id))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE user_waifus SET amount=amount+1 WHERE user_id=? AND waifu_id=?", (user_id, waifu_id))
        else:
            cursor.execute("INSERT INTO user_waifus (user_id, waifu_id, amount) VALUES (?, ?, 1)", (user_id, waifu_id))
        conn.commit()

        # Confirmation message
        text = (
            f"🔮✨ C A R D C O L L E C T E D ! ✨🔮\n"
            f"🆔 Waifu ID: {card[0]}\n"
            f"👤 Name: {card[1]}\n"
            f"⛩️ Anime: {card[2]}\n"
            f"❄️ Rarity: {card[3]}\n"
            f"🎀 Event/Theme: {card[4]}\n\n"
            f"🧿 Your collection just became stronger! 🧿\n"
            f"📚 Type /inventory to view your entire collection~ 🌸"
        )
        if card[5] == "photo":
            await message.reply_photo(card[6], caption=text)
        else:
            await message.reply_video(card[6], caption=text)
    else:
        await message.reply_text("❌ Incorrect guess! Try again before someone else collects it.")
