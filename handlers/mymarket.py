# mymarket.py
import random
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import Database
from config import app  # your pyrogram client instance

# ---------------- CONFIG ----------------
db = Database()

DEFAULT_PHOTO = "photo_2025-08-29_13-53-48.jpg"  # fallback image (keep this file in your bot folder)
STORE_SIZE = 10
STORE_REFRESH_COOLDOWN = timedelta(hours=24)
CURRENCY_SYMBOL = "💎"

RARITY_EMOJIS = {
    "Common": "😶",
    "Medium": "💨",
    "Rare": "🌹",
    "Legendary": "💫",
    "Limited edition": "🔥",
    "Prime": "🔮",
    "Cosmic": "⚜️",
    "Ultimate": "🧚",
    "God": "🦋",
}

BASE_PRICE = 150_000
PRICE_MULTIPLIER = {
    "Common": 1,
    "Medium": 1.5,
    "Rare": 2,
    "Legendary": 2.5,
    "Limited Edition": 3,
    "Prime": 3.5,
    "Cosmic": 4,
    "Ultimate": 4.5,
    "God": 5,
}

# in-memory pending buy map: user_id -> True (next numeric message is treated as ID)
pending_buy = {}


# ---------- Helpers ----------
def price_for_rarity(rarity: str) -> int:
    return int(BASE_PRICE * PRICE_MULTIPLIER.get(rarity, 1))


def rarity_emoji(rarity: str) -> str:
    return RARITY_EMOJIS.get(rarity, "❓")


def get_user_balance(user_id: int) -> int:
    """
    Try to get balance via db.get_crystals (if present),
    otherwise fallback to reading user_profiles.balance.
    Returns integer (0 if not found).
    """
    # Prefer db.get_crystals if available
    try:
        maybe = db.get_crystals(user_id)
        if maybe:
            # many existing bots return a tuple like (daily, weekly, monthly, total, last_claim, given)
            # but if format differs, try best-effort.
            if isinstance(maybe, (list, tuple)) and len(maybe) >= 4:
                return int(maybe[3] or 0)
    except Exception:
        pass

    # Fallback raw SQL to user_profiles.balance
    try:
        cur = db.cursor
        cur.execute("SELECT balance FROM user_profiles WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            return int(row[0] or 0)
    except Exception:
        pass

    return 0


def pick_store_items(limit: int = STORE_SIZE):
    """
    Pull random rows from waifu_cards and return list of:
    (id, name, rarity, price, media_type, media_file_id, media_file)
    """
    cur = db.cursor
    all_rows = cur.execute(
        "SELECT id, name, rarity, media_type, media_file_id, media_file FROM waifu_cards"
    ).fetchall()
    if not all_rows:
        return []
    sample = random.sample(all_rows, min(len(all_rows), limit))
    items = []
    for row in sample:
        wid, name, rarity, media_type, media_file_id, media_file = row
        price = price_for_rarity(rarity)
        items.append((wid, name, rarity, price, (media_type or "").lower(), media_file_id, media_file))
    return items


def build_store_caption(items) -> str:
    """
    Format store exactly as requested.
    """
    header = "This Is Your Today's Store:\n\n"
    lines = [header]
    for wid, name, rarity, price, is_video_type, media_file_id, media_file in items:
        emoji = rarity_emoji(rarity)
        lines.append(f"{emoji} {wid} {name}")
        lines.append(f"Rarity: {rarity} | Price: {price}{CURRENCY_SYMBOL}\n")
    return "\n".join(lines)


# ---------- /mymarket command ----------
@app.on_message(filters.command("mymarket"))
async def cmd_mymarket(client, message):
    user_id = message.from_user.id

    # cooldown check (per-user store refresh)
    can_refresh = True
    try:
        last_refresh = db.get_last_claim(user_id, "store_refresh")
        if last_refresh:
            last_time = datetime.fromisoformat(last_refresh)
            if datetime.utcnow() - last_time < STORE_REFRESH_COOLDOWN:
                can_refresh = False
    except Exception:
        # if any parsing error, allow refresh
        can_refresh = True

    items = pick_store_items(STORE_SIZE)
    if not items:
        await message.reply_text("🛒 The store is currently empty.")
        return

    caption = build_store_caption(items)

    # buttons: buy-by-id, refresh, help
    kb = [
        [InlineKeyboardButton("🛒 Buy by ID", callback_data="market_buy_by_id")],
        [InlineKeyboardButton("🔄 Refresh Store" if can_refresh else "🔒 Refresh (24h locked)", callback_data="market_refresh")],
        [InlineKeyboardButton("❓ How to buy", callback_data="market_help")],
    ]

    # send as photo with caption (no parse_mode), fallback if photo sending raises
    try:
        await message.reply_photo(photo=DEFAULT_PHOTO, caption=caption, reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        # fallback to simple text reply
        await message.reply_text(caption, reply_markup=InlineKeyboardMarkup(kb))


# ---------- refresh callback ----------
@app.on_callback_query(filters.regex(r"^market_refresh$"))
async def cb_refresh_store(client, callback_query):
    user_id = callback_query.from_user.id
    try:
        last_refresh = db.get_last_claim(user_id, "store_refresh")
        if last_refresh:
            last_time = datetime.fromisoformat(last_refresh)
            if datetime.utcnow() - last_time < STORE_REFRESH_COOLDOWN:
                await callback_query.answer("❌ You can refresh the store only once every 24 hours.", show_alert=True)
                return
    except Exception:
        pass

    # update last refresh
    db.update_last_claim(user_id, "store_refresh", datetime.utcnow().isoformat())

    # remove old message and send new store
    try:
        await callback_query.message.delete()
    except Exception:
        pass

    # Re-run command to display new list
    await cmd_mymarket(client, callback_query.message)
    await callback_query.answer("✅ Store refreshed!")


# ---------- market help ----------
@app.on_callback_query(filters.regex(r"^market_help$"))
async def cb_market_help(client, callback_query):
    help_text = (
        "🛒 Buy Character from Store\n\n"
        "Please enter the ID of the character you want to buy.\n"
        "Example: send `123` (the waifu id shown in the store)\n\n"
        "Or use command: /buy <id>\n"
    )
    # plain text message (no parse_mode)
    await callback_query.message.reply_text(help_text)
    await callback_query.answer()


# ---------- buy by id prompt ----------
@app.on_callback_query(filters.regex(r"^market_buy_by_id$"))
async def cb_buy_by_id(client, callback_query):
    user_id = callback_query.from_user.id
    pending_buy[user_id] = True
    await callback_query.message.reply_text("🛒 Please send the numeric ID of the character you want to buy (Example: 123).")
    await callback_query.answer("Send the waifu ID as a message.")


# ---------- catch numeric message when pending buy ----------
@app.on_message(filters.regex(r"^\d{1,10}$"))
async def on_numeric_id(client, message):
    user_id = message.from_user.id
    if not pending_buy.pop(user_id, False):
        return  # not in buy flow

    waifu_id = int(message.text.strip())
    await show_preview_for_id(message, waifu_id)


# ---------- /buy command ----------
@app.on_message(filters.command("buy"))
async def cmd_buy(client, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /buy <waifu_id>\nExample: /buy 123")
        return
    try:
        waifu_id = int(message.command[1])
    except Exception:
        await message.reply_text("Please provide a numeric ID. Example: /buy 123")
        return
    await show_preview_for_id(message, waifu_id)


# ---------- Preview helper ----------
async def show_preview_for_id(message, waifu_id: int):
    user = message.from_user
    user_id = user.id

    # get user balance
    balance = get_user_balance(user_id)

    # fetch waifu
    cur = db.cursor
    waifu = cur.execute(
        "SELECT id, name, anime, rarity, media_type, media_file_id, media_file FROM waifu_cards WHERE id=?",
        (waifu_id,)
    ).fetchone()
    if not waifu:
        await message.reply_text("❌ Waifu not found. Check the ID and try again.")
        return

    _id, name, anime, rarity, media_type, media_file_id, media_file = waifu
    price = price_for_rarity(rarity)
    emoji = rarity_emoji(rarity)
    is_video = (media_type or "").lower() == "video"

    if balance < price:
        await message.reply_text(f"❌ You don't have enough balance to buy this waifu.\nPrice: {price}{CURRENCY_SYMBOL} | Your balance: {balance}{CURRENCY_SYMBOL}")
        return

    caption = (
        f"{emoji} Preview\n\n"
        f"ID: {_id}\n"
        f"Name: {name}\n"
        f"Anime: {anime}\n"
        f"Rarity: {rarity}\n"
        f"Price: {price}{CURRENCY_SYMBOL}\n\n"
        "Do you want to confirm the purchase?"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data=f"market_confirm_{_id}_{price}"),
         InlineKeyboardButton("❌ Decline", callback_data=f"market_decline_{_id}")],
    ])

    send_id = media_file_id or media_file or DEFAULT_PHOTO

    try:
        if is_video:
            # video path/file_id or fallback to image if sending fails
            await message.reply_video(video=send_id, caption=caption, reply_markup=kb)
        else:
            await message.reply_photo(photo=send_id, caption=caption, reply_markup=kb)
    except Exception:
        # fallback to default photo caption
        try:
            await message.reply_photo(photo=DEFAULT_PHOTO, caption=caption, reply_markup=kb)
        except Exception:
            await message.reply_text(caption, reply_markup=kb)


