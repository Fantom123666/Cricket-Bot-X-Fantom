from pyrogram import filters
from config import app, Config
import sqlite3, random, time

DB_PATH = Config.DB_PATH
COOLDOWN = 120  # 2 minutes in seconds

def add_waifu_to_inventory(user_id, waifu_id):
    conn = sqlite3.connect(DB_PATH)
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


def can_marry(user_id: int):
    """Check marry cooldown. Returns (True/False, wait_time_remaining)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_marry (
            user_id INTEGER PRIMARY KEY,
            last_marry INTEGER
        )
    """)
    conn.commit()

    cur.execute("SELECT last_marry FROM user_marry WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    now = int(time.time())

    if row:
        last_time = row[0]
        if now - last_time < COOLDOWN:
            return False, COOLDOWN - (now - last_time)

    # Update with new marry time
    cur.execute("INSERT OR REPLACE INTO user_marry (user_id, last_marry) VALUES (?, ?)", (user_id, now))
    conn.commit()
    conn.close()
    return True, 0


@app.on_message(filters.command("marry"))
async def marry_command(client, message):
    user_id = message.from_user.id
    username = message.from_user.mention

    # Cooldown check
    allowed, wait_time = can_marry(user_id)
    if not allowed:
        minutes = wait_time // 60
        seconds = wait_time % 60
        return await message.reply(f"⏳ You need to wait {minutes}m {seconds}s before trying to marry again!")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Pick random waifu excluding Cinematic Legend videos
    cur.execute("""
        SELECT id, name, anime, rarity, media_type, media_file
          FROM waifu_cards
         WHERE NOT (rarity='Cinematic Legend' AND LOWER(media_type)='video')
         ORDER BY RANDOM() LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()

    if not row:
        return await message.reply("❌ No eligible waifus found for marriage.")

    waifu_id, name, anime, rarity, media_type, media_file = row

    # 70% success, 30% reject
    success = random.choices([True, False], weights=[70, 30], k=1)[0]

    if success:
        add_waifu_to_inventory(user_id, waifu_id)

        caption = (
            f"💍 {username} got a **YES** from **{name}** "
            f"from *{anime}*! 🌸\n"
            "What a beautiful couple! ❤️"
        )
        if media_type.lower() == "photo":
            await message.reply_photo(media_file, caption=caption)
        elif media_type.lower() == "video":
            await message.reply_video(media_file, caption=caption)
        else:
            await message.reply(caption)

    else:
        caption = (
            f"💔 {username}, it seems **{name}** "
            f"from *{anime}* sees you more as a friend than a partner..."
        )
        if media_type.lower() == "photo":
            await message.reply_photo(media_file, caption=caption)
        elif media_type.lower() == "video":
            await message.reply_video(media_file, caption=caption)
        else:
            await message.reply(caption)
