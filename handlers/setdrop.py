# handlers/setdrop.py

import sqlite3
from pyrogram import filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from config import Config, app
import random

DB_PATH = "waifu_bot.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Ensure current_drops table exists
cursor.execute("""
CREATE TABLE IF NOT EXISTS current_drops (
    chat_id INTEGER PRIMARY KEY,
    waifu_id INTEGER,
    collected_by INTEGER DEFAULT NULL
)
""")
conn.commit()

# In-memory drop counter
drop_settings = {}  # {chat_id: {"target": int, "count": int}}

# ---------------- ✅ Updated Allowed Rarities (Simple Names) ----------------
ALLOWED_KEYWORDS = [
    "Common", "Medium", "Rare", "Legendary", "Limited edition",
    "Prime", "Cosmic", "Ultimate", "God"
]

# ---------------- Blocked rarities (Optional: Empty rakh sakte hain) ----------------
BLOCKED_KEYWORDS = []

# Helper to build LIKE params
def like_params(keywords):
    return [f"%{k.strip()}%" for k in keywords]


# ---------------- /setdrop Command ----------------
@app.on_message(filters.command("setdrop") & filters.group, group=1)
async def set_drop(client, message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Validate input
    try:
        target_msg = int(message.text.split(" ", 1)[1])
    except (IndexError, ValueError):
        await message.reply_text("❌ Usage: /setdrop <number_of_messages>")
        return

    # -------- Proper Limits --------
    # Owner can set any limit (even 1 for testing)
    if user_id == Config.OWNER_ID:
        pass 
    elif user_id in Config.ADMINS:
        if target_msg < 20:
            await message.reply_text("⚠️ Admins cannot set drop below 20 messages.")
            return
    else:
        if target_msg < 60:
            await message.reply_text("⚠️ Normal users cannot set drop below 60 messages.")
            return

    # Set drop
    drop_settings[chat_id] = {"target": target_msg, "count": 0}
    await message.reply_text(f"✅ Card drop set! A random player will drop after every {target_msg} messages.")


# ---------------- /dropcount Command ----------------
@app.on_message(filters.command("dropcount") & filters.group, group=1)
async def drop_count(client, message: Message):
    chat_id = message.chat.id
    if chat_id not in drop_settings:
        await message.reply_text("ℹ️ No card drop is configured for this group. Use /setdrop to enable drops.")
        return

    remaining = drop_settings[chat_id]["target"] - drop_settings[chat_id]["count"]
    if remaining < 0:
        remaining = 0
    await message.reply_text(f"🎴 Messages remaining until next drop: {remaining}")


# ---------------- Message Tracker (Drop Logic) ----------------
@app.on_message(filters.group, group=2)
async def drop_tracker(client, message: Message):
    chat_id = message.chat.id

    # Ignore service messages
    if message.service:
        return

    # Ignore commands so /start and other commands don't count/trigger
    if message.text and message.text.startswith("/"):
        return

    if chat_id not in drop_settings:
        return

    drop_settings[chat_id]["count"] += 1
    
    # Check if target reached
    if drop_settings[chat_id]["count"] < drop_settings[chat_id]["target"]:
        return

    # Reset counter immediately
    drop_settings[chat_id]["count"] = 0

    # --- Logic to pick a card ---
    try:
        # Simply pick ANY random card from DB to ensure drops always work
        cursor.execute("SELECT id, name, anime, rarity, media_type, media_file FROM waifu_cards ORDER BY RANDOM() LIMIT 1")
        card = cursor.fetchone()

        if not card:
            # DB is empty
            return

    except Exception as e:
        print(f"❌ Error fetching card for drop: {e}")
        return

    # Save drop to DB so /collect works
    cursor.execute(
        "INSERT OR REPLACE INTO current_drops (chat_id, waifu_id, collected_by) VALUES (?, ?, NULL)",
        (chat_id, card[0])
    )
    conn.commit()

    # Prepare Deep Link Button (Optional, removed view details button to hide info further)
    # buttons = None (agar aapko deep link hatana hai toh is line ko uncomment kar dein)
    try:
        me = await client.get_me()
        bot_username = me.username
        # Hum button hata rahe hain taaki user wahan se bhi cheat na kar sake
        buttons = None 
    except:
        buttons = None

    # Send Drop Message
    # Unpack card details
    # card = (id, name, anime, rarity, media_type, media_file)
    # c_name = card[1]  <-- NAME HATA DIYA
    c_rarity = card[3]
    c_type = card[4]
    c_file = card[5]

    # ✅ NEW DROP TEXT (Hidden Name)
    drop_text = (
        f"🏏 **A Wild Player Appeared!** 🏏\n\n"
        f"👤 **Name:** ❓❓❓\n"
        f"💎 **Rarity:** {c_rarity}\n\n"
        f"👇 Type **/collect <name>** to collect this player!"
    )

    try:
        if c_type == "photo":
            await message.reply_photo(c_file, caption=drop_text, reply_markup=buttons)
        elif c_type == "video":
            await message.reply_video(c_file, caption=drop_text, reply_markup=buttons)
        else:
            await message.reply_text(drop_text, reply_markup=buttons)
    except Exception as e:
        print(f"❌ Failed to send drop message: {e}")

# ---------------- Private /start handler for Deep Links ----------------
@app.on_message(filters.private & filters.command("start"), group=3)
async def start_with_card(client, message: Message):
    if len(message.command) < 2:
        return
    payload = message.command[1]
    
    if payload.startswith("card_"):
        try:
            waifu_id = int(payload.split("_", 1)[1])
            cursor.execute(
                "SELECT id, name, anime, rarity, event, media_type, media_file FROM waifu_cards WHERE id = ?",
                (waifu_id,)
            )
            card = cursor.fetchone()
            if not card:
                await message.reply_text("❌ Card not found.")
                return

            caption = (
                f"🎴 **Player Details**\n\n"
                f"👤 Name: {card[1]}\n"
                f"🏟️ Team: {card[2]}\n"
                f"💎 Rarity: {card[3]}\n"
                f"🎀 Event: {card[4] or 'None'}\n"
                f"🆔 ID: {card[0]}"
            )
            
            if card[5] == "photo":
                await client.send_photo(message.chat.id, card[6], caption=caption)
            else:
                await client.send_video(message.chat.id, card[6], caption=caption)

        except Exception as e:
            print(f"Deep link error: {e}")