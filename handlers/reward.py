from pyrogram import filters
from config import app, Config
import sqlite3, random, time

DB_PATH = Config.DB_PATH

def add_waifu_to_inventory(user_id, waifu_id):
    """Insert or update user_waifus with given waifu_id"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()

        # Try to increment existing row
        cur.execute("""
            UPDATE user_waifus
               SET amount = amount + 1,
                   last_collected = strftime('%s','now')
             WHERE user_id = ? AND waifu_id = ?
        """, (user_id, waifu_id))

        if cur.rowcount == 0:
            # No row yet, insert
            cur.execute("""
                INSERT INTO user_waifus (user_id, waifu_id, amount, last_collected)
                VALUES (?, ?, 1, strftime('%s','now'))
            """, (user_id, waifu_id))

        conn.commit()
    finally:
        conn.close()

def has_claimed_reward(user_id):
    """Check if user already claimed the one-time reward"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM user_claims WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None

def mark_reward_claimed(user_id):
    """Mark user as having claimed reward"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO user_claims (user_id, last_claim) VALUES (?, ?)",
        (user_id, int(time.time()))
    )
    conn.commit()
    conn.close()

@app.on_message(filters.command("reward"))
async def reward_command(client, message):
    user_id = message.from_user.id

    # Check if already claimed
    if has_claimed_reward(user_id):
        await message.reply("❌ You have already claimed your special reward!")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # First try Cinematic Legend video cards
    cur.execute("""
        SELECT id, name, anime, event, media_file
          FROM waifu_cards
         WHERE rarity = 'Cinematic Legend'
           AND LOWER(media_type) = 'video'
         ORDER BY RANDOM() LIMIT 1
    """)
    row = cur.fetchone()

    # Fallback: if none, give any video card
    if not row:
        cur.execute("""
            SELECT id, name, anime, event, media_file
              FROM waifu_cards
             WHERE LOWER(media_type) = 'video'
             ORDER BY RANDOM() LIMIT 1
        """)
        row = cur.fetchone()

    conn.close()

    if not row:
        await message.reply("❌ No video cards available in the database.")
        return

    waifu_id, name, anime, theme, media_file = row

    # Save reward in inventory
    add_waifu_to_inventory(user_id, waifu_id)
    mark_reward_claimed(user_id)

    # Send video preview
    caption = (
        "🎉 You received a special reward!\n\n"
        f"🆔 ID: {waifu_id}\n"
        f"💖 Waifu: {name}\n"
        f"📺 Anime: {anime}\n"
        f"🎭 Theme: {theme}\n\n"
        "✨ Added to your inventory!"
    )

    await message.reply_video(media_file, caption=caption)
