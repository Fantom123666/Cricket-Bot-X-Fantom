# handlers/inventory.py
from pyrogram import filters
from pyrogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery, 
    InputMediaPhoto, 
    InputMediaVideo
)
from config import app
from database import Database
import urllib.parse

db = Database()

# ✅ Rarity Mappings
RARITY_EMOJIS = {
    "Common": "😶",
    "Medium": "💨",
    "Rare": "🌹",
    "Legendary": "💫",
    "Limited edition": "🔥",
    "Prime": "🔮",
    "Cosmic": "⚜️",
    "Ultimate": "🧚",
    "God": "🦋"
}

RARITY_ORDER = [
    "Common", "Medium", "Rare", "Legendary", "Limited edition",
    "Prime", "Cosmic", "Ultimate", "God"
]

# ---------------- Helpers ----------------
def encode_cb(s: str) -> str:
    return urllib.parse.quote_plus(s)

def decode_cb(s: str) -> str:
    return urllib.parse.unquote_plus(s)

def get_user_settings(user_id: int):
    try:
        cur = db.cursor
        cur.execute("SELECT rarity_filter, anime_filter FROM user_settings WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            return {"rarity": row[0], "anime": row[1]}
    except:
        pass
    return {"rarity": None, "anime": None}

def set_user_settings(user_id: int, rarity=None, anime=None):
    try:
        db.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                rarity_filter TEXT DEFAULT NULL,
                anime_filter TEXT DEFAULT NULL
            )
        """)
        db.conn.commit()
    except:
        pass
    db.cursor.execute(
        "INSERT OR REPLACE INTO user_settings (user_id, rarity_filter, anime_filter) VALUES (?, ?, ?)",
        (user_id, rarity, anime),
    )
    db.conn.commit()

# ---------------- /inventory Command ----------------
@app.on_message(filters.command("inventory"))
async def inventory_cmd(client, message):
    user_id = message.from_user.id
    
    # Check if user has a favorite set
    db.cursor.execute("SELECT waifu_id FROM user_fav WHERE user_id = ?", (user_id,))
    fav_row = db.cursor.fetchone()

    # Agar fav hai toh pehle Fav dikhao ('fav' mode), nahi toh normal inventory ('collection', page 0)
    if fav_row:
        await show_inventory_card(client, message.chat.id, user_id, mode="fav", page=0, is_new_message=True)
    else:
        await show_inventory_card(client, message.chat.id, user_id, mode="collection", page=0, is_new_message=True)

# ---------------- Main Logic to Show Card ----------------
async def show_inventory_card(client, chat_id, user_id, mode="collection", page=0, is_new_message=False, original_message=None):
    
    # --- MODE: FAVORITE ---
    if mode == "fav":
        # Fetch Favorite Details
        query = """
            SELECT wc.id, wc.name, wc.anime, wc.rarity, wc.event, wc.media_type, wc.media_file, uw.amount
            FROM user_fav uf
            JOIN waifu_cards wc ON uf.waifu_id = wc.id
            JOIN user_waifus uw ON (uw.waifu_id = wc.id AND uw.user_id = uf.user_id)
            WHERE uf.user_id = ?
        """
        db.cursor.execute(query, (user_id,))
        card = db.cursor.fetchone()

        if not card:
            # Agar fav set hai par card collection se delete ho gaya, toh normal inventory dikhao
            return await show_inventory_card(client, chat_id, user_id, "collection", 0, is_new_message, original_message)

        c_id, c_name, c_anime, c_rarity, c_event, c_type, c_file, c_amount = card
        
        c_emoji = RARITY_EMOJIS.get(c_rarity, "⚪")
        c_event = f"🎀 **Theme:** {c_event}\n" if c_event else ""
        
        caption = (
            f"👑 **YOUR FAVORITE PLAYER** 👑\n"
            f"──────────────────\n"
            f"{c_emoji} **{c_name}**\n"
            f"🏟️ **Team:** {c_anime}\n"
            f"{c_event}"
            f"💎 **Rarity:** {c_rarity}\n"
            f"📦 **You Own:** {c_amount}x\n"
            f"──────────────────\n"
            f"🆔 ID: `{c_id}`"
        )

        # Button to enter main collection
        buttons = [[InlineKeyboardButton("📂 Open Full Collection ➡️", callback_data="inv_pg:0")]]
        markup = InlineKeyboardMarkup(buttons)

    # --- MODE: COLLECTION (Normal Inventory) ---
    else:
        # 1. Get Filters
        settings = get_user_settings(user_id)
        rarity_filter = settings.get("rarity")
        where_clauses = ["uw.user_id = ?"]
        params = [user_id]

        if rarity_filter:
            where_clauses.append("wc.rarity = ?")
            params.append(rarity_filter)

        where_sql = " AND ".join(where_clauses)

        # 2. Count Total
        count_query = f"SELECT COUNT(*) FROM user_waifus uw JOIN waifu_cards wc ON uw.waifu_id = wc.id WHERE {where_sql}"
        db.cursor.execute(count_query, tuple(params))
        total_cards = db.cursor.fetchone()[0] or 0

        if total_cards == 0:
            text = "🚫 **Inventory Empty!**\nCollect some players or check your filters."
            if is_new_message: await client.send_message(chat_id, text)
            elif original_message: await original_message.edit_text(text)
            return

        # Adjust page
        if page >= total_cards: page = 0
        if page < 0: page = total_cards - 1

        # 3. Fetch Card
        query = f"""
            SELECT wc.id, wc.name, wc.anime, wc.rarity, wc.event, wc.media_type, wc.media_file, uw.amount
            FROM user_waifus uw
            JOIN waifu_cards wc ON uw.waifu_id = wc.id
            WHERE {where_sql}
            ORDER BY wc.rarity DESC, wc.id ASC
            LIMIT 1 OFFSET ?
        """
        db.cursor.execute(query, tuple(params + [page]))
        card = db.cursor.fetchone()

        if not card: return

        c_id, c_name, c_anime, c_rarity, c_event, c_type, c_file, c_amount = card
        c_emoji = RARITY_EMOJIS.get(c_rarity, "⚪")
        c_event = f"🎀 **Theme:** {c_event}\n" if c_event else ""
        
        caption = (
            f"🎒 **Collection Gallery**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{c_emoji} **{c_name}**\n"
            f"🏟️ **Team:** {c_anime}\n"
            f"{c_event}"
            f"💎 **Rarity:** {c_rarity}\n"
            f"🆔 **ID:** {c_id}  |  📦 **Owned:** {c_amount}x\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📄 Card {page + 1} of {total_cards}"
        )

        # Navigation Buttons
        nav_row = [
            InlineKeyboardButton("⬅️", callback_data=f"inv_pg:{page-1}"),
            InlineKeyboardButton(f"{page+1}/{total_cards}", callback_data="ignore"),
            InlineKeyboardButton("➡️", callback_data=f"inv_pg:{page+1}")
        ]
        
        # Settings & Fav Button
        ctrl_row = [
            InlineKeyboardButton("⚙️ Filter", callback_data="wmode_menu"),
            InlineKeyboardButton("❌ Close", callback_data="inv_close")
        ]

        # Check if Fav exists to show "Back to Fav" button
        db.cursor.execute("SELECT waifu_id FROM user_fav WHERE user_id = ?", (user_id,))
        if db.cursor.fetchone():
            ctrl_row.insert(1, InlineKeyboardButton("👑 Fav", callback_data="inv_show_fav"))

        markup = InlineKeyboardMarkup([nav_row, ctrl_row])

    # --- SENDING MEDIA ---
    media_type = (c_type or "photo").lower()
    if not c_file: 
        c_file = "https://telegra.ph/file/fallback_image.jpg" # Change if needed
        media_type = "photo"

    try:
        if is_new_message:
            if media_type == "video":
                await client.send_video(chat_id, c_file, caption=caption, reply_markup=markup)
            else:
                await client.send_photo(chat_id, c_file, caption=caption, reply_markup=markup)
        elif original_message:
            media = InputMediaVideo(c_file, caption=caption) if media_type == "video" else InputMediaPhoto(c_file, caption=caption)
            await original_message.edit_media(media=media, reply_markup=markup)
    except Exception:
        # Fallback for edit errors (e.g. same media)
        try:
            if original_message: await original_message.edit_caption(caption=caption, reply_markup=markup)
        except: pass

# ---------------- Callbacks ----------------

@app.on_callback_query(filters.regex(r"^inv_pg:(-?\d+)"))
async def inv_paginate(client, callback):
    page = int(callback.matches[0].group(1))
    await show_inventory_card(client, callback.message.chat.id, callback.from_user.id, "collection", page, False, callback.message)

@app.on_callback_query(filters.regex(r"^inv_show_fav$"))
async def inv_fav_cb(client, callback):
    await show_inventory_card(client, callback.message.chat.id, callback.from_user.id, "fav", 0, False, callback.message)

@app.on_callback_query(filters.regex(r"^inv_close$"))
async def inv_close(client, callback):
    await callback.message.delete()

@app.on_callback_query(filters.regex(r"^ignore$"))
async def inv_ignore(client, callback):
    await callback.answer(f"Current Page: {callback.data}")

# ---------------- W-MODE (Filters) ----------------
@app.on_callback_query(filters.regex(r"^wmode_menu$"))
async def wmode_menu_cb(client, callback):
    kb = []
    row = []
    for r in RARITY_ORDER:
        row.append(InlineKeyboardButton(f"{RARITY_EMOJIS.get(r,'')} {r.split()[0]}", callback_data=f"wmode_set:{encode_cb(r)}"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row: kb.append(row)
    
    kb.append([InlineKeyboardButton("🗑 Clear Filter", callback_data="wmode_clear")])
    kb.append([InlineKeyboardButton("🔙 Back to Inventory", callback_data="inv_pg:0")])
    
    try:
        await callback.message.edit_caption(
            caption="⚙️ **Filter Settings**\nSelect a rarity to show only specific cards:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except:
        await callback.message.reply("⚙️ **Filter Settings**", reply_markup=InlineKeyboardMarkup(kb))

@app.on_callback_query(filters.regex(r"^wmode_set:(.+)"))
async def wmode_set(client, callback):
    rarity = decode_cb(callback.matches[0].group(1))
    set_user_settings(callback.from_user.id, rarity=rarity)
    await callback.answer(f"Filtered by: {rarity}")
    await show_inventory_card(client, callback.message.chat.id, callback.from_user.id, "collection", 0, False, callback.message)

@app.on_callback_query(filters.regex(r"^wmode_clear$"))
async def wmode_clear(client, callback):
    set_user_settings(callback.from_user.id, rarity=None)
    await callback.answer("Filters cleared")
    await show_inventory_card(client, callback.message.chat.id, callback.from_user.id, "collection", 0, False, callback.message)