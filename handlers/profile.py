# handlers/profile.py

import os
from pyrogram import filters
from pyrogram.types import Message
from pyrogram.errors import RPCError
from config import Config, app
from database import Database

db = Database("waifu_bot.db")  # <- make sure it reads the correct DB

# ---------------- Updated Rarities ----------------
RARITIES = [
    "Common", "Medium", "Rare", "Lagendary", "Limited edition",
    "Prime", "Cosmic", "Ultimate", "God"
]

RARITY_EMOJIS = [
    "😶","💨","🌹","💫","🔥","🔮","⚜️","🧚","🦋","🧊",
    "⚡"
]

# ---------------- Helper: Download profile photo ----------------
async def get_user_profile_photo(client, user_id: int):
    """Return a downloaded photo file path or None if no photo"""
    try:
        async for photo in client.get_chat_photos(user_id, limit=1):
            file_path = await client.download_media(photo.file_id)
            return file_path
    except RPCError:
        return None
    return None

# ---------------- /profile Command ----------------
@app.on_message(filters.command("profile"))
async def profile_cmd(client, message: Message):
    user = message.from_user
    user_id = user.id
    first_name = user.first_name or "Unknown"

    # ---------------- Fetch user profile ----------------
    profile_data = db.cursor.execute(
        "SELECT level, rank, badge, total_collected, progress, balance FROM user_profiles WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if profile_data:
        level, rank, badge, total_collected, progress, balance = profile_data
    else:
        level, rank, badge, total_collected, progress, balance = 1, "Newbie", "None", 0, 0, 0

    # ---------------- Calculate rarity breakdown ----------------
    rarities_count = {}
    for rarity in RARITIES:
        count = db.cursor.execute(
            """
            SELECT SUM(uw.amount)
            FROM user_waifus uw
            JOIN waifu_cards wc ON uw.waifu_id = wc.id
            WHERE uw.user_id = ? AND wc.rarity = ?
            """,
            (user_id, rarity)
        ).fetchone()[0]
        rarities_count[rarity] = count or 0

    # ---------------- Progress bar ----------------
    progress_bar_length = 10
    filled = int(progress / 10)
    empty = progress_bar_length - filled
    progress_bar = "⬛️" * filled + "⬜️" * empty

    # ---------------- Build profile text ----------------
    profile_text = f"""
╔═══❀•°❀°•❀═══╗
   🎀 Waifu Profile 🎀
╚═══❀•°❀°•❀═══╝

👤 {first_name}
🆔 ID: {user_id}
🎖 Level: {level}
🥈 Rank: {rank}
🏅 Badge: {badge}

🌸 Collection Stats 🌸
✨ Total Collected: {total_collected}
💎 Crystal Balance: {balance}
🌪 Progress: {progress}%

📈 Progress Bar
{progress_bar}

🌸 Rarities Owned 🌸
"""
    for rar, emoji in zip(RARITIES, RARITY_EMOJIS):
        profile_text += f"{emoji} {rar} → {rarities_count[rar]}\n"

    # ---------------- Global Rank (optional) ----------------
    global_rank = db.cursor.execute(
        "SELECT COUNT(*)+1 FROM user_profiles WHERE total_collected > ?",
        (total_collected,)
    ).fetchone()[0]
    profile_text += f"""
╔═══❀•°❀°•❀═══╗
🌍 Global Position → {global_rank}
╚═══❀•°❀°•❀═══╝

✨ “Hehe~ keep collecting waifus darling,
Alisa is watching you grow~ 💕”
"""

    # ---------------- Get Telegram profile photo ----------------
    photo_path = await get_user_profile_photo(client, user_id)

    # ---------------- Send profile ----------------
    if photo_path:
        await message.reply_photo(photo=photo_path, caption=profile_text)
        try:
            os.remove(photo_path)
        except Exception:
            pass
    else:
        await message.reply_text(profile_text)
