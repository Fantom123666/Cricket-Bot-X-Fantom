# handlers/restart_take.py
"""
Owner-only maintenance commands:

/restart
    - Owner-only. Attempts to gracefully restart the bot process by re-execing the Python interpreter.
      This is the usual approach for self-restart; it works when the process manager (systemd, pm2, docker, etc.)
      allows the process to re-exec or will auto-restart the process. The handler notifies owner before doing so.

 /take
    - Owner-only. Remove waifu cards from a user's collection.
    - Usage (reply to user's message):
        /take <waifu_id> [qty]
      Removes `qty` copies (default 1) of <waifu_id> from the replied-to user.
    - Usage (not reply):
        /take <user_id> <waifu_id> [qty]
      Removes `qty` copies (default 1) of <waifu_id> from the specified user_id.

    Behavior:
      - If the user doesn't have that waifu, nothing is removed.
      - If the user's amount <= qty, the row is deleted (all copies removed).
      - Confirmation is sent to the owner and (best-effort) a DM to the affected user.

 /tcrystals
    - Owner-only. Subtract crystals from a user's balance.
    - Usage (reply):
        /tcrystals <amount>
      Subtracts <amount> from the replied-to user's balance.
    - Usage (not reply):
        /tcrystals <user_id> <amount>
      Subtracts <amount> from the specified user.

    Behavior:
      - If user's balance is missing it will be treated as 0.
      - If amount to remove >= current balance, balance will be set to 0.
      - Confirmation to owner and best-effort DM to target user.

This file expects the same DB used by other handlers: "waifu_bot.db".
"""

import os
import sys
import sqlite3
from datetime import datetime

from pyrogram import filters
from pyrogram.types import Message
from config import app, Config

DB_PATH = "waifu_bot.db"

# Owner id must exist in Config
OWNER_ID = getattr(Config, "OWNER_ID", None)

# --- DB connection (same approach used across your handlers) ---
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()


def _is_owner(msg: Message) -> bool:
    return bool(msg.from_user and OWNER_ID and msg.from_user.id == OWNER_ID)


# ---------------- /restart ----------------
@app.on_message(filters.command("restart"))
async def restart_handler(client, message: Message):
    if not _is_owner(message):
        await message.reply_text("❌ This command is owner-only.")
        return

    await message.reply_text("♻️ Restarting bot now (attempting to re-exec Python).")
    # flush DB and close connection
    try:
        conn.commit()
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass

    # Notify logs and re-exec the process. This replaces current process image.
    # Many process managers will pick this up or you may rely on an external supervisor.
    try:
        python = sys.executable
        os.execv(python, [python] + sys.argv)
    except Exception as e:
        # If execv fails, attempt a crude exit so a process manager may restart
        try:
            await client.send_message(OWNER_ID, f"⚠️ Restart exec failed: {e}. Exiting process as fallback.")
        except Exception:
            pass
        os._exit(0)


