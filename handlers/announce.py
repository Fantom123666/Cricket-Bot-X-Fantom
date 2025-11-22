from pyrogram import Client, filters
import sqlite3
import asyncio

from config import app, OWNER_ID

# Connect to your existing database
conn = sqlite3.connect("waifu_bot.db", check_same_thread=False)
cur = conn.cursor()

@app.on_message(filters.command("announce") & filters.user(OWNER_ID))
async def announce_cmd(client, message):
    # --- Detect announcement content ---
    text = None
    media = None

    if message.reply_to_message:
        # Reply to text
        if message.reply_to_message.text:
            text = message.reply_to_message.text

        # Reply to photo (with or without caption)
        elif message.reply_to_message.photo:
            media = (
                "photo",
                message.reply_to_message.photo.file_id,
                message.reply_to_message.caption or ""
            )

        # Reply to video (optional support)
        elif message.reply_to_message.video:
            media = (
                "video",
                message.reply_to_message.video.file_id,
                message.reply_to_message.caption or ""
            )

    else:
        # Inline text after command
        parts = message.text.split(" ", 1) if message.text else []
        if len(parts) < 2:
            await message.reply(
                "❌ Usage:\n"
                "- `/announce some text`\n"
                "- Reply `/announce` to a message or photo"
            )
            return
        text = parts[1]

    status = await message.reply("📢 Sending announcement...")

    # --- Load users & groups from DB ---
    try:
        cur.execute("SELECT user_id FROM users")
        users = [row[0] for row in cur.fetchall()]
    except Exception:
        users = []

    try:
        cur.execute("SELECT chat_id FROM groups")
        groups = [row[0] for row in cur.fetchall()]
    except Exception:
        groups = []

    total = len(users) + len(groups)
    sent, failed = 0, 0

    # --- Send to all ---
    for uid in users + groups:
        try:
            if media:
                if media[0] == "photo":
                    await app.send_photo(uid, media[1], caption=media[2])
                elif media[0] == "video":
                    await app.send_video(uid, media[1], caption=media[2])
            else:
                await app.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.3)  # avoid flood limit

    await status.edit_text(
        f"📢 Announcement complete!\n\n"
        f"✅ Sent: {sent}\n❌ Failed: {failed}\n📊 Total: {total}"
    )
