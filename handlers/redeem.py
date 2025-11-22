# handlers/redeem.py
"""
Robust redeem handler.

- /create <waifu_id> <limit>   (owner only)
- /redeem <code>               (users)
- Inline button to redeem
This version will ALTER the redeem_codes table to add missing columns if the table was created earlier with a smaller schema.
"""

import random
import string
from datetime import datetime
from typing import Optional
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from config import app, Config
from database import Database

db = Database()

# ---------------- Schema ensure (create/alter if needed) ----------------
def ensure_redeem_tables():
    # create table if missing with minimal column
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code TEXT PRIMARY KEY,
            waifu_id INTEGER
            -- other columns may be added below via ALTER TABLE
        )
    """)
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS redeem_claims (
            code TEXT,
            user_id INTEGER,
            redeemed_at TEXT,
            PRIMARY KEY (code, user_id)
        )
    """)
    db.conn.commit()

    # required columns and types
    required = {
        "creator": "INTEGER",
        "limit_count": "INTEGER",
        "redeemed_count": "INTEGER DEFAULT 0",
        "created_at": "TEXT"
    }

    # check existing columns
    db.cursor.execute("PRAGMA table_info(redeem_codes)")
    existing = [r[1] for r in db.cursor.fetchall()]
    for col, coltype in required.items():
        if col not in existing:
            try:
                db.cursor.execute(f"ALTER TABLE redeem_codes ADD COLUMN {col} {coltype}")
                db.conn.commit()
            except Exception:
                # best-effort: some SQLite older builds or schema states may error; ignore and continue
                pass

# run schema ensure on import
ensure_redeem_tables()

# ---------------- Utilities ----------------
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

def now_iso() -> str:
    return datetime.utcnow().isoformat()

def gen_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def find_unique_code():
    for _ in range(10):
        c = gen_code(8)
        db.cursor.execute("SELECT 1 FROM redeem_codes WHERE code = ?", (c,))
        if not db.cursor.fetchone():
            return c
    # fallback longer code
    while True:
        c = gen_code(12)
        db.cursor.execute("SELECT 1 FROM redeem_codes WHERE code = ?", (c,))
        if not db.cursor.fetchone():
            return c

def waifu_row_by_id(waifu_id: int):
    db.cursor.execute("SELECT id, name, anime, rarity, event, media_type, media_file, media_file_id FROM waifu_cards WHERE id = ?", (waifu_id,))
    return db.cursor.fetchone()

def user_has_claimed(code: str, user_id: int) -> bool:
    db.cursor.execute("SELECT 1 FROM redeem_claims WHERE code = ? AND user_id = ?", (code, user_id))
    return db.cursor.fetchone() is not None

def add_claim_record(code: str, user_id: int):
    db.cursor.execute("INSERT OR IGNORE INTO redeem_claims (code, user_id, redeemed_at) VALUES (?, ?, ?)",
                      (code, user_id, now_iso()))
    # don't commit here; caller manages transaction

def increment_redeem_count(code: str):
    db.cursor.execute("UPDATE redeem_codes SET redeemed_count = COALESCE(redeemed_count,0) + 1 WHERE code = ?", (code,))
    # caller manages commit

def add_waifu_to_user(user_id: int, waifu_id: int):
    db.cursor.execute("SELECT amount FROM user_waifus WHERE user_id = ? AND waifu_id = ?", (user_id, waifu_id))
    r = db.cursor.fetchone()
    if r:
        db.cursor.execute("UPDATE user_waifus SET amount = amount + 1 WHERE user_id = ? AND waifu_id = ?", (user_id, waifu_id))
    else:
        db.cursor.execute("INSERT INTO user_waifus (user_id, waifu_id, amount) VALUES (?, ?, 1)", (user_id, waifu_id))
    # caller commits

def build_preview_text(waifu):
    # waifu: (id, name, anime, rarity, event, media_type, media_file, media_file_id)
    if not waifu:
        return "⚠️ Waifu not found."
    wid, name, anime, rarity, event, media_type, media_file, media_file_id = waifu
    lines = [
        "✨ Crickter Preview ✨",
        f"ID: {wid}",
        f"Name: {name}",
        f"Team: {anime or '—'}",
        f"Rarity: {rarity or '—'}",
        f"Theme/Event: {event or '—'}",
    ]
    return "\n".join(lines)

