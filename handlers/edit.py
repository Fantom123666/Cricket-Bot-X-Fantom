from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import sqlite3
import random
import string
from config import app, OWNER_ID, ADMINS

DB_PATH = "waifu_bot.db"

# in-memory storage for long callback data
pending_edits = {}  # {short_id: (card_id, media_type, file_id)}

# helper to generate short IDs
def gen_short_id(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

# helper to check admin/owner
def is_admin(user_id):
    return user_id == OWNER_ID or user_id in ADMINS

# helper to check if a column exists
def column_exists(conn, table, column):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    columns = [info[1] for info in cur.fetchall()]
    return column in columns

@app.on_message(filters.command("editcard") & filters.user([OWNER_ID] + ADMINS))
async def edit_card_request(client, message):
    args = message.text.split(maxsplit=3)
    if len(args) < 2:
        await message.reply("❌ Usage:\n/editcard <waifu_id> [field] [new_value]\nFields: name, anime, rarity, theme, photo")
        return

    wid = args[1]

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    has_theme = column_exists(conn, "waifu_cards", "theme")

    try:
        if has_theme:
            cur.execute("SELECT id, name, anime, rarity, theme, media_type, media_file FROM waifu_cards WHERE id=?", (wid,))
        else:
            cur.execute("SELECT id, name, anime, rarity, media_type, media_file FROM waifu_cards WHERE id=?", (wid,))
        row = cur.fetchone()
    except Exception as e:
        await message.reply(f"❌ Database error: {e}")
        conn.close()
        return

    if not row:
        await message.reply("❌ No card found with this ID.")
        conn.close()
        return

    if has_theme:
        card_id, name, anime, rarity, theme, media_type, media_file = row
    else:
        card_id, name, anime, rarity, media_type, media_file = row
        theme = "N/A"

    # if only ID provided → show current card preview
    if len(args) == 2 and not message.reply_to_message:
        preview = (
            f"🆔 ID: {card_id}\n"
            f"👤 Name: {name}\n"
            f"📺 Anime: {anime}\n"
            f"❄️ Rarity: {rarity}\n"
            f"🎨 Theme: {theme}"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm Edit", callback_data=f"edit_confirm:{card_id}"),
                                    InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")]])
        if media_type == "video":
            await message.reply_video(media_file, caption=preview, reply_markup=kb)
        else:
            await message.reply_photo(media_file, caption=preview, reply_markup=kb)
        conn.close()
        return

    # editing field
    field = args[2].lower() if len(args) >= 3 else None

    # special case for photo/video update
    if field == "photo" and message.reply_to_message and (message.reply_to_message.photo or message.reply_to_message.video):
        media_type = "video" if message.reply_to_message.video else "photo"
        media_file = message.reply_to_message.video.file_id if media_type == "video" else message.reply_to_message.photo.file_id

        short_id = gen_short_id()
        pending_edits[short_id] = (card_id, media_type, media_file)

        preview = (
            f"🆔 ID: {card_id}\n"
            f"👤 Name: {name}\n"
            f"📺 Anime: {anime}\n"
            f"❄️ Rarity: {rarity}\n"
            f"🎨 Theme: {theme}\n\n"
            f"⚡ Updating image/video..."
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"edit_media:{short_id}"),
                                    InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")]])
        if media_type == "video":
            await message.reply_video(media_file, caption=preview, reply_markup=kb)
        else:
            await message.reply_photo(media_file, caption=preview, reply_markup=kb)
        conn.close()
        return

    if len(args) < 4:
        await message.reply("❌ Missing new value. Example:\n/editcard 1 name NewName")
        conn.close()
        return

    new_value = args[3]

    allowed_fields = ["name", "anime", "rarity", "photo"]
    if has_theme:
        allowed_fields.append("theme")

    if field not in allowed_fields:
        await message.reply(f"❌ Invalid field. Use one of: {', '.join(allowed_fields)}")
        conn.close()
        return

    preview = (
        f"🆔 ID: {card_id}\n"
        f"👤 Name: {name if field != 'name' else new_value}\n"
        f"📺 Anime: {anime if field != 'anime' else new_value}\n"
        f"❄️ Rarity: {rarity if field != 'rarity' else new_value}\n"
        f"🎨 Theme: {theme if field != 'theme' else new_value}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"edit_apply:{card_id}:{field}:{new_value}"),
                                InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")]])
    if media_type == "video":
        await message.reply_video(media_file, caption=preview, reply_markup=kb)
    else:
        await message.reply_photo(media_file, caption=preview, reply_markup=kb)

    conn.close()


# normal field edits
@app.on_callback_query(filters.regex(r"^edit_apply:(\d+):(\w+):(.+)"))
async def apply_edit(client, callback_query):
    wid, field, value = callback_query.data.split(":", 2)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    has_theme = column_exists(conn, "waifu_cards", "theme")

    try:
        if field == "theme" and not has_theme:
            await callback_query.message.reply("❌ Cannot update theme: column does not exist in database.")
            return
        cur.execute(f"UPDATE waifu_cards SET {field}=? WHERE id=?", (value, wid))
        conn.commit()
        await callback_query.message.edit_caption(f"✅ Card {wid} updated successfully!")
    except Exception as e:
        await callback_query.message.reply(f"❌ Update failed: {e}")
    finally:
        conn.close()


# photo/video edits using short_id
@app.on_callback_query(filters.regex(r"^edit_media:(\w+)$"))
async def apply_media_edit(client, callback_query):
    short_id = callback_query.data.split(":")[1]
    if short_id not in pending_edits:
        await callback_query.message.edit_caption("❌ This edit expired.")
        return

    card_id, media_type, media_file = pending_edits.pop(short_id)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE waifu_cards SET media_type=?, media_file=? WHERE id=?", (media_type, media_file, card_id))
    conn.commit()
    conn.close()

    await callback_query.message.edit_caption(f"✅ Card {card_id} updated successfully!")


@app.on_callback_query(filters.regex(r"^edit_cancel$"))
async def cancel_edit(client, callback_query):
    await callback_query.message.edit_caption("❌ Edit cancelled.")
