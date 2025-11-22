# handlers/gban.py
"""
Global ban (reply-only) using custom filters that only trigger for banned users.
- Reply to a user's message with /gban  -> ban (admin/owner only)
- Reply to a user's message with /gunban -> unban (admin/owner only)

Behavior:
 - Banned users: group messages deleted; private messages optionally get a short notice.
 - Callback presses show an alert to banned users.
 - Bans persist in DB table `global_bans` and are cached for fast checks.
 - Owner(s) cannot be banned.
"""

from datetime import datetime
from typing import Optional
from pyrogram import filters
from pyrogram.types import Message, CallbackQuery
from config import app, Config
from database import Database

db = Database()

# whether to notify banned users in private chat (True = reply, False = silent ignore)
NOTIFY_BANNED_IN_PRIVATE = True

# ------------------- DB schema / cache -------------------
def ensure_global_bans_schema():
    try:
        db.cursor.execute("""
            CREATE TABLE IF NOT EXISTS global_bans (
                user_id INTEGER PRIMARY KEY
            )
        """)
        db.conn.commit()
    except Exception:
        pass

    # best-effort add optional cols if missing
    try:
        required = {"banned_by": "INTEGER", "reason": "TEXT", "banned_at": "TEXT"}
        db.cursor.execute("PRAGMA table_info(global_bans)")
        existing = [r[1] for r in db.cursor.fetchall()]
        for col, ctype in required.items():
            if col not in existing:
                try:
                    db.cursor.execute(f"ALTER TABLE global_bans ADD COLUMN {col} {ctype}")
                    db.conn.commit()
                except Exception:
                    pass
    except Exception:
        pass

ensure_global_bans_schema()

BANNED_CACHE = set()

def load_banned_cache():
    """Load all banned user_ids into in-memory set. Safe to call again to refresh."""
    BANNED_CACHE.clear()
    try:
        db.cursor.execute("SELECT user_id FROM global_bans")
        for row in db.cursor.fetchall():
            try:
                BANNED_CACHE.add(int(row[0]))
            except Exception:
                continue
    except Exception:
        pass

# initial load
load_banned_cache()

# ------------------- helpers -------------------
def now_iso() -> str:
    return datetime.utcnow().isoformat()

def is_owner(uid: int) -> bool:
    try:
        if getattr(Config, "OWNER_ID", None) and int(uid) == int(getattr(Config, "OWNER_ID")):
            return True
        owner_ids = getattr(Config, "OWNER_IDS", []) or []
        if owner_ids and int(uid) in [int(x) for x in owner_ids]:
            return True
    except Exception:
        pass
    return False

def is_admin(uid: int) -> bool:
    try:
        if is_owner(uid):
            return True
        admins = getattr(Config, "ADMINS", []) or []
        if admins and int(uid) in [int(x) for x in admins]:
            return True
    except Exception:
        pass
    return False

def add_global_ban(user_id: int, banned_by: int = 0, reason: Optional[str] = None):
    """Insert/replace into DB and update cache immediately (best-effort)."""
    try:
        ensure_global_bans_schema()
        banned_at = now_iso()
        try:
            db.cursor.execute(
                "INSERT OR REPLACE INTO global_bans (user_id, banned_by, reason, banned_at) VALUES (?, ?, ?, ?)",
                (int(user_id), int(banned_by or 0), reason or "", banned_at)
            )
            db.conn.commit()
        except Exception:
            # fallback minimal insert if schema older
            try:
                db.cursor.execute("INSERT OR REPLACE INTO global_bans (user_id) VALUES (?)", (int(user_id),))
                db.conn.commit()
            except Exception:
                pass
        BANNED_CACHE.add(int(user_id))
        try:
            db.log_event("gban", user_id=user_id, details=f"by={banned_by} reason={reason}")
        except Exception:
            pass
    except Exception:
        pass

def remove_global_ban(user_id: int):
    try:
        db.cursor.execute("DELETE FROM global_bans WHERE user_id = ?", (int(user_id),))
        db.conn.commit()
    except Exception:
        pass
    BANNED_CACHE.discard(int(user_id))
    try:
        db.log_event("gunban", user_id=user_id)
    except Exception:
        pass

def is_globally_banned(uid: int) -> bool:
    try:
        return int(uid) in BANNED_CACHE
    except Exception:
        return False

# ------------------- Filters (fast, evaluated before handlers) -------------------
# Message filter: returns True only when the incoming Message is FROM a banned user
@filters.create
def banned_message_filter(_, __, message: Message):
    try:
        if not message or not getattr(message, "from_user", None):
            return False
        return int(message.from_user.id) in BANNED_CACHE
    except Exception:
        return False

# Callback filter: returns True only when CallbackQuery is FROM a banned user
@filters.create
def banned_callback_filter(_, __, callback: CallbackQuery):
    try:
        if not callback or not getattr(callback, "from_user", None):
            return False
        return int(callback.from_user.id) in BANNED_CACHE
    except Exception:
        return False

# ------------------- Handlers that run only when user is banned -------------------
# These run group=0 but only for banned users (filter prevents them from running for others)
@app.on_message(banned_message_filter, group=0)
async def _handle_banned_message(client, message: Message):
    # Minimal, defensive handler: delete group messages; reply in private (optional)
    try:
        if not message or not message.from_user:
            return
        uid = message.from_user.id
        # double-check from cache (defensive)
        if not is_globally_banned(uid):
            return

        if message.chat and message.chat.type in ("group", "supergroup"):
            try:
                await message.delete()
            except Exception:
                pass
            # do not send heavy notifications; keep minimal to avoid spam
            return

        if message.chat and message.chat.type == "private":
            if NOTIFY_BANNED_IN_PRIVATE:
                try:
                    await message.reply_text("🚫 You are banned from using this bot. Contact support if you believe this is a mistake.")
                except Exception:
                    pass
            return
    except Exception:
        # swallow any errors to avoid interfering with other handlers
        return

@app.on_callback_query(banned_callback_filter, group=0)
async def _handle_banned_callback(client, callback: CallbackQuery):
    try:
        uid = callback.from_user.id
        if not is_globally_banned(uid):
            return
        try:
            await callback.answer("🚫 You are banned from using this bot.", show_alert=True)
        except Exception:
            pass
    except Exception:
        return

# ------------------- Commands: reply-only gban/gunban -------------------
@app.on_message(filters.command("gban"))
async def gban_handler(client, message: Message):
    try:
        issuer = message.from_user
        if not issuer:
            return
        if not is_admin(issuer.id):
            # explicit helpful reply for non-admins
            try:
                await message.reply_text("🚫 You are not an admin. Think again!")
            except Exception:
                pass
            return

        if not message.reply_to_message or not message.reply_to_message.from_user:
            try:
                await message.reply_text("Usage: reply to the target user's message with /gban")
            except Exception:
                pass
            return

        target = message.reply_to_message.from_user
        target_id = target.id

        if is_owner(target_id):
            try:
                await message.reply_text("❌ Cannot ban the bot owner.")
            except Exception:
                pass
            return

        if is_globally_banned(target_id):
            try:
                await message.reply_text("ℹ️ User is already globally banned.")
            except Exception:
                pass
            return

        parts = (message.text or "").split(maxsplit=1)
        reason = parts[1].strip() if len(parts) > 1 else None

        add_global_ban(target_id, issuer.id, reason)

        # ensure user exists in users table
        try:
            db.add_user(target_id, username=getattr(target, "username", None), first_name=getattr(target, "first_name", None))
        except Exception:
            pass

        # notify target via DM (best-effort)
        try:
            await client.send_message(target_id, "🚫 You have been globally banned from using this bot. Contact support if you believe this is a mistake.")
        except Exception:
            pass

        display = f"@{getattr(target, 'username', None)}" if getattr(target, "username", None) else (getattr(target, "first_name", None) or str(target_id))
        try:
            await message.reply_text(f"✅ {display} has been globally banned.")
        except Exception:
            pass
    except Exception:
        try:
            await message.reply_text("❌ Failed to ban user (internal error).")
        except Exception:
            pass

@app.on_message(filters.command("gunban"))
async def gunban_handler(client, message: Message):
    try:
        issuer = message.from_user
        if not issuer:
            return
        if not is_admin(issuer.id):
            try:
                await message.reply_text("🚫 You are not an admin. Think again!")
            except Exception:
                pass
            return

        if not message.reply_to_message or not message.reply_to_message.from_user:
            try:
                await message.reply_text("Usage: reply to the target user's message with /gunban")
            except Exception:
                pass
            return

        target = message.reply_to_message.from_user
        target_id = target.id

        if not is_globally_banned(target_id):
            try:
                await message.reply_text("ℹ️ User is not globally banned.")
            except Exception:
                pass
            return

        remove_global_ban(target_id)

        try:
            await client.send_message(target_id, "🔓 You have been unbanned and can use the bot again.")
        except Exception:
            pass

        display = f"@{getattr(target,'username',None)}" if getattr(target,"username",None) else (getattr(target,"first_name",None) or str(target_id))
        try:
            await message.reply_text(f"✅ {display} has been unbanned.")
        except Exception:
            pass
    except Exception:
        try:
            await message.reply_text("❌ Failed to unban user (internal error).")
        except Exception:
            pass

# small owner helper to refresh cache manually
@app.on_message(filters.command("reload_gbans"))
async def reload_gbans_cmd(client, message: Message):
    try:
        uid = message.from_user.id
        if not is_owner(uid):
            return
        load_banned_cache()
        await message.reply_text("✅ Global ban cache reloaded.")
    except Exception:
        pass