async def send_waifu_preview(client, chat_id, waifu, caption, reply_markup=None):
    # supports photo/video or fallback to text
    if not waifu:
        return await client.send_message(chat_id, caption, reply_markup=reply_markup)
    media_type = waifu[5]
    file = waifu[6] or waifu[7]
    try:
        if file and media_type == "photo":
            await client.send_photo(chat_id, file, caption=caption, reply_markup=reply_markup)
            return
        elif file and media_type == "video":
            await client.send_video(chat_id, file, caption=caption, reply_markup=reply_markup)
            return
    except Exception:
        # fall back to text if sending media fails
        pass
    # fallback
    await client.send_message(chat_id, caption, reply_markup=reply_markup)

# ---------------- /create (owner only) ----------------
@app.on_message(filters.command("create"))
async def create_redeem_cmd(client, message: Message):
    uid = message.from_user.id if message.from_user else None
    if not is_owner(uid):
        await message.reply_text("❌ Only the bot owner can create redeem codes.")
        return

    parts = (message.text or "").strip().split()
    if len(parts) < 3:
        await message.reply_text("Usage: /create <waifu_id> <limit>\nExample: /create 42 5")
        return

    try:
        waifu_id = int(parts[1])
        limit = int(parts[2])
        if limit <= 0:
            raise ValueError()
    except Exception:
        await message.reply_text("Invalid arguments. waifu_id and limit must be integers, limit > 0.")
        return

    waifu = waifu_row_by_id(waifu_id)
    if not waifu:
        await message.reply_text(f"❌ Waifu with ID {waifu_id} not found.")
        return

    code = find_unique_code()
    created_at = now_iso()

    # ensure columns exist again (defensive)
    ensure_redeem_tables()

    try:
        # try safe insert
        db.cursor.execute("""INSERT OR REPLACE INTO redeem_codes
                             (code, waifu_id, creator, limit_count, redeemed_count, created_at)
                             VALUES (?, ?, ?, ?, ?, ?)""",
                          (code, waifu_id, uid, limit, 0, created_at))
        db.conn.commit()
    except Exception as e:
        # if schema still incompatible, attempt minimal insert fallback
        try:
            db.cursor.execute("INSERT OR REPLACE INTO redeem_codes (code, waifu_id) VALUES (?, ?)", (code, waifu_id))
            db.conn.commit()
        except Exception as e2:
            await message.reply_text(f"❌ Failed to create code: {e}")
            return

    caption = build_preview_text(waifu) + "\n\n" + f"🎫 Code: {code}\n🔁 Limit: {limit} redeems\n🧾 Created by: {message.from_user.first_name}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Redeem", callback_data=f"redeem_cb:{code}")]])
    try:
        await send_waifu_preview(client, message.chat.id, waifu, caption, reply_markup=kb)
    except Exception:
        await message.reply_text(caption, reply_markup=kb)

