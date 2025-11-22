# handlers/delcard.py
import sqlite3
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import app, OWNER_ID, ADMINS

DB_PATH = "waifu_bot.db"

def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


# /deletecard <id>
@app.on_message(filters.command("deletecard") & filters.user([OWNER_ID] + ADMINS))
async def delete_card_request(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("⚠️ Usage: `/deletecard <waifu_id>`", quote=True)
        return

    wid = args[1].strip()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, anime, rarity, media_type, media_file FROM waifu_cards WHERE id=?", (wid,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await message.reply_text("❌ Waifu card not found.")
        return

    wid, name, anime, rarity, media_type, media_file = row
    caption = (
        f"🆔 ID: {wid}\n"
        f"👤 Name: {name}\n"
        f"🤝 Anime: {anime}\n"
        f"❄️ Rarity: {rarity}\n\n"
        f"⚠️ Are you sure you want to delete this card?"
    )

    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Confirm Delete", callback_data=f"confirmdel_{wid}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"canceldel_{wid}")
        ]]
    )

    if media_type in ("photo", "image"):
        await message.reply_photo(media_file, caption=caption, reply_markup=keyboard)
    elif media_type in ("video", "animation"):
        await message.reply_video(media_file, caption=caption, reply_markup=keyboard)
    else:
        await message.reply_text(caption, reply_markup=keyboard)


# Confirm or Cancel
@app.on_callback_query(filters.regex(r"^(confirmdel|canceldel)_(\d+)$"))
async def delete_card_confirm(client, cq: CallbackQuery):
    action, wid = cq.data.split("_")
    wid = int(wid)

    if cq.from_user.id not in [OWNER_ID] + ADMINS:
        await cq.answer("🚫 You are not allowed to do this.", show_alert=True)
        return

    if action == "canceldel":
        await cq.message.edit_caption("❌ Deletion cancelled.")
        return

    # Confirm delete
    conn = _conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM waifu_cards WHERE id=?", (wid,))
    conn.commit()
    conn.close()

    await cq.message.edit_caption(f"✅ Waifu card ID {wid} deleted permanently.")
