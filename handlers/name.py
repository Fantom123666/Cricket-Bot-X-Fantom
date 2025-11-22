"""
name.py

Reveal a dropped waifu name when a user replies to the dropped photo/video.

Behavior:
- Triggered when a user replies to a message that contains a photo or video.
- Looks up the replied message (chat_id + message_id) in active_drops.
- Fetches waifu info from waifu_cards (falls back to waifus).
- Replies with the revealed card info and marks the drop as revealed.

Integration:
- If you already have a pyrogram.Client in your project:
    from name import reveal_on_reply
    client.add_handler(MessageHandler(reveal_on_reply, filters.reply))
  or decorate your own handler.
- If you want to run standalone: export BOT_TOKEN and run this file.

Note:
- This version avoids conditional decorators (fixes the 'NoneType' error).
- It ignores edited messages by checking message.edit_date.
"""

import os
import sqlite3
import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.handlers import MessageHandler

DB_PATH = os.getenv("WAIFU_DB_PATH", "waifu_bot.db")
BOT_TOKEN = os.getenv("BOT_TOKEN")  # optional; if not set, file is meant for import/integration

# Do not raise on missing DB so integration won't crash at import time.
if not os.path.exists(DB_PATH):
    print(f"Warning: database not found at '{DB_PATH}'. Set WAIFU_DB_PATH or place DB there.")

# Create a Client only if BOT_TOKEN is provided (standalone mode). Otherwise app is None (integration mode).
app = Client("waifu_revealer", bot_token=BOT_TOKEN) if BOT_TOKEN else None


def get_active_drop_for_message(chat_id: int, message_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT waifu_id, revealed, revealed_by, revealed_at FROM active_drops WHERE chat_id=? AND message_id=?",
        (chat_id, message_id),
    )
    row = c.fetchone()
    conn.close()
    return row


def fetch_waifu_info(waifu_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, anime, rarity FROM waifu_cards WHERE id=?", (waifu_id,))
    row = c.fetchone()
    if row:
        conn.close()
        return row
    c.execute("SELECT name, anime, rarity FROM waifus WHERE id=?", (waifu_id,))
    row = c.fetchone()
    conn.close()
    return row


def mark_drop_revealed(chat_id: int, message_id: int, revealer_user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now_iso = datetime.datetime.utcnow().isoformat()
    c.execute(
        "UPDATE active_drops SET revealed=1, revealed_by=?, revealed_at=? WHERE chat_id=? AND message_id=?",
        (revealer_user_id, now_iso, chat_id, message_id),
    )
    conn.commit()
    conn.close()


async def reveal_on_reply(client: Client, message: Message):
    """
    Handler: reveal waifu when a user replies to a dropped photo/video.
    Note: this function is not auto-registered here if you integrate the file — register it yourself.
    """
    # Ignore edited messages
    if getattr(message, "edit_date", None):
        return

    if not message.reply_to_message:
        return

    replied = message.reply_to_message

    # Only act if the replied message has a photo or video
    if not (replied.photo or replied.video):
        return

    chat_id = replied.chat.id
    message_id = replied.message_id

    active = get_active_drop_for_message(chat_id, message_id)
    if not active:
        return  # not a tracked drop

    waifu_id, revealed, revealed_by, revealed_at = active

    if revealed:
        try:
            txt = "🔎 This drop was already revealed."
            if revealed_by:
                txt += f"\nRevealed by user id: `{revealed_by}`"
            if revealed_at:
                txt += f"\nAt: `{revealed_at}` (UTC)"
            await message.reply_text(txt, quote=True)
        except Exception:
            pass
        return

    info = fetch_waifu_info(waifu_id)
    if not info:
        await message.reply_text("⚠️ Could not find the waifu in the database.", quote=True)
        return

    name, anime, rarity = info
    anime = anime or "—"
    rarity = rarity or "—"

    reveal_text = (
        f"🎴 *Revealed waifu card!*\n\n"
        f"*Name:* {name}\n"
        f"*Anime:* {anime}\n"
        f"*Rarity:* {rarity}"
    )

    # Reply to the dropped message for clarity
    try:
        await replied.reply_text(reveal_text, parse_mode="markdown")
    except Exception:
        await message.reply_text(reveal_text, parse_mode="markdown", quote=True)

    try:
        mark_drop_revealed(chat_id, message_id, message.from_user.id if message.from_user else None)
    except Exception as e:
        print("Failed to update active_drops:", e)


# If running standalone with BOT_TOKEN, register the handler and run the client.
if app:
    app.add_handler(MessageHandler(reveal_on_reply, filters.reply))
    if __name__ == "__main__":
        app.run()
