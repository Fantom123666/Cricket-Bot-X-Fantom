# handlers/affection.py
from main import app
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta, date
from database import Database

db = Database()

# Configuration
ENERGY_PER_UPGRADE = 1000      # energy required to increase bond by 1
DAILY_ENERGY_CAP = 500         # max energy user can add per day (per waifu)
MAX_BOND_LEVEL = 10
ADD_ENERGY_AMOUNT = 500        # amount added when user presses "Add Energy (+500)"


# Ensure table exists
def ensure_affection_table():
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_affection (
            user_id INTEGER,
            waifu_id INTEGER,
            bond_level INTEGER DEFAULT 1,
            energy_accum INTEGER DEFAULT 0,
            last_upgrade_iso TEXT,
            daily_added INTEGER DEFAULT 0,
            daily_reset_date TEXT,
            PRIMARY KEY (user_id, waifu_id)
        )
    """)
    db.conn.commit()

ensure_affection_table()


# --- DB helpers for affection ---
def get_affection_record(user_id: int, waifu_id: int):
    db.cursor.execute("""
        SELECT user_id, waifu_id, bond_level, energy_accum, last_upgrade_iso, daily_added, daily_reset_date
        FROM user_affection
        WHERE user_id = ? AND waifu_id = ?
    """, (user_id, waifu_id))
    row = db.cursor.fetchone()
    if not row:
        # create default record
        today = date.today().isoformat()
        db.cursor.execute("""
            INSERT INTO user_affection (user_id, waifu_id, bond_level, energy_accum, last_upgrade_iso, daily_added, daily_reset_date)
            VALUES (?, ?, 1, 0, NULL, 0, ?)
        """, (user_id, waifu_id, today))
        db.conn.commit()
        return {
            "user_id": user_id,
            "waifu_id": waifu_id,
            "bond_level": 1,
            "energy_accum": 0,
            "last_upgrade_iso": None,
            "daily_added": 0,
            "daily_reset_date": today
        }
    return {
        "user_id": row[0],
        "waifu_id": row[1],
        "bond_level": row[2],
        "energy_accum": row[3],
        "last_upgrade_iso": row[4],
        "daily_added": row[5],
        "daily_reset_date": row[6]
    }


def update_affection_record(user_id: int, waifu_id: int, **kwargs):
    # build dynamic update
    cols = []
    vals = []
    for k, v in kwargs.items():
        cols.append(f"{k} = ?")
        vals.append(v)
    if not cols:
        return
    vals.extend([user_id, waifu_id])
    sql = f"UPDATE user_affection SET {', '.join(cols)} WHERE user_id = ? AND waifu_id = ?"
    db.cursor.execute(sql, tuple(vals))
    db.conn.commit()


# Utility: parse ISO timestamp string to datetime
def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        try:
            return datetime.strptime(s.split("T")[0], "%Y-%m-%d")
        except Exception:
            return None


# Render the affection panel caption
def build_affection_caption(waifu_row, affection):
    # waifu_row columns: id, name, anime, rarity, event, media_type, media_file, media_file_id (common schema)
    wid = waifu_row[0]
    name = waifu_row[1]
    anime = waifu_row[2] if len(waifu_row) > 2 else ""
    rarity = waifu_row[3] if len(waifu_row) > 3 else ""
    event = waifu_row[4] if len(waifu_row) > 4 else ""
    # owned count
    db.cursor.execute("SELECT amount FROM user_waifus WHERE user_id = ? AND waifu_id = ?", (affection["user_id"], wid))
    r = db.cursor.fetchone()
    owned = r[0] if r else 0

    bond_level = affection["bond_level"]
    energy = affection["energy_accum"]
    daily_added = affection["daily_added"] or 0
    last_upgrade_iso = affection["last_upgrade_iso"]
    last_upgrade_dt = parse_iso(last_upgrade_iso)
    cooldown_left = None
    if last_upgrade_dt:
        delta = last_upgrade_dt + timedelta(hours=24) - datetime.now()
        if delta.total_seconds() > 0:
            cooldown_left = delta

    lines = [
        f"💞 Waifu: {name}",
        "━━━━━━━━━━━━━━━━",
        f"📛 ID: {wid}",
        f"💠 Anime: {anime or '—'}",
        f"✨ Rarity: {rarity or '—'}",
        f"🎭 Theme: {event or '—'}",
        f"🧾 Owned: {owned}×",
        "━━━━━━━━━━━━━━━━",
        f"🔰 Bond Level: {bond_level}/{MAX_BOND_LEVEL}",
        f"🔥 Energy: {energy}/{ENERGY_PER_UPGRADE} (Daily added: {daily_added}/{DAILY_ENERGY_CAP})"
    ]
    if cooldown_left:
        hours = int(cooldown_left.total_seconds() // 3600)
        mins = int((cooldown_left.total_seconds() % 3600) // 60)
        lines.append(f"⏳ Upgrade cooldown: {hours}h {mins}m remaining")
    return "\n".join(lines)


# Helper to send waifu media + caption
async def send_waifu_preview(client, chat_id, waifu_row, caption, reply_markup=None):
    # pick media (prefer media_file_id then media_file)
    media_file_id = waifu_row[7] if len(waifu_row) > 7 else None
    media_file = waifu_row[6] if len(waifu_row) > 6 else None
    media_type = waifu_row[5] if len(waifu_row) > 5 else None
    media = media_file_id or media_file

    try:
        if media_type == "video":
            if media:
                await client.send_video(chat_id, media, caption=caption, reply_markup=reply_markup)
            else:
                await client.send_message(chat_id, caption, reply_markup=reply_markup)
        else:
            # default photo
            if media:
                await client.send_photo(chat_id, media, caption=caption, reply_markup=reply_markup)
            else:
                await client.send_message(chat_id, caption, reply_markup=reply_markup)
    except Exception:
        # fallback: send text only
        await client.send_message(chat_id, caption, reply_markup=reply_markup)


# --- Commands / Handlers ---

@app.on_message(filters.command("affection"))
async def affection_handler(client, message):
    """
    Usage:
    /affection [waifu_id]  -> opens affection panel for waifu_id or user's favorite waifu
    """
    user_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=1)
    ensure_affection_table()  # just to be safe

    # Determine waifu_id: either provided or user's favorite
    waifu_id = None
    if len(parts) > 1 and parts[1].strip().isdigit():
        waifu_id = int(parts[1].strip())
    else:
        # try fetch from user_fav
        db.cursor.execute("SELECT waifu_id FROM user_fav WHERE user_id = ?", (user_id,))
        fav = db.cursor.fetchone()
        if fav and fav[0]:
            waifu_id = fav[0]

    if not waifu_id:
        return await message.reply_text("❌ No waifu specified and no favorite set. Use `/affection <waifu_id>` or set a favorite first.")

    # fetch waifu data
    db.cursor.execute("""
        SELECT id, name, anime, rarity, event, media_type, media_file, media_file_id
        FROM waifu_cards
        WHERE id = ?
    """, (waifu_id,))
    waifu = db.cursor.fetchone()
    if not waifu:
        return await message.reply_text("❌ Waifu not found with that ID.")

    # ensure user exists and affection record
    db.add_user(user_id, message.from_user.username if message.from_user.username else None)
    affection = get_affection_record(user_id, waifu_id)

    caption = build_affection_caption(waifu, affection)

    # buttons -- Add Energy, Increase Bond (if enough), Close
    buttons = []

    # Add energy button (it will try to add ADD_ENERGY_AMOUNT but limited by daily cap)
    buttons.append(InlineKeyboardButton(f"➕ Add {ADD_ENERGY_AMOUNT} Energy", callback_data=f"aff_add:{waifu_id}"))

    # Increase Bond button shown only when enough energy and not on cooldown and level < MAX
    can_upgrade = False
    if affection["bond_level"] < MAX_BOND_LEVEL and affection["energy_accum"] >= ENERGY_PER_UPGRADE:
        # check cooldown
        last_up_dt = parse_iso(affection["last_upgrade_iso"])
        if not last_up_dt or datetime.now() >= last_up_dt + timedelta(hours=24):
            can_upgrade = True

    if can_upgrade:
        buttons.append(InlineKeyboardButton("💗 Increase Bond", callback_data=f"aff_upgrade:{waifu_id}"))
    else:
        # show disabled label (non-interactive style by callback to 'aff_disabled')
        buttons.append(InlineKeyboardButton("💗 Increase Bond", callback_data=f"aff_disabled"))

    buttons.append(InlineKeyboardButton("❌ Close", callback_data="aff_close"))

    kb = InlineKeyboardMarkup([buttons])
    await send_waifu_preview(client, message.chat.id, waifu, caption, reply_markup=kb)


# Callback: Add energy
@app.on_callback_query(filters.regex(r"^aff_add:"))
async def aff_add_cb(client, callback_query):
    data = callback_query.data.split(":")
    try:
        waifu_id = int(data[1])
    except Exception:
        await callback_query.answer("Invalid data.", show_alert=True)
        return

    user_id = callback_query.from_user.id
    affection = get_affection_record(user_id, waifu_id)

    # Reset daily_added if day changed
    today_iso = date.today().isoformat()
    if affection["daily_reset_date"] != today_iso:
        affection["daily_added"] = 0
        affection["daily_reset_date"] = today_iso

    remaining_cap = DAILY_ENERGY_CAP - (affection["daily_added"] or 0)
    if remaining_cap <= 0:
        await callback_query.answer(f"Daily add limit reached ({DAILY_ENERGY_CAP}). Try tomorrow.", show_alert=True)
        return

    add_amount = min(ADD_ENERGY_AMOUNT, remaining_cap)
    new_energy = (affection["energy_accum"] or 0) + add_amount
    new_daily = (affection["daily_added"] or 0) + add_amount

    update_affection_record(user_id, waifu_id, energy_accum=new_energy, daily_added=new_daily, daily_reset_date=today_iso)

    # refresh affection dict
    affection = get_affection_record(user_id, waifu_id)

    # fetch waifu to rebuild caption
    db.cursor.execute("SELECT id, name, anime, rarity, event, media_type, media_file, media_file_id FROM waifu_cards WHERE id = ?", (waifu_id,))
    waifu = db.cursor.fetchone()
    caption = build_affection_caption(waifu, affection)

    # Edit message (replace with updated preview)
    try:
        await callback_query.message.edit_caption(caption)
    except Exception:
        # maybe original was a text message or media type different; just edit text
        try:
            await callback_query.message.edit_text(caption)
        except Exception:
            pass

    await callback_query.answer(f"+{add_amount} energy added (daily {new_daily}/{DAILY_ENERGY_CAP}).")


# Callback: Increase bond
@app.on_callback_query(filters.regex(r"^aff_upgrade:"))
async def aff_upgrade_cb(client, callback_query):
    data = callback_query.data.split(":")
    try:
        waifu_id = int(data[1])
    except Exception:
        await callback_query.answer("Invalid data.", show_alert=True)
        return

    user_id = callback_query.from_user.id
    affection = get_affection_record(user_id, waifu_id)

    # Check max level
    if affection["bond_level"] >= MAX_BOND_LEVEL:
        await callback_query.answer("Bond level already at maximum.", show_alert=True)
        return

    # Check energy
    if (affection["energy_accum"] or 0) < ENERGY_PER_UPGRADE:
        await callback_query.answer(f"Not enough energy. Need {ENERGY_PER_UPGRADE} energy to upgrade.", show_alert=True)
        return

    # Check cooldown
    last_up = parse_iso(affection["last_upgrade_iso"])
    if last_up and datetime.now() < last_up + timedelta(hours=24):
        await callback_query.answer("Upgrade is on cooldown. Try later.", show_alert=True)
        return

    # Perform upgrade: reduce energy by ENERGY_PER_UPGRADE, increase bond_level, set last_upgrade_iso
    new_energy = (affection["energy_accum"] or 0) - ENERGY_PER_UPGRADE
    new_level = min(MAX_BOND_LEVEL, (affection["bond_level"] or 1) + 1)
    now_iso = datetime.now().isoformat()

    update_affection_record(user_id, waifu_id, energy_accum=new_energy, bond_level=new_level, last_upgrade_iso=now_iso)

    # log event (optional)
    db.log_event("affection_upgrade", user_id=user_id, details=f"waifu_id={waifu_id} new_level={new_level}")

    # fetch waifu for caption update
    db.cursor.execute("SELECT id, name, anime, rarity, event, media_type, media_file, media_file_id FROM waifu_cards WHERE id = ?", (waifu_id,))
    waifu = db.cursor.fetchone()
    affection = get_affection_record(user_id, waifu_id)
    caption = build_affection_caption(waifu, affection)

    try:
        await callback_query.message.edit_caption(caption)
    except Exception:
        try:
            await callback_query.message.edit_text(caption)
        except Exception:
            pass

    await callback_query.answer(f"💗 Bond increased to {new_level}! (−{ENERGY_PER_UPGRADE} energy)")


# Callback: disabled or close
@app.on_callback_query(filters.regex(r"^aff_disabled"))
async def aff_disabled_cb(client, callback_query):
    await callback_query.answer("You cannot upgrade yet. Make sure you have enough energy and cooldown expired.", show_alert=True)


@app.on_callback_query(filters.regex(r"^aff_close"))
async def aff_close_cb(client, callback_query):
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await callback_query.answer()
