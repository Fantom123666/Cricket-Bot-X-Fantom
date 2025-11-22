# handlers/bonus.py
from main import app
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from database import Database

db = Database()

WEEKLY_BONUS_AMOUNT = 800_000  # 800,000 💎

def parse_iso_date(s):
    """Safely parse ISO datetime string stored in DB, return date or None."""
    if not s:
        return None
    try:
        # users.weekly_claim appears to store ISO-format datetimes like "2025-08-29T09:28:21.783823"
        dt = datetime.fromisoformat(s)
        return dt.date()
    except Exception:
        # fallback: try parsing just the date part
        try:
            return datetime.strptime(s.split("T")[0], "%Y-%m-%d").date()
        except Exception:
            return None


@app.on_message(filters.command("bonus"))
async def bonus_handler(client, message):
    user_id = message.from_user.id
    username = message.from_user.first_name or message.from_user.username or "there"
    today = datetime.now().date()

    # ensure user exists in users table (safe)
    db.add_user(user_id, message.from_user.username if message.from_user.username else None)

    # fetch last weekly claim timestamp (stored as text) from users.weekly_claim
    db.cursor.execute("SELECT weekly_claim FROM users WHERE user_id = ?", (user_id,))
    row = db.cursor.fetchone()
    last_claim_date = parse_iso_date(row[0]) if row and row[0] else None

    # determine eligibility (once every 7 days)
    eligible = False
    if last_claim_date is None:
        eligible = True
    else:
        eligible = (today >= last_claim_date + timedelta(days=7))

    # compute "how many times user claimed bonus" from logs table (event_type = 'bonus_claim')
    db.cursor.execute("SELECT COUNT(*) FROM logs WHERE user_id = ? AND event_type = ?", (user_id, "bonus_claim"))
    cnt_row = db.cursor.fetchone()
    claim_count = cnt_row[0] if cnt_row else 0

    today_str = today.strftime("%Y-%m-%d")
    panel_text = (
f"⋆✧˚₊‧ ʜᴇʏᴀ {username}-ᴄʜᴀɴ! ‧₊˚✧⋆\n\n"
"━━━━━━━━━━━━━━━━\n"
f"⚡️ ᴛᴏᴅᴀʏ's ᴅᴀᴛᴇ: {today_str}\n"
f"🌸 ᴡᴇᴇᴋ ɴᴜᴍʙᴇʀ: {claim_count}\n"
"━━━━━━━━━━━━━━━━\n\n"
"✧･ﾟ: *✧･ﾟ:* ʏᴏᴜʀ ʙᴏɴᴜs ʀᴇᴡᴀʀᴅs ᴀᴡᴀɪᴛ! *:･ﾟ✧*:･ﾟ✧\n\n"
"ᴘʟᴇᴀsᴇ ᴄʜᴏᴏsᴇ ғʀᴏᴍ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ᴄʟᴀɪᴍ ʏᴏᴜʀ ʀᴇᴡᴀʀᴅs~"
    )

    # Buttons: Claim if eligible else "Already Claimed"
    if eligible:
        claim_btn = InlineKeyboardButton("💎 Claim Bonus", callback_data=f"bonus_claim:{user_id}")
    else:
        claim_btn = InlineKeyboardButton("⏳ Already Claimed", callback_data="bonus_already")

    buttons = [
        [claim_btn, InlineKeyboardButton("❌ Close", callback_data="bonus_close")]
    ]
    await message.reply(panel_text, reply_markup=InlineKeyboardMarkup(buttons))


@app.on_callback_query(filters.regex(r"^bonus_claim:"))
async def claim_bonus(client, callback_query):
    try:
        user_id = int(callback_query.data.split(":")[1])
    except Exception:
        await callback_query.answer("Invalid request.", show_alert=True)
        return

    today = datetime.now().date()

    # ensure user exists
    db.add_user(user_id)

    # re-check last claim (race-condition safe)
    db.cursor.execute("SELECT weekly_claim FROM users WHERE user_id = ?", (user_id,))
    row = db.cursor.fetchone()
    last_claim_date = parse_iso_date(row[0]) if row and row[0] else None

    if last_claim_date and today < last_claim_date + timedelta(days=7):
        # not eligible
        await callback_query.answer("⏳ You already claimed your weekly bonus. Come back later!", show_alert=True)
        return

    # Give crystals using your existing method (updates given_crystals column)
    db.add_crystals(user_id, given=WEEKLY_BONUS_AMOUNT)

    # Update users.weekly_claim to current ISO datetime string
    now_iso = datetime.now().isoformat()
    db.cursor.execute("UPDATE users SET weekly_claim = ? WHERE user_id = ?", (now_iso, user_id))
    db.conn.commit()

    # Log the event
    db.log_event("bonus_claim", user_id=user_id, details=f"weekly bonus {WEEKLY_BONUS_AMOUNT}")

    # Count claims for display
    db.cursor.execute("SELECT COUNT(*) FROM logs WHERE user_id = ? AND event_type = ?", (user_id, "bonus_claim"))
    cnt_row = db.cursor.fetchone()
    claim_count = cnt_row[0] if cnt_row else 1

    # Edit original panel to confirmation text & remove buttons
    await callback_query.message.edit_text(
        f"🎉 You claimed your weekly bonus of {WEEKLY_BONUS_AMOUNT:,} 💎!\n"
        f"🌸 Total weekly bonus claims (historical): {claim_count}"
    )
    await callback_query.answer("✅ Bonus added!")


@app.on_callback_query(filters.regex(r"^bonus_already"))
async def bonus_already(client, callback_query):
    await callback_query.answer("⏳ You’ve already claimed this week!", show_alert=True)


@app.on_callback_query(filters.regex(r"^bonus_close"))
async def close_bonus_menu(client, callback_query):
    # delete the panel message
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()
