# handlers/give.py

from pyrogram import filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import Config, app
from database import Database

db = Database()

# ---------------- /give command ----------------
@app.on_message(filters.command("give") & filters.user(Config.OWNER_ID))
async def give_card_cmd(client, message: Message):
    """
    Owner replies to a user message with: /give <waifu_id>
    Shows a preview with confirm/cancel buttons
    """
    if not message.reply_to_message:
        await message.reply_text("❌ You must reply to a user message to give a card.")
        return

    try:
        waifu_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.reply_text("❌ Usage: /give <waifu_id>")
        return

    target_user = message.reply_to_message.from_user
    target_user_id = target_user.id

    # Fetch card from DB
    db.cursor.execute("""
        SELECT id, name, anime, rarity, event, media_type, media_file
        FROM waifu_cards WHERE id=?
    """, (waifu_id,))
    card = db.cursor.fetchone()

    if not card:
        await message.reply_text("❌ Card not found in database.")
        return

    card_info = {
        "id": card[0],
        "name": card[1],
        "anime": card[2],
        "rarity": card[3],
        "event": card[4],
        "media_type": card[5],
        "media_file": card[6]
    }

    # Buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"give:confirm:{target_user_id}:{waifu_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"give:cancel:{target_user_id}:{waifu_id}")
        ]
    ])

    # Caption
    caption = (
        f"🎁 Owner wants to give a card to {target_user.first_name} ({target_user_id})\n\n"
        f"🆔 Waifu ID: {card_info['id']}\n"
        f"👤 Name: {card_info['name']}\n"
        f"⛩️ Anime: {card_info['anime']}\n"
        f"❄️ Rarity: {card_info['rarity']}\n"
        f"🎀 Event/Theme: {card_info['event']}"
    )

    # Send preview
    if card_info["media_type"] == "photo":
        await message.reply_photo(card_info["media_file"], caption=caption, reply_markup=buttons)
    else:
        await message.reply_video(card_info["media_file"], caption=caption, reply_markup=buttons)


# ---------------- Callback handler ----------------
@app.on_callback_query(filters.regex(r"^give:(confirm|cancel):\d+:\d+$"))
async def give_callback(client, callback_query: CallbackQuery):
    try:
        parts = callback_query.data.split(":")
        action = parts[1]           # 'confirm' or 'cancel'
        target_user_id = int(parts[2])
        waifu_id = int(parts[3])
    except Exception:
        await callback_query.answer("❌ Invalid callback data.", show_alert=True)
        return

    # Only owner can confirm/cancel
    if callback_query.from_user.id != Config.OWNER_ID:
        await callback_query.answer("❌ Only owner can confirm/cancel.", show_alert=True)
        return

    # Fetch card
    db.cursor.execute("""
        SELECT id, name, anime, rarity, event, media_type, media_file
        FROM waifu_cards WHERE id=?
    """, (waifu_id,))
    card = db.cursor.fetchone()
    if not card:
        await callback_query.answer("❌ Card not found.", show_alert=True)
        return

    card_info = {
        "id": card[0],
        "name": card[1],
        "anime": card[2],
        "rarity": card[3],
        "event": card[4],
        "media_type": card[5],
        "media_file": card[6]
    }

    if action == "confirm":
        # Add to user collection
        db.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_waifus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                waifu_id INTEGER,
                amount INTEGER DEFAULT 1
            )
        """)
        db.cursor.execute("SELECT amount FROM user_waifus WHERE user_id=? AND waifu_id=?", (target_user_id, waifu_id))
        row = db.cursor.fetchone()
        if row:
            db.cursor.execute("UPDATE user_waifus SET amount=amount+1 WHERE user_id=? AND waifu_id=?", (target_user_id, waifu_id))
        else:
            db.cursor.execute("INSERT INTO user_waifus (user_id, waifu_id, amount) VALUES (?, ?, 1)", (target_user_id, waifu_id))
        db.conn.commit()

        # Send card to user privately
        caption = (
            f"🔮✨ C A R D G I V E N ! ✨🔮\n\n"
            f"🆔 Waifu ID: {card_info['id']}\n"
            f"👤 Name: {card_info['name']}\n"
            f"⛩️ Anime: {card_info['anime']}\n"
            f"❄️ Rarity: {card_info['rarity']}\n"
            f"🎀 Event/Theme: {card_info['event']}"
        )

        try:
            if card_info["media_type"] == "photo":
                await client.send_photo(target_user_id, card_info["media_file"], caption=caption)
            else:
                await client.send_video(target_user_id, card_info["media_file"], caption=caption)
        except:
            await callback_query.message.edit_text("❌ Failed to send media to user.")

        await callback_query.message.edit_text(f"✅ Card successfully given to {target_user_id}!")
        await callback_query.answer("✅ Card given!")

    else:  # cancel
        await callback_query.message.edit_text("❌ Card giving cancelled.")
        await callback_query.answer("❌ Cancelled")
