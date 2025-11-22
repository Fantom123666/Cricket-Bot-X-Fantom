# craft.py
import sqlite3, time, random
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import app, Config

DB_PATH = Config.DB_PATH
COOLDOWN = 24 * 60 * 60  # 24 hours
BONUS_CRYSTALS = 10000

# ✅ Only these rarities are allowed for craft drops
ALLOWED_RARITIES = [
    "Common", "Medium", "Rare", "Lagendary", "Limited edition",
    "Prime", "Cosmic", "Ultimate", "God",
]

# ---------- DB helpers ----------
def db():
    return sqlite3.connect(DB_PATH)

def ensure_user_rows(user_id: int, username: str, first_name: str):
    conn = db()
    cur = conn.cursor()
    # Minimal users row (other columns have defaults)
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
    """, (user_id, username or "", first_name or ""))

    # Profile row for balance
    cur.execute("""
        INSERT OR IGNORE INTO user_profiles (user_id)
        VALUES (?)
    """, (user_id,))

    # Cooldown table for craft
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_craft (
            user_id INTEGER PRIMARY KEY,
            last_claim INTEGER
        )
    """)
    conn.commit()
    conn.close()

def add_waifu_to_inventory(user_id: int, waifu_id: int):
    """Same inventory pattern as your reward.py (user_waifus)"""
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE user_waifus
               SET amount = amount + 1,
                   last_collected = strftime('%s','now')
             WHERE user_id = ? AND waifu_id = ?
        """, (user_id, waifu_id))
        if cur.rowcount == 0:
            cur.execute("""
                INSERT INTO user_waifus (user_id, waifu_id, amount, last_collected)
                VALUES (?, ?, 1, strftime('%s','now'))
            """, (user_id, waifu_id))
        conn.commit()
    finally:
        conn.close()

def add_crystals(user_id: int, amount: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE user_profiles SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def get_cooldown_remaining(user_id: int) -> int:
    """Return seconds remaining; 0 if ready."""
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT last_claim FROM user_craft WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    now = int(time.time())
    if not row or not row[0]:
        return 0
    elapsed = now - int(row[0])
    return max(0, COOLDOWN - elapsed)

def set_cooldown_now(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO user_craft (user_id, last_claim) VALUES (?, ?)", (user_id, int(time.time())))
    conn.commit()
    conn.close()

def pick_random_allowed_waifu():
    conn = db()
    cur = conn.cursor()
    placeholders = ",".join("?" * len(ALLOWED_RARITIES))
    cur.execute(f"""
        SELECT id, name, anime, rarity, media_type, media_file
          FROM waifu_cards
         WHERE rarity IN ({placeholders})
         ORDER BY RANDOM() LIMIT 1
    """, ALLOWED_RARITIES)
    row = cur.fetchone()
    conn.close()
    return row

# ---------- UI texts ----------
def craft_announcement_text(display_name: str):
    # Using the style you provided
    copy_this = f"{display_name} 愛"
    return (
        "🍁 ᴅᴀɪʟʏ ʀᴇᴇɴ ᴄʀᴀғᴛ ʀᴇᴡᴀʀᴅ 🍁\n\n"
        f"ʜᴇʏ {display_name} ʀᴇᴀᴅʏ ᴛᴏ ᴄʟᴀɪᴍ ʏᴏᴜʀ ғʀᴇᴇ ᴄʜᴀʀᴀᴄᴛᴇʀ ᴀɴᴅ 10000 ᴛᴏᴋᴇɴs?\n\n"
        "➤ ᴛᴏ ʙᴇ ᴇʟɪɢɪʙʟᴇ, ʏᴏᴜ ᴍᴜsᴛ ᴀᴅᴅ あ / 愛 ᴀᴛ ᴛʜᴇ ᴇɴᴅ ᴏғ ʏᴏᴜʀ ɴᴀᴍᴇ.\n"
        "➤ ᴜsᴇ ᴛʜᴇ Change Name ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴇᴅɪᴛ ʏᴏᴜʀ ɴᴀᴍᴇ.\n\n"
        "🔗 𝐂𝐨𝐩𝐲 𝐓𝐡𝐢𝐬:\n"
        f"{copy_this}\n\n"
        "⏳ ᴏɴᴄᴇ ᴅᴏɴᴇ, ᴄʟɪᴄᴋ ᴄʟᴀɪᴍ ʀᴇᴡᴀʀᴅ ᴛᴏ ᴜɴʟᴏᴄᴋ ʏᴏᴜʀ ɢɪғᴛ!\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✨ *ʀᴇᴇɴ ᴡᴀʀʀɪᴏʀs ɴᴇᴠᴇʀ sᴛᴏᴘ!* ✨"
    )

def success_caption(waifu_name: str, anime: str, rarity: str, user_display: str):
    return (
        "🎉 ᴅᴀɪʟʏ ᴄʟᴀɪᴍ sᴜᴄᴄᴇssғᴜʟ! 🎉\n\n"
        f"🏷️ Name: {waifu_name}\n"
        f"🧬 Anime: {anime}\n"
        f"✨ Rarity: {rarity}\n"
        f"🎈 Bonus Crystal: {BONUS_CRYSTALS}\n\n"
        f"⚔️ ᴋᴇᴇᴘ ғɪɢʜᴛɪɴɢ, {user_display}"
    )

def need_logo_text(display_name: str):
    return (
        "❌ You need to add **愛** to your Telegram name to claim this reward.\n\n"
        "➤ Open settings with the button below, add the logo, then press **Claim Reward** again."
    )

# ---------- Handlers ----------
@app.on_message(filters.command("craft"))
async def craft_command(client, message):
    user = message.from_user
    user_id = user.id
    username = (user.username or "")
    first_name = (user.first_name or "")
    last_name = (user.last_name or "")
    display_name = (first_name + (" " + last_name if last_name else "")).strip() or username or "Traveler"

    # Ensure rows and tables exist
    ensure_user_rows(user_id, username, first_name)

    text = craft_announcement_text(display_name)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Change Name", url="tg://settings")],
        [InlineKeyboardButton("🎁 Claim Reward", callback_data="claim_craft")]
    ])
    await message.reply(text, reply_markup=kb, disable_web_page_preview=True)

@app.on_callback_query(filters.regex("^claim_craft$"))
async def claim_craft_cb(client, callback_query):
    user = callback_query.from_user
    user_id = user.id
    username = (user.username or "")
    first_name = (user.first_name or "")
    last_name = (user.last_name or "")
    full_name = (first_name + (" " + last_name if last_name else "")).strip()

    # Must have 愛 in profile name
    if "愛" not in full_name:
        await callback_query.answer("Add 愛 to your name first!", show_alert=True)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Change Name", url="tg://settings")],
            [InlineKeyboardButton("🎁 Claim Reward", callback_data="claim_craft")]
        ])
        await callback_query.message.reply(need_logo_text(full_name or username or "Traveler"), reply_markup=kb)
        return

    # Ensure DB rows exist
    ensure_user_rows(user_id, username, first_name)

    # Cooldown check
    remaining = get_cooldown_remaining(user_id)
    if remaining > 0:
        hrs = remaining // 3600
        mins = (remaining % 3600) // 60
        secs = remaining % 60
        await callback_query.answer(f"Cooldown: {hrs}h {mins}m {secs}s left.", show_alert=True)
        return

    # Pick a waifu (only allowed rarities)
    row = pick_random_allowed_waifu()
    if not row:
        await callback_query.answer("No eligible waifus in DB.", show_alert=True)
        await callback_query.message.reply("⚠️ No eligible waifu cards available for craft right now.")
        return

    waifu_id, name, anime, rarity, media_type, media_file = row

    # Award: inventory + crystals, then set cooldown
    add_waifu_to_inventory(user_id, waifu_id)
    add_crystals(user_id, BONUS_CRYSTALS)
    set_cooldown_now(user_id)

    caption = success_caption(name, anime, rarity, full_name)

    # Send media preview with caption
    try:
        if (media_type or "").lower() == "video":
            await callback_query.message.reply_video(media_file, caption=caption)
        else:
            await callback_query.message.reply_photo(media_file, caption=caption)
    except Exception:
        # If media fails, at least send the text
        await callback_query.message.reply(caption)

    await callback_query.answer("Reward claimed! 🎁")
