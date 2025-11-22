# handlers/reset.py
import sqlite3
import time
import random
import traceback
from typing import Dict, Any, List

from pyrogram import filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from config import app, Config

DB_PATH = "waifu_bot.db"
pending_resets: Dict[str, Dict[str, Any]] = {}  # nonce -> info


def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.cursor()
    try:
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        return column in cols
    except Exception:
        return False


def get_user_collection_count(conn: sqlite3.Connection, user_id: int) -> int:
    """
    Return total number of card units the user has (using 'amount' column if present),
    otherwise return row-count.
    """
    cur = conn.cursor()
    if table_exists(conn, "user_waifus") and column_exists(conn, "user_waifus", "amount"):
        cur.execute("SELECT COALESCE(SUM(amount),0) FROM user_waifus WHERE user_id=?", (user_id,))
        r = cur.fetchone()
        return int(r[0]) if r and r[0] is not None else 0
    elif table_exists(conn, "user_waifus"):
        cur.execute("SELECT COUNT(*) FROM user_waifus WHERE user_id=?", (user_id,))
        r = cur.fetchone()
        return int(r[0]) if r else 0
    else:
        # if the main table doesn't exist, try some common alternatives (safe, non-explosive)
        # check "collections", "user_cards", "inventory" etc.
        alt_tables = ["collections", "user_cards", "user_collection", "inventory", "user_inventory"]
        total = 0
        for t in alt_tables:
            if table_exists(conn, t):
                if column_exists(conn, t, "amount"):
                    cur.execute(f"SELECT COALESCE(SUM(amount),0) FROM {t} WHERE user_id=?", (user_id,))
                    r = cur.fetchone()
                    total += int(r[0]) if r and r[0] is not None else 0
                else:
                    cur.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id=?", (user_id,))
                    r = cur.fetchone()
                    total += int(r[0]) if r else 0
        return total


def delete_user_collections(conn: sqlite3.Connection, user_id: int) -> int:
    """
    Delete user's collection rows from known tables.
    Returns total units deleted (sum of amounts if present; otherwise number of rows deleted).
    This function commits the changes.
    """
    cur = conn.cursor()
    total_removed_units = 0

    # Primary known table
    if table_exists(conn, "user_waifus"):
        if column_exists(conn, "user_waifus", "amount"):
            # sum amount to report then delete
            cur.execute("SELECT COALESCE(SUM(amount),0) FROM user_waifus WHERE user_id=?", (user_id,))
            r = cur.fetchone()
            removed_units = int(r[0]) if r and r[0] is not None else 0
            total_removed_units += removed_units
        else:
            cur.execute("SELECT COUNT(*) FROM user_waifus WHERE user_id=?", (user_id,))
            r = cur.fetchone()
            removed_units = int(r[0]) if r else 0
            total_removed_units += removed_units

        cur.execute("DELETE FROM user_waifus WHERE user_id=?", (user_id,))

    # Try a few likely alternative tables (safe, check existence first)
    alt_tables = ["collections", "user_cards", "user_collection", "inventory", "user_inventory"]
    for t in alt_tables:
        if table_exists(conn, t) and column_exists(conn, t, "user_id"):
            if column_exists(conn, t, "amount"):
                cur.execute(f"SELECT COALESCE(SUM(amount),0) FROM {t} WHERE user_id=?", (user_id,))
                r = cur.fetchone()
                removed = int(r[0]) if r and r[0] is not None else 0
                total_removed_units += removed
            else:
                cur.execute(f"SELECT COUNT(*) FROM {t} WHERE user_id=?", (user_id,))
                r = cur.fetchone()
                removed = int(r[0]) if r else 0
                total_removed_units += removed

            cur.execute(f"DELETE FROM {t} WHERE user_id=?", (user_id,))

    conn.commit()
    return total_removed_units


