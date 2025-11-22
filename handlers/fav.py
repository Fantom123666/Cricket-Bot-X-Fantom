# handlers/fav.py

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from config import app
from database import Database

db = Database()

# ---------------- /fav Command ----------------
@app.on_message(filters.command("fav"))
async def set_favorite(client, message: Message):
    """
    Usage: /fav <waifu_id>
    """
    try:
        user_id = message.from_user.id
        username = message.from_user.first_name
        text = message.text.split(" ", 1)[1].strip()
        waifu_id = int(text)
    except (IndexError, ValueError):
        await message.reply_text("❌ Usage: /fav <waifu_id>")
        return

    # Ensure tables exist
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
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_fav (
            user_id INTEGER PRIMARY KEY,
            waifu_id INTEGER
        )
    """)
    db.conn.commit()

    # Fetch waifu card
    db.cursor.execute("SELECT * FROM waifu_cards WHERE id = ?", (waifu_id,))
    waifu = db.cursor.fetchone()
    if not waifu:
        await message.reply_text("❌ Waifu card not found!")
        return

    # Map columns safely
    waifu_data = dict(zip([desc[0] for desc in db.cursor.description], waifu))
    waifu_id = waifu_data["id"]
    name = waifu_data["name"]
    anime = waifu_data["anime"]
    rarity = waifu_data["rarity"]
    event = waifu_data["event"]
    media_type = waifu_data["media_type"]
    media_file = waifu_data["media_file"]

    # Prepare preview caption
    caption = (
        f"🌸 Favorite Waifu Preview 🌸\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 𝐖𝐚𝐢𝐟𝐮 𝐈𝐃: {waifu_id}\n"
        f"✨ 𝐍𝐚𝐦𝐞: {name}\n"
        f"⛩️ 𝐀𝐧𝐢𝐦𝐞: {anime}\n"
        f"💖 𝐑𝐚𝐫𝐢𝐭𝐲: {rarity}\n"
        f"🎀 𝐄𝐯𝐞𝐧𝐭/𝐓𝐡𝐞𝐦𝐞: {event}\n"
        f"🕊️ Requested by: {username}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Do you want to set this as your favorite waifu?"
    )

    # Inline buttons for confirmation
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"fav_confirm|{user_id}|{waifu_id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"fav_decline|{user_id}")
        ]
    ])

    # Send media preview
    if media_type == "photo":
        await message.reply_photo(media_file, caption=caption, reply_markup=buttons)
    else:
        await message.reply_video(media_file, caption=caption, reply_markup=buttons)


# ---------------- Callback Handler ----------------
@app.on_callback_query(filters.regex(r"^fav_"))
async def fav_callback(client, callback):
    data = callback.data.split("|")
    action = data[0]

    if action == "fav_confirm":
        user_id = int(data[1])
        waifu_id = int(data[2])
        # Save favorite in user_fav table (insert or replace)
        db.cursor.execute("REPLACE INTO user_fav (user_id, waifu_id) VALUES (?, ?)", (user_id, waifu_id))
        db.conn.commit()
        await callback.answer("💞 Favorite waifu set successfully!", show_alert=True)
        await callback.message.delete()

    elif action == "fav_decline":
        await callback.answer("❌ Favorite waifu selection cancelled.", show_alert=True)
        await callback.message.delete()