# ---------------- /redeem command ----------------
@app.on_message(filters.command("redeem"))
async def redeem_cmd(client, message: Message):
    user = message.from_user
    if not user:
        return

    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.reply_text("Usage: /redeem <code>\nExample: /redeem ABCD1234")
        return

    code = parts[1].strip().upper()

    # fetch code row
    db.cursor.execute("SELECT code, waifu_id, creator, limit_count, redeemed_count, created_at FROM redeem_codes WHERE code = ?", (code,))
    row = db.cursor.fetchone()
    if not row:
        await message.reply_text("❌ Invalid code.")
        return

    _, waifu_id, creator, limit_count, redeemed_count, created_at = row
    limit_count = int(limit_count or 0)
    redeemed_count = int(redeemed_count or 0)

    if limit_count > 0 and redeemed_count >= limit_count:
        await message.reply_text("❌ Redeem limit reached for this code.")
        return

    if user_has_claimed(code, user.id):
        await message.reply_text("ℹ️ You have already redeemed this code.")
        return

    # perform atomic-ish redeem
    try:
        db.cursor.execute("BEGIN IMMEDIATE")
        db.cursor.execute("SELECT redeemed_count, limit_count FROM redeem_codes WHERE code = ? LIMIT 1", (code,))
        rc = db.cursor.fetchone()
        if not rc:
            db.conn.commit()
            await message.reply_text("❌ Code no longer available.")
            return
        cur_redeemed, cur_limit = rc
        cur_redeemed = int(cur_redeemed or 0)
        cur_limit = int(cur_limit or 0)
        if cur_limit > 0 and cur_redeemed >= cur_limit:
            db.conn.commit()
            await message.reply_text("❌ Redeem limit reached for this code.")
            return

        # add claim, increment and grant waifu
        add_claim_record(code, user.id)
        increment_redeem_count(code)
        add_waifu_to_user(user.id, waifu_id)
        db.conn.commit()
    except Exception:
        try:
            db.conn.rollback()
        except Exception:
            pass
        await message.reply_text("❌ An error occurred while redeeming. Try again later.")
        return

    waifu = waifu_row_by_id(waifu_id)
    caption = build_preview_text(waifu) + f"\n\n✅ Redeemed by {user.first_name}\n🎫 Code: {code}"
    try:
        await send_waifu_preview(client, message.chat.id, waifu, caption)
    except Exception:
        await message.reply_text(caption)

# ---------------- inline redeem button ----------------
@app.on_callback_query(filters.regex(r"^redeem_cb:(?P<code>.+)$"))
async def redeem_button_cb(client, callback: CallbackQuery):
    code = callback.matches[0].group("code").upper()
    user = callback.from_user
    if not user:
        await callback.answer("Invalid user.", show_alert=True)
        return

    db.cursor.execute("SELECT code, waifu_id, creator, limit_count, redeemed_count FROM redeem_codes WHERE code = ?", (code,))
    row = db.cursor.fetchone()
    if not row:
        await callback.answer("❌ Invalid code.", show_alert=True)
        return

    _, waifu_id, creator, limit_count, redeemed_count = row
    limit_count = int(limit_count or 0)
    redeemed_count = int(redeemed_count or 0)

    if limit_count > 0 and redeemed_count >= limit_count:
        await callback.answer("❌ Redeem limit reached for this code.", show_alert=True)
        return

    if user_has_claimed(code, user.id):
        await callback.answer("ℹ️ You have already redeemed this code.", show_alert=True)
        return

    # atomic update
    try:
        db.cursor.execute("BEGIN IMMEDIATE")
        db.cursor.execute("SELECT redeemed_count, limit_count FROM redeem_codes WHERE code = ? LIMIT 1", (code,))
        rc = db.cursor.fetchone()
        if not rc:
            db.conn.commit()
            await callback.answer("❌ Code no longer available.", show_alert=True)
            return
        cur_redeemed, cur_limit = rc
        cur_redeemed = int(cur_redeemed or 0)
        cur_limit = int(cur_limit or 0)
        if cur_limit > 0 and cur_redeemed >= cur_limit:
            db.conn.commit()
            await callback.answer("❌ Redeem limit reached.", show_alert=True)
            return

        add_claim_record(code, user.id)
        increment_redeem_count(code)
        add_waifu_to_user(user.id, waifu_id)
        db.conn.commit()
    except Exception:
        try:
            db.conn.rollback()
        except Exception:
            pass
        await callback.answer("❌ Failed to redeem. Try again later.", show_alert=True)
        return

    waifu = waifu_row_by_id(waifu_id)
    caption = build_preview_text(waifu) + f"\n\n✅ Redeemed by {user.first_name}\n🎫 Code: {code}"
    try:
        # reply in chat with preview
        await send_waifu_preview(client, callback.message.chat.id, waifu, caption)
    except Exception:
        try:
            await callback.message.reply_text(caption)
        except Exception:
            pass

    await callback.answer("✅ Redeemed successfully!", show_alert=True)