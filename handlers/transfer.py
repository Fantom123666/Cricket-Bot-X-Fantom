# handlers/transfer.py

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import app, Config
import sqlite3
import re

DB_PATH = "waifu_bot.db"

# Ownership column candidates (check these names in table schemas)
OWNERSHIP_COLS = [
    "user_id", "owner_id", "owner", "userid", "owner_user_id", "user"
]
# Columns that commonly indicate a collection item row
ITEM_COL_HINTS = [
    "waifu", "waifu_id", "card", "card_id", "collection", "collection_id", "item", "item_id"
]

# Tables we should never touch for transfer
EXCLUDE_TABLES = {"users", "user_claims", "waifu_cards", "sqlite_sequence"}

# Build a DB connection helper
def get_db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn


def detect_candidate_tables(conn):
    """
    Detect tables that look like they hold per-user collections.
    Returns a list of dicts: {"table": name, "owner_col": colname}
    """
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]

    candidates = []
    for t in tables:
        if t in EXCLUDE_TABLES:
            continue
        try:
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info('{t}')").fetchall()]
        except Exception:
            continue

        # normalize lower-case
        cols_l = [c.lower() for c in cols]

        # find ownership column
        owner_col = None
        for oc in OWNERSHIP_COLS:
            if oc in cols_l:
                # find original case-sensitive column name
                owner_col = cols[cols_l.index(oc)]
                break

        # quick skip if no ownership column
        if not owner_col:
            # but if table name strongly matches known patterns, try to use 'user_id' if present
            if t.lower() in ("user_cards", "user_waifus", "user_collections", "owned_waifus", "user_items"):
                # try to use any column that looks like user id
                for oc in OWNERSHIP_COLS:
                    if oc in cols_l:
                        owner_col = cols[cols_l.index(oc)]
                        break

        # find at least one item-like column
        has_item_hint = False
        for hint in ITEM_COL_HINTS:
            if hint in cols_l:
                has_item_hint = True
                break

        # accept if we have owner_col and item hint OR table name looks promising
        if owner_col and (has_item_hint or t.lower() in ("user_cards", "user_waifus", "user_collections", "owned_waifus", "user_items")):
            candidates.append({"table": t, "owner_col": owner_col})

    return candidates


# helper to get owner id from config in a few possible attribute names
def get_owner_id_from_config():
    for name in ("OWNER_ID", "OWNER", "OWNER_USER_ID", "OWNERID"):
        val = getattr(Config, name, None)
        if val:
            try:
                return int(val)
            except Exception:
                # maybe string like "@username" or "7606..."
                try:
                    return int(str(val).strip())
                except Exception:
                    pass
    return None


# ---------------- /transfer command ----------------
@app.on_message(filters.command("transfer"))
async def transfer_command(client, message):
    """
    Usage (owner only):
    /transfer <from_user_id> <to_user_id>

    The bot detects collection tables in the DB and will present a confirmation that
    shows how many rows will be moved. Owner must confirm.
    """
    sender = message.from_user
    owner_id = get_owner_id_from_config()

    if owner_id is None:
        await message.reply_text("❌ Owner ID not configured (Config.OWNER_ID missing). Transfer cancelled.")
        return

    if sender.id != owner_id:
        await message.reply_text("❌ Only the bot owner can use this command.")
        return

    args = message.text.split()
    if len(args) != 3:
        await message.reply_text("Usage: /transfer <from_user_id> <to_user_id>")
        return

    try:
        from_uid = int(args[1])
        to_uid = int(args[2])
    except ValueError:
        await message.reply_text("❌ User IDs must be integers. Example: /transfer 123456789 987654321")
        return

    if from_uid == to_uid:
        await message.reply_text("❌ Source and destination IDs are the same. Nothing to do.")
        return

    # open DB and detect candidate tables
    conn = get_db_conn()
    cur = conn.cursor()

    candidates = detect_candidate_tables(conn)

    if not candidates:
        # give a helpful list of tables (so owner can tell which is correct)
        tbls = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        await message.reply_text(
            "❌ Could not detect any collection tables automatically.\n"
            "Detected DB tables: \n" + ", ".join(tbls) + "\n\n"
            "If your collection table has a different name or schema, tell me the table name and column that stores the owner (e.g. user_id) and I can adjust the script."
        )
        conn.close()
        return

    # Prepare a summary (counts per candidate)
    summary_lines = []
    total_rows = 0
    for c in candidates:
        t = c["table"]
        owner_col = c["owner_col"]
        try:
            cur.execute(f"SELECT COUNT(*) FROM '{t}' WHERE {owner_col} = ?", (from_uid,))
            cnt = cur.fetchone()[0]
        except Exception:
            cnt = 0
        summary_lines.append(f"• {t}: {cnt} rows (owner column: {owner_col})")
        total_rows += cnt

    if total_rows == 0:
        await message.reply_text(f"⚠️ No collection rows found for user {from_uid} in detected tables. Nothing to transfer.")
        conn.close()
        return

    # ask for confirmation
    confirm_payload = f"transfer_confirm:{from_uid}:{to_uid}"
    cancel_payload = f"transfer_cancel:{from_uid}:{to_uid}"

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm transfer", callback_data=confirm_payload), InlineKeyboardButton("❌ Cancel", callback_data=cancel_payload)]
    ])

    await message.reply_text(
        "⚠️ Transfer confirmation required\n\n"
        f"From user: {from_uid}\nTo user: {to_uid}\n\n"
        "The following tables appear to contain collection rows that will be moved:\n"
        + "\n".join(summary_lines)
        + "\n\nThis operation will move the rows so that the source user will no longer own them. Proceed?",
        reply_markup=buttons
    )

    conn.close()


# ---------------- Callback handlers ----------------
@app.on_callback_query(filters.regex(r"^transfer_cancel:(\d+):(\d+)$"))
async def transfer_cancel_cb(client, callback: CallbackQuery):
    data = callback.data or ""
    m = re.match(r"^transfer_cancel:(\d+):(\d+)$", data)
    if not m:
        await callback.answer("Invalid data.")
        return
    from_uid = int(m.group(1))
    to_uid = int(m.group(2))

    owner_id = get_owner_id_from_config()
    if callback.from_user.id != owner_id:
        await callback.answer("Only owner can cancel.", show_alert=True)
        return

    try:
        await callback.message.edit_text(f"❌ Transfer from {from_uid} to {to_uid} cancelled by owner.")
    except Exception:
        pass
    await callback.answer("Cancelled.")


@app.on_callback_query(filters.regex(r"^transfer_confirm:(\d+):(\d+)$"))
async def transfer_confirm_cb(client, callback: CallbackQuery):
    data = callback.data or ""
    m = re.match(r"^transfer_confirm:(\d+):(\d+)$", data)
    if not m:
        await callback.answer("Invalid data.")
        return
    from_uid = int(m.group(1))
    to_uid = int(m.group(2))

    owner_id = get_owner_id_from_config()
    if callback.from_user.id != owner_id:
        await callback.answer("Only owner can confirm.", show_alert=True)
        return

    conn = get_db_conn()
    cur = conn.cursor()

    candidates = detect_candidate_tables(conn)

    # perform updates inside a transaction
    moved_summary = []
    try:
        for c in candidates:
            t = c["table"]
            owner_col = c["owner_col"]
            try:
                # count first
                cur.execute(f"SELECT COUNT(*) FROM '{t}' WHERE {owner_col} = ?", (from_uid,))
                cnt_before = cur.fetchone()[0]

                if cnt_before > 0:
                    cur.execute(f"UPDATE '{t}' SET {owner_col} = ? WHERE {owner_col} = ?", (to_uid, from_uid))
                    moved_summary.append((t, owner_col, cnt_before))
            except Exception as e:
                # skip problematic table but collect info
                moved_summary.append((t, owner_col, f"error: {e}"))

        conn.commit()
    except Exception as e:
        conn.rollback()
        await callback.message.edit_text(f"❌ Transfer failed: {e}")
        conn.close()
        await callback.answer("Transfer failed.", show_alert=True)
        return

    # Build result text
    lines = [f"✅ Transfer complete from {from_uid} to {to_uid}. Rows moved:"]
    for row in moved_summary:
        lines.append(f"• {row[0]} (col {row[1]}): {row[2]}")

    try:
        await callback.message.edit_text("\n".join(lines))
    except Exception:
        pass

    conn.close()
    await callback.answer("Transfer completed.")
