# handlers/userdetatiles.py
"""
Owner-only details + utility commands.

Commands:
 - /details <user_id>      -> OWNER ONLY. Fetches available Telegram details about the user_id
                             and (if available) phone number previously shared to the bot.
                             Sends a .txt report to the owner as a document.

 - /id                     -> If used as a reply: returns the replied user's ID.
                             If used not as a reply: returns the current chat ID.

Notes / privacy:
 - Telegram does NOT expose other users' phone numbers to bots. The only way a bot can
   obtain a phone number is if a user explicitly shares their contact with the bot
   (e.g. via the "Attach -> Contact" UI). This script stores such shared contacts
   (when received in private chat) into the local DB table `user_contacts` so the
   owner can later look them up with /details.
 - This file *only* adds the contact-storage handler and the owner /details command.
"""

import sqlite3
import io
from datetime import datetime

from pyrogram import filters
from pyrogram.types import Message, Contact
from config import app, Config

DB_PATH = "waifu_bot.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Ensure contacts table exists (stores contacts users explicitly shared with bot)
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_contacts (
    user_id INTEGER PRIMARY KEY,
    phone TEXT,
    name TEXT,
    saved_by INTEGER,         -- id of who sent the contact (useful if admin submitted)
    saved_at TEXT
)
""")
conn.commit()


# ------------------ Helper: save contact when a user shares contact in private ------------------
# This handler stores contacts shared in private chats (best-effort).
# It intentionally only saves when the contact is shared in a private chat with the bot.
@app.on_message(filters.private & filters.contact)
async def store_shared_contact(client, message: Message):
    """
    When somebody shares a contact to the bot in private, we save it so /details can find it later.
    Saving contact is explicit (user shared it) — we do NOT request or harvest phone numbers.
    """
    try:
        contact: Contact = message.contact
        # contact.user_id may be None if phone-only contact; prefer contact.user_id when available.
        target_id = contact.user_id if contact.user_id else None
        phone = contact.phone_number
        name = " ".join(filter(None, [contact.first_name, contact.last_name])).strip() or contact.vcard or "Unknown"
        saved_by = message.from_user.id if message.from_user else None
        saved_at = datetime.utcnow().isoformat()

        if target_id:
            # store by explicit user id
            cursor.execute("""
                INSERT OR REPLACE INTO user_contacts (user_id, phone, name, saved_by, saved_at)
                VALUES (?, ?, ?, ?, ?)
            """, (int(target_id), phone, name, saved_by, saved_at))
            conn.commit()
            await message.reply_text("✅ Contact saved. Owner can view this via /details.")
        else:
            # No linked Telegram user id — we still store a placeholder using negative row id (timestamp)
            # but we won't be able to map it to a user id later. Inform the sharer.
            await message.reply_text("⚠️ Contact saved locally but it is not linked to a Telegram user (no user id included). Owner cannot map it to a user id.")
    except Exception:
        # Do not spam errors to user; log to console instead
        try:
            print("Failed to store shared contact:", exc_info=True)
        except Exception:
            pass


# ------------------ /details command (owner-only) ------------------
@app.on_message(filters.command("details"))
async def details_handler(client, message: Message):
    """
    Usage:
      /details <user_id>

    Owner-only. Gathers available information via Telegram API + stored contacts
    and sends a .txt report to the owner as a document.
    """
    # Owner-only check
    if not message.from_user or message.from_user.id != Config.OWNER_ID:
        await message.reply_text("❌ This command is owner-only.")
        return

    # Parse user id
    parts = (message.text or "").strip().split(None, 1)
    if len(parts) < 2:
        await message.reply_text("Usage: /details <user_id>\nExample: /details 123456789")
        return

    target_token = parts[1].strip()
    try:
        target_id = int(target_token)
    except Exception:
        await message.reply_text("❌ Invalid user id. It must be a numeric Telegram user id.")
        return

    # Try to fetch user via Telegram API (best-effort)
    user_info = None
    profile_photo_count = None
    chat_member_status = None
    try:
        user_info = await client.get_users(target_id)
    except Exception as e:
        # user_info stays None if user not found or privacy prevents retrieval
        user_info = None
        # we continue to collect what we can (contacts etc.)

    try:
        photos = await client.get_user_profile_photos(target_id)
        profile_photo_count = photos.total_count if photos else 0
    except Exception:
        profile_photo_count = None

    # Check if we have a saved contact phone number for this user
    phone = None
    contact_name = None
    try:
        cursor.execute("SELECT phone, name FROM user_contacts WHERE user_id = ?", (target_id,))
        r = cursor.fetchone()
        if r:
            phone, contact_name = r[0], r[1]
    except Exception:
        phone = None

    # Attempt to get chat member status for any mutual groups where the bot is present is costly;
    # we won't enumerate groups here to avoid heavy ops. Instead attempt a single get_chat_member
    # only if the command was invoked from a group and target is part of that chat.
    try:
        if message.chat and message.chat.type in ("group", "supergroup"):
            try:
                cm = await client.get_chat_member(message.chat.id, target_id)
                chat_member_status = cm.status
            except Exception:
                chat_member_status = None
    except Exception:
        chat_member_status = None

    # Build report
    lines = []
    lines.append(f"User details report generated: {datetime.utcnow().isoformat()} UTC")
    lines.append("=" * 60)
    lines.append(f"Requested ID: {target_id}")
    lines.append("")

    if user_info:
        lines.append(f"First name: {getattr(user_info, 'first_name', '') or '—'}")
        lines.append(f"Last name: {getattr(user_info, 'last_name', '') or '—'}")
        lines.append(f"Username: @{getattr(user_info, 'username', '') if getattr(user_info, 'username', None) else '—'}")
        lines.append(f"Is bot: {getattr(user_info, 'is_bot', False)}")
        lines.append(f"Language code: {getattr(user_info, 'language_code', None) or '—'}")
        # Some attributes may be missing for bots
        # user_info.status is not available via get_users; presence / last seen cannot be reliably obtained here.
    else:
        lines.append("Telegram API: Could not fetch user via get_users (may be privacy/invalid id).")

    lines.append(f"Profile photos (count): {profile_photo_count if profile_photo_count is not None else 'unknown'}")
    if chat_member_status:
        lines.append(f"Status in this chat: {chat_member_status}")
    lines.append("")

    # Phone info from stored contacts (explicit user-shared contacts)
    if phone:
        lines.append("Phone (from user-shared contact):")
        lines.append(f" - Number: {phone}")
        lines.append(f" - Saved name: {contact_name or '—'}")
        lines.append("")
    else:
        lines.append("Phone: Not available.")
        lines.append("Note: Telegram bots cannot fetch other users' phone numbers via the API.")
        lines.append("If you want to collect phone numbers for verification, instruct users to send their contact to the bot in private (Attach → Contact).")
        lines.append("When a user shares their contact in private with the bot, it will be stored and visible here.")
        lines.append("")

    # Extra suggestions
    lines.append("Suggestions to gather phone numbers reliably:")
    lines.append("- Ask users to DM the bot and share their contact via Telegram's contact share (this bot stores those contacts).")
    lines.append("- Require a verification step that asks users to confirm a code sent to their phone (external SMS) — requires additional infra.")
    lines.append("")

    report_text = "\n".join(lines)

    # Create in-memory text file and send to owner (who invoked)
    bio = io.BytesIO(report_text.encode("utf-8"))
    bio.name = f"user_details_{target_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"

    try:
        await client.send_document(Config.OWNER_ID, bio, caption=f"User details for ID {target_id}")
        # also notify in the chat that the report was sent
        await message.reply_text("✅ Detailed report sent to owner (as a .txt file).")
    except Exception as e:
        # fallback: reply in current chat with the text (if small) or send file to current chat
        try:
            bio.seek(0)
            await client.send_document(message.chat.id, bio, caption=f"User details for ID {target_id} (fallback)")
        except Exception as e2:
            # last resort: send a short message
            await message.reply_text("❌ Failed to deliver report to owner or this chat. Check bot logs.")


# ------------------ /id command ------------------
@app.on_message(filters.command("id"))
async def id_simple_handler(client, message: Message):
    """
    If used as a reply -> show replied user's id.
    If not a reply -> show current chat id.
    """
    if message.reply_to_message and message.reply_to_message.from_user:
        uid = message.reply_to_message.from_user.id
        name = message.reply_to_message.from_user.first_name or ""
        await message.reply_text(f"User: {name}\nID: `{uid}`")
        return

    # Not a reply -> show chat id (works in private/group)
    if message.chat:
        title = message.chat.title or (message.chat.first_name or "Private")
        await message.reply_text(f"Chat: {title}\nChat ID: `{message.chat.id}`")
    else:
        await message.reply_text("❌ Could not determine chat or user id here.")
