# handlers/claim.py

import sqlite3
import random
import time
import asyncio
from pyrogram import filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import app

# ---------------- Connect to DB ----------------
db = sqlite3.connect("waifu_bot.db", check_same_thread=False)
cursor = db.cursor()

# ---------------- Ensure Tables Exist ----------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_claims (
    user_id INTEGER PRIMARY KEY,
    last_claim INTEGER DEFAULT 0
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_waifus (
    user_id INTEGER,
    waifu_id INTEGER,
    amount INTEGER DEFAULT 1,
    PRIMARY KEY (user_id, waifu_id)
)
""")
db.commit()

# Settings
SUPPORT_USERNAME = "suppofcollectyourcrickers"
UPDATE_CHANNEL_USERNAME = "CricketCollecterBot"
SUPPORT_LINK = "https://t.me/suppofcollectyourcrickers"
UPDATE_LINK = "https://t.me/CricketCollecterBot"

# Reaction Emojis
REACTION_EMOJIS = ["🏏", "⚡", "🔥"]

# Cooldown (24 Hours)
COOLDOWN = 86400

async def is_member_of(client, chat_username: str, user_id: int) -> bool:
    try:
        chat = "@" + chat_username if not chat_username.startswith("@") else chat_username
        member = await client.get_chat_member(chat, user_id)
        status = getattr(member, "status", "")
        if status in ("left", "kicked"):
            return False
        return True
    except Exception:
        return False

def get_remaining_cooldown(user_id: int) -> int:
    cursor.execute("SELECT last_claim FROM user_claims WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    current_time = int(time.time())
    if row:
        last_claim = row[0]
        if current_time - last_claim < COOLDOWN:
            return COOLDOWN - (current_time - last_claim)
    return 0

async def give_reward(client, chat_id: int, user_id: int, username: str, reply_to_message_id: int = None):
    # Check cooldown
    remaining = get_remaining_cooldown(user_id)
    if remaining > 0:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return False, f"⏳ You already claimed a player! Come back in {hours}h {minutes}m."

    # Fetch random card
    cursor.execute("SELECT id, name, anime, rarity, event, media_type, media_file FROM waifu_cards")
    waifus = cursor.fetchall()
    if not waifus:
        return False, "❌ No players available in database yet."

    waifu = random.choice(waifus)
    waifu_id, name, anime, rarity, event, media_type, media_file = waifu

    # --- [FIX START] SAVE TO INVENTORY ---
    try:
        cursor.execute("SELECT amount FROM user_waifus WHERE user_id=? AND waifu_id=?", (user_id, waifu_id))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE user_waifus SET amount = amount + 1 WHERE user_id=? AND waifu_id=?", (user_id, waifu_id))
        else:
            cursor.execute("INSERT INTO user_waifus (user_id, waifu_id, amount) VALUES (?, ?, 1)", (user_id, waifu_id))
        
        # Update Cooldown
        current_time = int(time.time())
        cursor.execute("INSERT OR REPLACE INTO user_claims (user_id, last_claim) VALUES (?, ?)", (user_id, current_time))
        db.commit()
    except Exception as e:
        print(f"Database Error in Claim: {e}")
        return False, "❌ Error saving to database."
    # --- [FIX END] ---

    # Send Reactions (Visuals)
    if reply_to_message_id is not None:
        try:
            await client.send_reaction(chat_id=chat_id, message_id=reply_to_message_id, emoji=REACTION_EMOJIS[0])
        except:
            pass

    # Build Caption
    profile_text = (
        f"🏏 **Player Unlocked!** 🏏\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 **ID:** {waifu_id}\n"
        f"👤 **Name:** {name}\n"
        f"🏟️ **Team:** {anime}\n"
        f"💎 **Rarity:** {rarity}\n"
        f"🎀 **Event:** {event}\n"
        f"🔥 **Claimed by:** {username}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Check /inventory to see your collection!"
    )

    # Send Media
    try:
        if media_type == "photo":
            if reply_to_message_id:
                await client.send_photo(chat_id=chat_id, photo=media_file, caption=profile_text, reply_to_message_id=reply_to_message_id)
            else:
                await client.send_photo(chat_id=chat_id, photo=media_file, caption=profile_text)
        else:
            if reply_to_message_id:
                await client.send_video(chat_id=chat_id, video=media_file, caption=profile_text, reply_to_message_id=reply_to_message_id)
            else:
                await client.send_video(chat_id=chat_id, video=media_file, caption=profile_text)
    except Exception as e:
        print(f"Media Error: {e}")
        try:
            await client.send_message(chat_id=chat_id, text=profile_text)
        except:
            pass

    return True, None

# ---------------- /claim Command ----------------
@app.on_message(filters.command("claim"))
async def claim_waifu(client, message: Message):
    user_id = message.from_user.id
    username = message.from_user.first_name

    # Check cooldown
    remaining = get_remaining_cooldown(user_id)
    if remaining > 0:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await message.reply_text(f"⏳ You already claimed! Come back in {hours}h {minutes}m.")
        return

    # Check membership
    joined_support = await is_member_of(client, SUPPORT_USERNAME, user_id)
    joined_update = await is_member_of(client, UPDATE_CHANNEL_USERNAME, user_id)

    if joined_support and joined_update:
        success, info = await give_reward(client, message.chat.id, user_id, username, reply_to_message_id=message.id)
        if not success:
            await message.reply_text(info)
        return

    # Not joined buttons
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Join Support Group", url=SUPPORT_LINK)],
        [InlineKeyboardButton("📢 Join Update Channel", url=UPDATE_LINK)],
        [InlineKeyboardButton("✅ I've joined", callback_data=f"claim_joined:{user_id}")]
    ])

    await message.reply_text(
        "🔒 **Verification Required!**\n\n"
        "You must join our channels to claim daily players.",
        reply_markup=buttons
    )

# ---------------- Callback ----------------
@app.on_callback_query(filters.regex(r"^claim_joined:(\d+)$"))
async def claim_joined_cb(client, callback: CallbackQuery):
    try:
        expected_user_id = int(callback.data.split(":")[1])
        if callback.from_user.id != expected_user_id:
            await callback.answer("This button is not for you.", show_alert=True)
            return

        # Check membership again
        joined_support = await is_member_of(client, SUPPORT_USERNAME, expected_user_id)
        joined_update = await is_member_of(client, UPDATE_CHANNEL_USERNAME, expected_user_id)

        if not (joined_support and joined_update):
            await callback.answer("❌ You haven't joined both channels yet!", show_alert=True)
            return

        # Give reward
        success, info = await give_reward(client, callback.message.chat.id, expected_user_id, callback.from_user.first_name)
        if success:
            await callback.message.delete()
        else:
            await callback.answer(info, show_alert=True)

    except Exception as e:
        print(e)