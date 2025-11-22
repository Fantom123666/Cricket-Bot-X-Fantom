# handlers/addwaifu.py

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from config import Config, app
from database import Database
import os, uuid

db = Database()
db.ensure_waifu_cards_schema()  # make sure table/columns exist at import

# Keep preview payloads here by a short token -> data
PENDING_ADDS = {}

# Build allowed IDs set
ALLOWED_IDS = {getattr(Config, "OWNER_ID", 0)}
ALLOWED_IDS.update(getattr(Config, "ADMINS", []))  # make sure Config.ADMINS exists as list

# ------------- Allowed rarities -------------
ALLOWED_RARITIES = [
    "Common", "Medium", "Rare", "Legendary", "Limited edition",
    "Prime", "Cosmic", "Ultimate", "God"
]

def is_allowed(user_id: int) -> bool:
    return user_id in ALLOWED_IDS

def short_token() -> str:
    # short, safe token for callback data
    return uuid.uuid4().hex[:10]

# ------------- /addwaifu command -------------
@app.on_message(filters.command("addwaifu"))
async def add_waifu_start(client, message: Message):
    # Permission check for both DM & Groups
    user_id = message.from_user.id if message.from_user else 0
    if not is_allowed(user_id):
        await message.reply_text("⛔ Owner/Admin only command.")
        return

    # Parse arguments
    try:
        text = message.text.split(" ", 1)[1]
    except IndexError:
        await message.reply_text("❌ Usage: /addwaifu Cricketer Name | Team | Rarity | Event\n\nReply to an image/video with this command.")
        return

    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 4:
        await message.reply_text("❌ Usage: /addwaifu Cricketer Name | Team | Rarity | Event")
        return

    name, anime, rarity, event = parts

    if rarity not in ALLOWED_RARITIES:
        await message.reply_text(
            "❌ Invalid rarity!\n\n" +
            "\n".join(f"• {r}" for r in ALLOWED_RARITIES)
        )
        return

    # Need a reply with media
    if not message.reply_to_message:
        await message.reply_text("📷 Please reply to the waifu image or video with the /addwaifu command.")
        return

    reply = message.reply_to_message
    media_type = None
    media_file_id = None

    if reply.photo:
        media_type = "photo"
        media_file_id = reply.photo.file_id
    elif reply.video:
        media_type = "video"
        media_file_id = reply.video.file_id
    else:
        await message.reply_text("❌ Please reply to a Crickter image or video to add.")
        return

    # Prepare preview
    caption = (
        "🌸 New Crickter Preview 🌸\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"✨ Name: {name}\n"
        f"⛩️ Anime: {anime}\n"
        f"💎 Rarity: {rarity}\n"
        f"🎀 Event/Theme: {event}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"{'📷 [Image Attached]' if media_type == 'photo' else '📽️ [Video Attached]'}\n\n"
        "👉 Do you want to add this Cricketer to the collection?"
    )

    # Store payload in memory and use short token in the buttons
    token = short_token()
    PENDING_ADDS[token] = {
        "name": name,
        "anime": anime,
        "rarity": rarity,
        "event": event,
        "media_type": media_type,
        "media_file_id": media_file_id,
        "owner": user_id
    }

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"aw_ok:{token}")],
        [InlineKeyboardButton("❌ Cancel",  callback_data=f"aw_no:{token}")]
    ])

    # Send preview with the same media
    if media_type == "photo":
        await message.reply_photo(media_file_id, caption=caption, reply_markup=buttons)
    else:
        await message.reply_video(media_file_id, caption=caption, reply_markup=buttons)

# ------------- Callback handlers -------------
@app.on_callback_query(filters.regex(r"^aw_(ok|no):"))
async def add_waifu_callback(client, cq: CallbackQuery):
    # Only allow owner/admins to press
    user_id = cq.from_user.id if cq.from_user else 0
    if not is_allowed(user_id):
        await cq.answer("⛔ Owner/Admin only.", show_alert=True)
        return

    action, token = cq.data.split(":")
    payload = PENDING_ADDS.get(token)

    if not payload:
        await cq.answer("❌ This preview expired. Please run /addwaifu again.", show_alert=True)
        # also try to remove the preview message to avoid stale buttons
        try:
            await cq.message.edit_text("❌ This preview expired.")
        except:
            pass
        return

    if action == "aw_no":
        # Cancel
        PENDING_ADDS.pop(token, None)
        await cq.answer("❌ Cancelled.")
        try:
            await cq.message.edit_text("❌ Waifu addition cancelled.")
        except:
            pass
        return

    # Confirm
    try:
        # Ensure schema again (safe)
        db.ensure_waifu_cards_schema()

        # Insert; write both media_file and media_file_id for compatibility
        db.cursor.execute("""
            INSERT INTO waifu_cards (name, anime, rarity, event, media_type, media_file, media_file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            payload["name"],
            payload["anime"],
            payload["rarity"],
            payload["event"],
            payload["media_type"],
            payload["media_file_id"],   # media_file (compat) = file_id as well
            payload["media_file_id"]    # media_file_id
        ))
        db.conn.commit()
        new_id = db.cursor.lastrowid

        # Clean state
        PENDING_ADDS.pop(token, None)

        # Acknowledge and show final saved card with Waifu ID
        await cq.answer("✅ Saved!", show_alert=False)
        final_caption = (
            "✅ Cricketer Saved!\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 Crickter ID: {new_id}\n"
            f"✨ Name: {payload['name']}\n"
            f"⛩️ Team: {payload['anime']}\n"
            f"💎 Rarity: {payload['rarity']}\n"
            f"🎀 Event/Theme: {payload['event']}\n"
        )
        if payload["media_type"] == "photo":
            await cq.message.edit_caption(final_caption)
        else:
            # For videos, edit_caption also works if it was sent as video with caption
            await cq.message.edit_caption(final_caption)

    except Exception as e:
        await cq.answer("❌ Failed to save.", show_alert=True)
        try:
            await cq.message.edit_text(f"❌ Error while saving: {e}")
        except:
            pass
      
