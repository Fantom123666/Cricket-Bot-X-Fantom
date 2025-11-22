# handlers/backup.py
import os
import zipfile
from datetime import datetime
from typing import Optional
from pyrogram import filters
from pyrogram.errors import RPCError
from config import app, Config

DB_PATH = getattr(Config, "DB_PATH", "waifu_bot.db")
TELEGRAM_FILE_LIMIT = 49 * 1024 * 1024  # ~50 MB Telegram bot upload limit

async def safe_send_text(client, chat_id: int, text: str, reply_to: Optional[int] = None):
    """Send text safely (no entity parsing issues)."""
    try:
        return await client.send_message(chat_id, text, parse_mode=None, reply_to_message_id=reply_to)
    except RPCError:
        try:
            return await client.send_message(chat_id, text.replace("`", "'"), parse_mode=None, reply_to_message_id=reply_to)
        except Exception:
            return None

def zip_file(src_path: str) -> str:
    """Compress DB into a timestamped zip and return path."""
    base = os.path.splitext(src_path)[0]
    zip_path = f"{base}_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(src_path, arcname=os.path.basename(src_path))
    return zip_path

@app.on_message(filters.command("backup"))
async def backup_handler(client, message):
    uid = message.from_user.id if message.from_user else None
    chat_id = message.chat.id

    owner_id = getattr(Config, "OWNER_ID", None)
    if owner_id is None:
        await safe_send_text(client, chat_id, "❗ OWNER_ID not set in Config.", reply_to=getattr(message, "message_id", None))
        return

    if uid != int(owner_id):
        await safe_send_text(client, chat_id, "❌ Only the bot owner can request backups.", reply_to=getattr(message, "message_id", None))
        return

    if not os.path.exists(DB_PATH):
        await safe_send_text(client, chat_id, f"❌ Database not found at `{DB_PATH}`.", reply_to=getattr(message, "message_id", None))
        return

    size = os.path.getsize(DB_PATH)
    to_send = DB_PATH
    temp_zip = None

    # zip if too large
    if size > TELEGRAM_FILE_LIMIT:
        try:
            temp_zip = zip_file(DB_PATH)
            to_send = temp_zip
        except Exception as e:
            await safe_send_text(client, chat_id, f"❌ Failed to compress DB: {e}", reply_to=getattr(message, "message_id", None))
            return

    await safe_send_text(client, chat_id, "📦 Preparing database backup...", reply_to=getattr(message, "message_id", None))

    try:
        await client.send_document(chat_id, document=to_send, file_name=os.path.basename(to_send))
        await safe_send_text(client, chat_id, "✅ Backup sent. Save it securely!", reply_to=getattr(message, "message_id", None))
    except Exception as e:
        await safe_send_text(client, chat_id, f"❌ Failed to send backup: {e}", reply_to=getattr(message, "message_id", None))
    finally:
        if temp_zip and os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass
