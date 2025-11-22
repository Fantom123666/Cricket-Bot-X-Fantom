# handlers/sudo.py
from pyrogram import filters
from pyrogram.types import Message
from config import app, Config
from database import Database
import sqlite3
import time
import asyncio

db = Database()
DB_PATH = getattr(Config, "DB_PATH", "waifu_bot.db")

# In-memory cache of admin user IDs (keeps permissions instant)
BOT_ADMINS_CACHE = set()

# ---------------- DB helpers ----------------
def ensure_table():
    try:
        cur = db.cursor
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_at INTEGER
            )
            """
        )
        db.conn.commit()
        return True
    except Exception:
        try:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_admins (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER,
                    added_at INTEGER
                )
                """
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

ensure_table()

def load_admins():
    """Load admin IDs from DB into BOT_ADMINS_CACHE (safe to call at runtime)."""
    try:
        cur = db.cursor
        cur.execute("SELECT user_id FROM bot_admins")
        ids = [r[0] for r in cur.fetchall()]
    except Exception:
        try:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT user_id FROM bot_admins")
            ids = [r[0] for r in c.fetchall()]
            conn.close()
        except Exception:
            ids = []
    global BOT_ADMINS_CACHE
    BOT_ADMINS_CACHE = set(int(i) for i in ids if i is not None)
    return BOT_ADMINS_CACHE

# initial load on module import
load_admins()

def add_admin_db(user_id: int, added_by: int) -> bool:
    """Insert to DB and refresh cache. Returns True if inserted, False if already existed / failed."""
    try:
        cur = db.cursor
        cur.execute("SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,))
        if cur.fetchone():
            return False
        now = int(time.time())
        cur.execute("INSERT INTO bot_admins (user_id, added_by, added_at) VALUES (?, ?, ?)", (user_id, added_by, now))
        db.conn.commit()
        # refresh cache
        load_admins()
        return True
    except Exception:
        try:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,))
            if c.fetchone():
                conn.close()
                return False
            now = int(time.time())
            c.execute("INSERT INTO bot_admins (user_id, added_by, added_at) VALUES (?, ?, ?)", (user_id, added_by, now))
            conn.commit()
            conn.close()
            load_admins()
            return True
        except Exception:
            return False

def remove_admin_db(user_id: int) -> bool:
    """Delete from DB and refresh cache. Returns True if deleted, False if not present or failed."""
    try:
        cur = db.cursor
        cur.execute("SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,))
        if not cur.fetchone():
            return False
        cur.execute("DELETE FROM bot_admins WHERE user_id = ?", (user_id,))
        db.conn.commit()
        load_admins()
        return True
    except Exception:
        try:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,))
            if not c.fetchone():
                conn.close()
                return False
            c.execute("DELETE FROM bot_admins WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            load_admins()
            return True
        except Exception:
            return False

def list_admins_db():
    try:
        cur = db.cursor
        cur.execute("SELECT user_id, added_by, added_at FROM bot_admins ORDER BY added_at ASC")
        return cur.fetchall()
    except Exception:
        try:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT user_id, added_by, added_at FROM bot_admins ORDER BY added_at ASC")
            rows = c.fetchall()
            conn.close()
            return rows
        except Exception:
            return []

def is_bot_admin_db(user_id: int) -> bool:
    """DB lookup fallback — kept for completeness."""
    try:
        cur = db.cursor
        cur.execute("SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,))
        return bool(cur.fetchone())
    except Exception:
        try:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,))
            found = bool(c.fetchone())
            conn.close()
            return found
        except Exception:
            return False

# ---------------- owner detection ----------------
def get_owner_id_from_config():
    for name in ("OWNER_ID", "OWNER", "OWNER_USER_ID", "OWNERID"):
        val = getattr(Config, name, None)
        if val:
            try:
                return int(val)
            except Exception:
                try:
                    return int(str(val).strip())
                except Exception:
                    pass
    return None

OWNER_ID = get_owner_id_from_config()

def is_owner(user_id: int) -> bool:
    return OWNER_ID is not None and int(user_id) == int(OWNER_ID)

# ---------------- utility to safely mention a user (plain text) ----------------
async def mention_user_safe(client, user_id: int) -> str:
    try:
        u = await client.get_users(user_id)
        name = getattr(u, "first_name", None)
        username = getattr(u, "username", None)
        if name:
            return f"{name} ({user_id})"
        if username:
            return f"@{username} ({user_id})"
    except Exception:
        pass
    return str(user_id)

# ---------------- attempt to promote/demote in chat (best-effort) ----------------
async def try_promote_in_chat(client, chat_id, target_user_id: int) -> (bool, str):
    try:
        me = await client.get_chat_member(chat_id, "me")
        if getattr(me, "status", "") not in ("administrator", "creator"):
            return False, "Bot is not an admin in this chat."
        bot_can_promote = getattr(me, "can_promote_members", False)
        if not bot_can_promote:
            return False, "Bot lacks promote rights in this chat."
        await client.promote_chat_member(
            chat_id,
            target_user_id,
            can_change_info=True,
            can_delete_messages=True,
            can_invite_users=True,
            can_restrict_members=True,
            can_pin_messages=True,
            can_promote_members=False,
            can_manage_video_chats=True
        )
        return True, "Promoted in this chat."
    except Exception as e:
        return False, f"Failed to promote in chat: {e}"

async def try_demote_in_chat(client, chat_id, target_user_id: int) -> (bool, str):
    try:
        me = await client.get_chat_member(chat_id, "me")
        if getattr(me, "status", "") not in ("administrator", "creator"):
            return False, "Bot is not an admin in this chat."
        bot_can_promote = getattr(me, "can_promote_members", False)
        if not bot_can_promote:
            return False, "Bot lacks promote rights in this chat."
        await client.promote_chat_member(
            chat_id,
            target_user_id,
            can_change_info=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_video_chats=False
        )
        return True, "Demoted in this chat."
    except Exception as e:
        return False, f"Failed to demote in chat: {e}"

# ---------------- Public helper used by other modules ----------------
def is_bot_admin(user_id: int) -> bool:
    """Fast cache-based check other modules should call at runtime."""
    # first check in-memory cache
    if int(user_id) in BOT_ADMINS_CACHE:
        return True
    # fallback to DB (in case cache is out of sync)
    return is_bot_admin_db(user_id)

def reload_admins():
    """Force reload cache from DB (callable from other modules if needed)."""
    return load_admins()

# ---------------- /sudo (add admin) ----------------
@app.on_message(filters.command("sudo"))
async def cmd_sudo(client, message: Message):
    sender = message.from_user
    if not is_owner(sender.id):
        await message.reply_text("❌ Only the bot owner can use this command.")
        return

    target_user_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.strip().split()
        if len(parts) >= 2:
            try:
                target_user_id = int(parts[1])
            except Exception:
                target_user_id = None

    if not target_user_id:
        await message.reply_text("Usage: reply to a user's message with /sudo or use: /sudo <user_id>")
        return

    added = add_admin_db(target_user_id, sender.id)
    if not added:
        await message.reply_text(f"⚠️ User {target_user_id} is already a bot admin (or DB insert failed).")
        return

    promoted = False
    promote_msg = ""
    if message.chat.type in ("group", "supergroup"):
        promoted, promote_msg = await try_promote_in_chat(client, message.chat.id, target_user_id)

    mention = await mention_user_safe(client, target_user_id)
    if promoted:
        await message.reply_text(f"✅ {mention} has been made a bot admin (and promoted in this chat).")
    else:
        if promote_msg:
            await message.reply_text(f"✅ {mention} has been added to bot admins (note: {promote_msg})")
        else:
            await message.reply_text(f"✅ {mention} has been added to bot admins.")

# ---------------- /sack (remove admin) ----------------
@app.on_message(filters.command("sack"))
async def cmd_sack(client, message: Message):
    sender = message.from_user
    if not is_owner(sender.id):
        await message.reply_text("❌ Only the bot owner can use this command.")
        return

    target_user_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
    else:
        parts = message.text.strip().split()
        if len(parts) >= 2:
            try:
                target_user_id = int(parts[1])
            except Exception:
                target_user_id = None

    if not target_user_id:
        await message.reply_text("Usage: reply to a user's message with /sack or use: /sack <user_id>")
        return

    existed = remove_admin_db(target_user_id)
    if not existed:
        await message.reply_text(f"⚠️ User {target_user_id} is not a bot admin.")
        return

    demoted = False
    demote_msg = ""
    if message.chat.type in ("group", "supergroup"):
        demoted, demote_msg = await try_demote_in_chat(client, message.chat.id, target_user_id)

    mention = await mention_user_safe(client, target_user_id)
    if demoted:
        await message.reply_text(f"✅ {mention} has been removed from bot admins (and demoted in this chat).")
    else:
        if demote_msg:
            await message.reply_text(f"✅ {mention} has been removed from bot admins (note: {demote_msg})")
        else:
            await message.reply_text(f"✅ {mention} has been removed from bot admins.")

# ---------------- /listadmin (show admins) ----------------
@app.on_message(filters.command("listadmin"))
async def cmd_listadmin(client, message: Message):
    rows = list_admins_db()

    lines = []
    ids = [r[0] for r in rows]
    users_info = {}
    if ids:
        try:
            fetched = await client.get_users(ids)
            if not isinstance(fetched, (list, tuple)):
                fetched = [fetched]
            for u in fetched:
                users_info[int(u.id)] = (getattr(u, "first_name", None), getattr(u, "username", None))
        except Exception:
            users_info = {}

    for r in rows:
        uid, added_by, added_at = r
        display = str(uid)
        if uid in users_info:
            fn, un = users_info[uid]
            if fn:
                display = f"{fn} ({uid})"
            elif un:
                display = f"@{un} ({uid})"
        if OWNER_ID and int(uid) == int(OWNER_ID):
            display = "👑 " + display
        added_by_label = str(added_by) if added_by else "Unknown"
        lines.append(f"• {display} — added by {added_by_label}")

    if OWNER_ID:
        owner_in_list = any(int(r[0]) == int(OWNER_ID) for r in rows)
        if not owner_in_list:
            lines.insert(0, f"👑 Owner: {OWNER_ID}")

    if not lines:
        await message.reply_text("No bot admins found.")
        return

    text = "🤖 Bot Admins:\n\n" + "\n".join(lines)
    await message.reply_text(text)
