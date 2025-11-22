from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from pyrogram.errors import MessageNotModified
import sqlite3, random, time
from config import app, Config

DB_PATH = Config.DB_PATH

# cooldown tracking: {user_id: timestamp}
propose_cooldowns = {}

# in-memory store for proposal actions
# {short_id: (user_id, card_id, waifu_name, media_type, media_file)}
pending_proposals = {}

def gen_short_id(length=6):
    import string
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

async def finalize_proposal(callback_query, text, media_type, media_file):
    """Edit media/caption & remove buttons safely."""
    try:
        await callback_query.message.edit_reply_markup(None)
    except MessageNotModified:
        pass

    try:
        if media_type == "video":
            media = InputMediaVideo(media_file, caption=text)
        else:
            media = InputMediaPhoto(media_file, caption=text)
        await callback_query.message.edit_media(media)
    except MessageNotModified:
        try:
            await callback_query.message.edit_caption(caption=text)
        except MessageNotModified:
            pass

@app.on_message(filters.command("propose"))
async def propose_waifu(client, message):
    user_id = message.from_user.id
    now = time.time()

    # 5 min cooldown
    last = propose_cooldowns.get(user_id)
    if last and now - last < 300:
        wait_s = int(300 - (now - last))
        await message.reply(f"⏳ You must wait {wait_s} seconds before proposing again.")
        return
    propose_cooldowns[user_id] = now

    # pick a random waifu
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, name, media_type, media_file FROM waifu_cards ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    conn.close()

    if not row:
        await message.reply("❌ No waifu cards available in the database.")
        return

    card_id, waifu_name, media_type, media_file = row

    short_id = gen_short_id()
    pending_proposals[short_id] = (user_id, card_id, waifu_name, media_type, media_file)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💖 Pour your heart out", callback_data=f"propose_accept:{short_id}"),
            InlineKeyboardButton("🚶 Walk away", callback_data=f"propose_reject:{short_id}"),
        ]
    ])

    caption = (
        "🌠 A Fateful Encounter...\n\n"
        f"💖 {waifu_name} stands before you\n"
        "Will you confess your deepest feelings?"
    )

    if media_type == "video":
        await message.reply_video(media_file, caption=caption, reply_markup=kb)
    else:
        await message.reply_photo(media_file, caption=caption, reply_markup=kb)

@app.on_callback_query(filters.regex(r"^propose_accept:(\w+)$"))
async def handle_accept(client, callback_query):
    short_id = callback_query.data.split(":")[1]
    data = pending_proposals.pop(short_id, None)
    if not data:
        await callback_query.answer("❌ This proposal expired.", show_alert=True)
        return

    user_id, card_id, waifu_name, media_type, media_file = data

    if callback_query.from_user.id != user_id:
        await callback_query.answer("❌ This is not your proposal.", show_alert=True)
        return

    # 30% chance to fail dramatically
    if random.randint(1, 100) <= 30:
        text = (
            f"{waifu_name} vanished like the wind... leaving only silence 🌪️\n\n"
            "💫 *The third time's the charm... Keep trying!*"
        )
        await finalize_proposal(callback_query, text, media_type, media_file)
        return

    # Accepted: add to user_waifus WITHOUT schema changes (manual upsert)
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()

        # Try to increment existing
        cur.execute(
            """
            UPDATE user_waifus
               SET amount = amount + 1,
                   last_collected = strftime('%s','now')
             WHERE user_id = ? AND waifu_id = ?
            """,
            (user_id, card_id),
        )

        if cur.rowcount == 0:
            # No existing row: insert new
            cur.execute(
                """
                INSERT INTO user_waifus (user_id, waifu_id, amount, last_collected)
                VALUES (?, ?, 1, strftime('%s','now'))
                """,
                (user_id, card_id),
            )

        conn.commit()
    finally:
        conn.close()

    text = (
        f"💖 The world seemed to pause when {waifu_name} embraced you... *\"I'm yours\"* 💕\n\n"
        f"💞 {waifu_name} has been added to your harem!"
    )
    await finalize_proposal(callback_query, text, media_type, media_file)

@app.on_callback_query(filters.regex(r"^propose_reject:(\w+)$"))
async def handle_reject(client, callback_query):
    short_id = callback_query.data.split(":")[1]
    data = pending_proposals.pop(short_id, None)
    if not data:
        await callback_query.answer("❌ This proposal expired.", show_alert=True)
        return

    _, _, waifu_name, media_type, media_file = data

    text = (
        f"{waifu_name} vanished like the wind... leaving only silence 🌪️\n\n"
        "💫 *The third time's the charm... Keep trying!*"
    )
    await finalize_proposal(callback_query, text, media_type, media_file)