# ---------------- /take (remove waifu cards from user) ----------------
@app.on_message(filters.command("take"))
async def take_waifu_handler(client, message: Message):
    if not _is_owner(message):
        await message.reply_text("❌ This command is owner-only.")
        return

    parts = (message.text or "").strip().split()
    # Determine target user & params
    if message.reply_to_message and message.reply_to_message.from_user:
        # Format: reply -> /take <waifu_id> [qty]
        if len(parts) < 2:
            await message.reply_text("Usage (reply): /take <waifu_id> [qty]")
            return
        try:
            waifu_id = int(parts[1])
        except Exception:
            await message.reply_text("❌ Invalid waifu id. It must be a number.")
            return
        qty = 1
        if len(parts) >= 3:
            try:
                qty = max(1, int(parts[2]))
            except Exception:
                qty = 1
        target_user_id = message.reply_to_message.from_user.id
    else:
        # Not reply -> /take <user_id> <waifu_id> [qty]
        if len(parts) < 3:
            await message.reply_text("Usage: /take <user_id> <waifu_id> [qty]\nOr reply to a user's message: /take <waifu_id> [qty]")
            return
        try:
            target_user_id = int(parts[1])
            waifu_id = int(parts[2])
        except Exception:
            await message.reply_text("❌ Invalid user id or waifu id. They must be numbers.")
            return
        qty = 1
        if len(parts) >= 4:
            try:
                qty = max(1, int(parts[3]))
            except Exception:
                qty = 1

    # Fetch current ownership
    try:
        cursor.execute("SELECT id, amount FROM user_waifus WHERE user_id = ? AND waifu_id = ?", (target_user_id, waifu_id))
        row = cursor.fetchone()
    except Exception as e:
        await message.reply_text(f"❌ DB query failed: {e}")
        return

    if not row:
        await message.reply_text(f"ℹ️ User `{target_user_id}` does not own waifu ID {waifu_id}. Nothing done.")
        return

    row_id, amount = row[0], int(row[1] or 0)
    if amount <= 0:
        # defensive
        try:
            cursor.execute("DELETE FROM user_waifus WHERE id = ?", (row_id,))
            conn.commit()
        except Exception:
            pass
        await message.reply_text(f"✅ Removed record for waifu ID {waifu_id} from user {target_user_id} (had zero).")
        return

    if qty >= amount:
        # remove the row entirely
        try:
            cursor.execute("DELETE FROM user_waifus WHERE id = ?", (row_id,))
            conn.commit()
            await message.reply_text(f"🗑 Removed all ({amount}) copies of waifu ID {waifu_id} from user {target_user_id}.")
            # notify target user
            try:
                await client.send_message(target_user_id, f"⚠️ An admin action removed {amount}x waifu ID {waifu_id} from your collection.")
            except Exception:
                pass
        except Exception as e:
            await message.reply_text(f"❌ Failed to remove waifu(s): {e}")
    else:
        # subtract qty
        new_amount = amount - qty
        try:
            cursor.execute("UPDATE user_waifus SET amount = ? WHERE id = ?", (new_amount, row_id))
            conn.commit()
            await message.reply_text(f"✅ Removed {qty}x of waifu ID {waifu_id} from user {target_user_id}. Remaining: {new_amount}")
            try:
                await client.send_message(target_user_id, f"⚠️ An admin action removed {qty}x waifu ID {waifu_id} from your collection. Remaining: {new_amount}")
            except Exception:
                pass
        except Exception as e:
            await message.reply_text(f"❌ Failed to update record: {e}")


# ---------------- /tcrystals (subtract crystals from user balance) ----------------
@app.on_message(filters.command("tcrystals"))
async def take_crystals_handler(client, message: Message):
    if not _is_owner(message):
        await message.reply_text("❌ This command is owner-only.")
        return

    parts = (message.text or "").strip().split()
    if message.reply_to_message and message.reply_to_message.from_user:
        # reply form: /tcrystals <amount>
        if len(parts) < 2:
            await message.reply_text("Usage (reply): /tcrystals <amount>")
            return
        try:
            amount = int(parts[1])
            amount = max(0, amount)
        except Exception:
            await message.reply_text("❌ Invalid amount. It must be a number.")
            return
        target_user_id = message.reply_to_message.from_user.id
    else:
        # /tcrystals <user_id> <amount>
        if len(parts) < 3:
            await message.reply_text("Usage: /tcrystals <user_id> <amount>\nOr reply to a user's message: /tcrystals <amount>")
            return
        try:
            target_user_id = int(parts[1])
            amount = int(parts[2])
            amount = max(0, amount)
        except Exception:
            await message.reply_text("❌ Invalid user id or amount. Must be numbers.")
            return

    # fetch current balance
    try:
        cursor.execute("SELECT balance FROM user_balances WHERE user_id = ?", (target_user_id,))
        r = cursor.fetchone()
    except Exception as e:
        await message.reply_text(f"❌ DB query failed: {e}")
        return

    current = int(r[0]) if r and r[0] is not None else 0
    if current <= 0:
        await message.reply_text(f"ℹ️ User {target_user_id} has no crystals (balance = 0). Nothing to remove.")
        return

    if amount <= 0:
        await message.reply_text("❌ Amount must be greater than zero.")
        return

    if amount >= current:
        new_balance = 0
    else:
        new_balance = current - amount

    # update DB (insert or update)
    try:
        # ensure there's a row
        cursor.execute("SELECT user_id FROM user_balances WHERE user_id = ?", (target_user_id,))
        if cursor.fetchone():
            cursor.execute("UPDATE user_balances SET balance = ? WHERE user_id = ?", (new_balance, target_user_id))
        else:
            cursor.execute("INSERT INTO user_balances (user_id, balance) VALUES (?, ?)", (target_user_id, new_balance))
        conn.commit()
        await message.reply_text(f"✅ Updated crystals for user {target_user_id}: {current} -> {new_balance} (removed {current - new_balance}).")
        try:
            await client.send_message(target_user_id, f"⚠️ An admin action adjusted your crystals: {current} -> {new_balance}.")
        except Exception:
            pass
    except Exception as e:
        await message.reply_text(f"❌ Failed to update balance: {e}")
