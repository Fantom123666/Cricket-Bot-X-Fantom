# handlers/partner.py
from main import app
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import Database

db = Database()


def _choose_media_and_send(client, chat_id, waifu_row, caption):
    """
    waifu_row expected columns (from waifu_cards):
      id, name, anime, rarity, event, media_type, media_file, media_file_id
    media_type may be NULL depending on your DB (we handle gracefully).
    """
    # Normalize row values (use indices to avoid depending on DB helper)
    try:
        wid = waifu_row[0]
        name = waifu_row[1]
        anime = waifu_row[2]
        rarity = waifu_row[3]
        event = waifu_row[4] if len(waifu_row) > 4 else None
        media_type = waifu_row[5] if len(waifu_row) > 5 else None
        media_file = waifu_row[6] if len(waifu_row) > 6 else None
        media_file_id = waifu_row[7] if len(waifu_row) > 7 else None
    except Exception:
        # fallback: try to use available fields
        media_type = waifu_row[5] if len(waifu_row) > 5 else None
        media_file = waifu_row[6] if len(waifu_row) > 6 else None
        media_file_id = waifu_row[7] if len(waifu_row) > 7 else None

    media = media_file_id or media_file

    # Try to send according to media_type, fallback to photo, then to text
    async def _send():
        if media_type == "video":
            if media:
                await client.send_video(chat_id, media, caption=caption)
            else:
                # no media available
                await client.send_message(chat_id, caption)
        else:
            # default to photo
            if media:
                try:
                    await client.send_photo(chat_id, media, caption=caption)
                except Exception:
                    # try as video if fails
                    try:
                        await client.send_video(chat_id, media, caption=caption)
                    except Exception:
                        await client.send_message(chat_id, caption)
            else:
                await client.send_message(chat_id, caption)

    return _send()


# ---------------- /partner - show current favorite ----------------
@app.on_message(filters.command("partner"))
async def partner_handler(client, message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # ensure the user exists
    db.add_user(user_id, message.from_user.username if message.from_user.username else None)

    # fetch favorite waifu id
    db.cursor.execute("SELECT waifu_id FROM user_fav WHERE user_id = ?", (user_id,))
    row = db.cursor.fetchone()
    if not row or not row[0]:
        await message.reply_text("💔 You don't have a partner set. Use your collection to set a favorite waifu first.")
        return

    fav_id = row[0]

    # fetch full waifu details from waifu_cards
    db.cursor.execute("""
        SELECT id, name, anime, rarity, event, media_type, media_file, media_file_id
        FROM waifu_cards
        WHERE id = ?
    """, (fav_id,))
    waifu = db.cursor.fetchone()
    if not waifu:
        # data inconsistency: favorite points to missing card
        await message.reply_text("⚠️ Your favorite waifu is set but the card data couldn't be found. Try /divorce to unset.")
        return

    # fetch how many the user owns of this waifu
    db.cursor.execute("SELECT amount FROM user_waifus WHERE user_id = ? AND waifu_id = ?", (user_id, fav_id))
    amt_row = db.cursor.fetchone()
    owned = amt_row[0] if amt_row else 0

    # build caption
    wid, name, anime, rarity, event = waifu[0], waifu[1], waifu[2], waifu[3], waifu[4]
    caption_lines = [
        f"💞 Your Partner Waifu",
        "━━━━━━━━━━━━━━",
        f"📛 ID: {wid}",
        f"💠 Name: {name}",
        f"🎬 Anime: {anime or '—'}",
        f"✨ Rarity: {rarity or '—'}",
        f"🎭 Theme: {event or '—'}",
        f"🧾 Owned: {owned}×",
    ]
    caption = "\n".join(caption_lines)

    # send media (photo/video) or fallback to message
    try:
        await _choose_media_and_send(client, chat_id, waifu, caption)
    except Exception:
        # final fallback
        await message.reply_text(caption)


# ---------------- /divorce - unset favorite ----------------
@app.on_message(filters.command("divorce"))
async def divorce_handler(client, message):
    user_id = message.from_user.id

    # check if favorite exists
    db.cursor.execute("SELECT waifu_id FROM user_fav WHERE user_id = ?", (user_id,))
    row = db.cursor.fetchone()
    if not row or not row[0]:
        await message.reply_text("❌ You don't have a favorite waifu set.")
        return

    # remove favorite entry
    db.cursor.execute("DELETE FROM user_fav WHERE user_id = ?", (user_id,))
    db.conn.commit()

    # log the removal
    try:
        db.log_event("favorite_removed", user_id=user_id, details=f"divorced waifu_id={row[0]}")
    except Exception:
        pass

    await message.reply_text("💔 Your favorite waifu has been removed. You're now free to choose another partner.")