# ----------------- /reset command -----------------
@app.on_message(filters.command("reset"))
async def cmd_reset(client, message: Message):
    """
    Usage: Reply to a user's message with /reset
    Only owner or admins allowed to run. Shows Confirm / Cancel inline buttons.
    """
    try:
        issuer = message.from_user
        issuer_id = issuer.id if issuer else None

        # permission check
        allowed = False
        if issuer_id == Config.OWNER_ID:
            allowed = True
        else:
            # support Config.ADMINS being list or tuple or undefined
            if hasattr(Config, "ADMINS") and Config.ADMINS:
                try:
                    if issuer_id in Config.ADMINS:
                        allowed = True
                except Exception:
                    allowed = False

        if not allowed:
            await message.reply_text("❌ Only the Owner or Admins can use /reset.")
            return

        # must be a reply
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply_text("❌ Usage: Reply to the target user's message with `/reset` to wipe their collection.")
            return

        target = message.reply_to_message.from_user
        target_id = target.id

        # protective checks
        if target_id == Config.OWNER_ID:
            await message.reply_text("⛔ You cannot reset the Owner's collection.")
            return

        # if target is admin and issuer is not owner -> deny
        if hasattr(Config, "ADMINS") and Config.ADMINS and target_id in Config.ADMINS and issuer_id != Config.OWNER_ID:
            await message.reply_text("⛔ Only the Owner can reset an Admin's collection.")
            return

        # do not allow resetting bot accounts
        if getattr(target, "is_bot", False):
            await message.reply_text("❌ You cannot reset a bot account.")
            return

        # build confirmation prompt
        first = getattr(target, "first_name", "") or "Unknown"
        uname = ("@" + target.username) if getattr(target, "username", None) else ""
        prompt_lines = [
            "⚠️ Confirm collection reset ⚠️",
            "",
            f"Target: {first} {uname}".strip(),
            f"User ID: {target_id}",
            "",
            "This will permanently DELETE the user's entire collection (all waifu cards).",
            "Only confirm if you are sure. This action cannot be undone.",
            "",
            "Press ✅ Confirm to proceed or ❌ Cancel to abort."
        ]
        prompt = "\n".join(prompt_lines)

        # nonce for this operation
        nonce = str(int(time.time() * 1000)) + str(random.randint(1000, 9999))
        pending_resets[nonce] = {
            "issuer": issuer_id,
            "target": target_id,
            "chat_id": message.chat.id,
            "created": time.time(),
        }

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Confirm", callback_data=f"reset_confirm:{nonce}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"reset_cancel:{nonce}"),
                ]
            ]
        )

        # send as a reply to the target's message (so chat context is clear)
        try:
            await message.reply_text(prompt, reply_markup=kb)
        except Exception:
            # fallback
            await client.send_message(message.chat.id, prompt, reply_markup=kb)

    except Exception as e:
        traceback.print_exc()
        try:
            await message.reply_text("❌ Internal error while preparing reset. Check logs.")
        except:
            pass


# ----------------- Callback handler -----------------
@app.on_callback_query(filters.regex(r"^reset_(confirm|cancel):"))
async def cb_reset(client, callback: CallbackQuery):
    try:
        data = callback.data  # e.g. "reset_confirm:12345"
        action, nonce = data.split(":", 1)
        info = pending_resets.get(nonce)
        if not info:
            await callback.answer("⚠️ This reset request has expired or is invalid.", show_alert=True)
            return

        issuer_id = info["issuer"]
        target_id = info["target"]
        created = info.get("created", 0)
        chat_id = info.get("chat_id")

        # only the issuer or owner can confirm/cancel
        user_id = callback.from_user.id
        if user_id != issuer_id and user_id != Config.OWNER_ID:
            await callback.answer("⛔ Only the admin who initiated this reset (or the Owner) may confirm/cancel.", show_alert=True)
            return

        # expiry (e.g., 5 minutes)
        if time.time() - created > 300:
            pending_resets.pop(nonce, None)
            try:
                await callback.message.edit_text("⛔ Reset request expired.")
            except:
                pass
            await callback.answer("Reset request expired.", show_alert=True)
            return

        if action == "reset_cancel":
            pending_resets.pop(nonce, None)
            try:
                await callback.message.edit_text("❌ Reset cancelled by admin.")
            except:
                pass
            await callback.answer("Reset cancelled.", show_alert=False)
            return

        # action == confirm -> perform deletion
        conn = _conn()
        try:
            before_count = get_user_collection_count(conn, target_id)
            removed_units = delete_user_collections(conn, target_id)
            # if delete_user_collections couldn't compute units but returns 0, fallback to before_count
            if removed_units == 0 and before_count:
                removed_units = before_count

            # remove pending entry
            pending_resets.pop(nonce, None)

            # edit callback message to show result
            try:
                await callback.message.edit_text(
                    f"✅ Reset completed!\n\nTarget ID: {target_id}\nRemoved units: {removed_units}"
                )
            except:
                pass

            # notify issuer in chat (already edited), also attempt to DM target
            try:
                await client.send_message(
                    callback.message.chat.id,
                    f"✅ Collection reset by {callback.from_user.mention} for user ID {target_id} — removed {removed_units} units."
                )
            except:
                pass

            # DM target if possible (best-effort)
            try:
                await client.send_message(target_id, f"⚠️ Your collection was reset by an admin. If you think this is a mistake contact support.")
            except:
                # ignore if blocked or cannot message
                pass

            await callback.answer("Reset completed.", show_alert=False)
        finally:
            try:
                conn.close()
            except:
                pass

    except Exception:
        traceback.print_exc()
        try:
            await callback.answer("❌ Internal error while processing reset.", show_alert=True)
        except:
            pass