# ---------- Confirm / Decline callbacks ----------
@app.on_callback_query(filters.regex(r"^market_confirm_(\d+)_(\d+)$"))
async def cb_market_confirm(client, callback_query):
    user_id = callback_query.from_user.id
    parts = callback_query.data.split("_")
    waifu_id = int(parts[2])
    price = int(parts[3])

    balance = get_user_balance(user_id)
    if balance < price:
        await callback_query.answer("❌ Not enough balance.", show_alert=True)
        return

    # Prefer existing DB purchase function if it exists
    try:
        success = db.purchase_waifu(user_id, waifu_id, price)
    except Exception:
        # fallback manual: deduct from user_profiles.balance and insert into user_waifus
        success = False
        try:
            cur = db.cursor
            # deduct balance (if table user_profiles.balance exists)
            cur.execute("UPDATE user_profiles SET balance = balance - ? WHERE user_id = ?", (price, user_id))
            # add to user_waifus (same pattern used elsewhere in your code)
            cur.execute("""
                INSERT INTO user_waifus (user_id, waifu_id, amount, last_collected)
                VALUES (?, ?, 1, strftime('%s','now'))
                ON CONFLICT(user_id, waifu_id) DO UPDATE SET amount = amount + 1, last_collected = strftime('%s','now')
            """, (user_id, waifu_id))
            db.conn.commit()
            success = True
        except Exception:
            success = False

    if success:
        await callback_query.message.reply_text(f"✅ Purchase successful! You bought waifu ID {waifu_id} for {price}{CURRENCY_SYMBOL}")
        await callback_query.answer("✅ Purchased!", show_alert=True)
    else:
        await callback_query.message.reply_text("❌ Purchase failed. Please try again or contact the owner.")
        await callback_query.answer("❌ Purchase failed.", show_alert=True)


@app.on_callback_query(filters.regex(r"^market_decline_(\d+)$"))
async def cb_market_decline(client, callback_query):
    await callback_query.message.reply_text("❌ Purchase cancelled.")
    await callback_query.answer("Purchase cancelled.")

# End of file
