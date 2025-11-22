# handlers/botuserlist.py
"""
Owner-only command: /listuser
Sends the owner a .txt file containing every user found in the DB and their waifu holdings.

Requirements / behavior:
 - Only the owner (ID 7558715645) can run this command.
 - The handler collects user IDs from user_waifus and pending_offers (from_user, to_user).
 - For each user it fetches a best-effort Telegram name (via get_users) and then
   fetches that user's waifu holdings (joined with waifu_cards for names/rarity).
 - Produces a readable text report and sends it to the owner as a .txt document.
"""

import io
from datetime import datetime
from pyrogram import filters
from config import app
from database import Database

OWNER_ID = 7558715645  # owner id from your config/context

db = Database()


def get_all_user_ids_from_db():
    """Collect distinct user ids from user_waifus and pending_offers"""
    ids = set()
    try:
        db.cursor.execute("SELECT DISTINCT user_id FROM user_waifus")
        for row in db.cursor.fetchall():
            if row and row[0]:
                ids.add(int(row[0]))
    except Exception:
        # table might not exist or query fail — ignore and continue
        pass

    try:
        db.cursor.execute("SELECT DISTINCT from_user FROM pending_offers")
        for row in db.cursor.fetchall():
            if row and row[0]:
                ids.add(int(row[0]))
    except Exception:
        pass

    try:
        db.cursor.execute("SELECT DISTINCT to_user FROM pending_offers")
        for row in db.cursor.fetchall():
            if row and row[0]:
                ids.add(int(row[0]))
    except Exception:
        pass

    return sorted(ids)


def get_user_waifus(user_id: int):
    """
    Return list of tuples (waifu_id, amount, name, anime, rarity)
    and total count (sum of amounts)
    """
    items = []
    total = 0
    try:
        db.cursor.execute("""
            SELECT uw.waifu_id, uw.amount, wc.name, wc.anime, wc.rarity
            FROM user_waifus uw
            LEFT JOIN waifu_cards wc ON uw.waifu_id = wc.id
            WHERE uw.user_id = ?
        """, (user_id,))
        for row in db.cursor.fetchall():
            wid = row[0]
            amt = int(row[1]) if row[1] is not None else 0
            name = row[2] or "Unknown"
            anime = row[3] or "—"
            rarity = row[4] or "—"
            items.append((wid, amt, name, anime, rarity))
            total += amt
    except Exception:
        # table might not exist or query fail — return empty
        pass
    return items, total


@app.on_message(filters.command("listuser"))
async def listuser_handler(client, message):
    # Owner-only
    if not message.from_user or message.from_user.id != OWNER_ID:
        await message.reply_text("❌ This command is owner-only.")
        return

    await message.reply_text("🔎 Generating user list... (this may take a few seconds)")

    user_ids = get_all_user_ids_from_db()
    # If DB has no users, return a small file indicating that
    if not user_ids:
        text = "No users found in the database (no rows in user_waifus or pending_offers).\n"
        bio = io.BytesIO(text.encode("utf-8"))
        bio.name = f"user_list_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            await client.send_document(OWNER_ID, bio, caption="User list (empty).")
        except Exception as e:
            await message.reply_text(f"Failed to send file to owner: {e}")
        return

    # Build report
    lines = []
    header = f"User list generated: {datetime.utcnow().isoformat()} UTC\nTotal users found: {len(user_ids)}\n"
    lines.append(header)
    lines.append("=" * 60)
    for uid in user_ids:
        # Try to fetch Telegram user info (best-effort)
        t_first = t_last = t_un = "Unknown"
        try:
            tg = await client.get_users(uid)
            if tg:
                t_first = tg.first_name or ""
                t_last = tg.last_name or ""
                t_un = f"@{tg.username}" if getattr(tg, "username", None) else ""
        except Exception:
            # ignore failures, leave Unknown
            pass

        lines.append(f"\nUser ID: {uid}")
        name_line = f"Name: {t_first} {t_last}".strip()
        if t_un:
            name_line += f" ({t_un})"
        lines.append(name_line)

        # fetch waifu holdings
        waifus, total = get_user_waifus(uid)
        lines.append(f"Total cards: {total}")
        if waifus:
            lines.append("Holdings:")
            for wid, amt, name, anime, rarity in waifus:
                lines.append(f" - ID {wid} | x{amt} | {name} | {anime} | Rarity: {rarity}")
        else:
            lines.append("Holdings: None")

        # small separator between users
        lines.append("-" * 1)

    content = "\n".join(lines)
    bio = io.BytesIO(content.encode("utf-8"))
    bio.name = f"user_list_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"

    # Send the file to owner (also confirm in chat)
    try:
        await client.send_document(OWNER_ID, bio, caption=f"Full user list ({len(user_ids)} users).")
        await message.reply_text("✅ Sent the user list file to the owner (you). Check your DMs.")
    except Exception as e:
        # fallback: try to send in the same chat
        try:
            bio.seek(0)
            await client.send_document(message.chat.id, bio, caption=f"User list (failed DM to owner): {e}")
        except Exception as e2:
            await message.reply_text(f"Failed to send user list: {e}; fallback also failed: {e2}")
