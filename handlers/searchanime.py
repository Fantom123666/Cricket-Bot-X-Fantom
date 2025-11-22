# handlers/searchanime.py
"""
/animesearch — Search anime by first letter.

Displays A-Z inline keyboard. Clicking a letter shows all anime names
found in your waifu_cards.anime column that start with that letter.
"""

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import app
from database import Database

db = Database()

ALPHABET = [chr(c) for c in range(ord("A"), ord("Z") + 1)]

# Build alphabet keyboard in compact rows
def alphabet_keyboard():
    buttons = []
    row = []
    for i, ch in enumerate(ALPHABET, start=1):
        row.append(InlineKeyboardButton(ch, callback_data=f"animesearch:{ch}"))
        # 6 buttons per row for tidy layout
        if i % 6 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # add a close/back button row
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="animesearch:close")])
    return InlineKeyboardMarkup(buttons)

BACK_KB = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="animesearch:back")],
                                [InlineKeyboardButton("❌ Close", callback_data="animesearch:close")]])


@app.on_message(filters.command("animesearch"))
async def animesearch_cmd(client, message):
    """
    Show alphabet keyboard.
    """
    text = "🔎 **Anime Search**\n\nTap a letter to list anime names starting with that character."
    # Use plain text to avoid parse_mode issues in different pyrogram versions
    await message.reply_text(text, reply_markup=alphabet_keyboard())


@app.on_callback_query(filters.regex(r"^animesearch:(?P<action>.+)$"))
async def animesearch_callback(client, callback: CallbackQuery):
    """
    Handle:
      animesearch:A      -> show anime names starting with A
      animesearch:back   -> show alphabet again
      animesearch:close  -> close (delete) the help message
    """
    data = callback.data.split(":", 1)[1]

    # Close message
    if data == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()
        return

    # Back to alphabet
    if data == "back":
        try:
            await callback.message.edit_text(
                "🔎 **Anime Search**\n\nTap a letter to list anime names starting with that character.",
                reply_markup=alphabet_keyboard()
            )
        except Exception:
            pass
        await callback.answer()
        return

    # Letter selected (A-Z)
    letter = data.upper()
    if len(letter) != 1 or not letter.isalpha():
        await callback.answer("Invalid selection.", show_alert=True)
        return

    # Query distinct anime names starting with that letter from waifu_cards.anime
    try:
        query = """
            SELECT DISTINCT anime
            FROM waifu_cards
            WHERE anime IS NOT NULL AND anime <> '' AND UPPER(anime) LIKE ?
            ORDER BY anime COLLATE NOCASE ASC
            LIMIT 100
        """
        like_pattern = f"{letter}%"
        db.cursor.execute(query, (like_pattern,))
        rows = db.cursor.fetchall()
        anime_names = [r[0] for r in rows if r and r[0]]
    except Exception as e:
        # On DB error, inform the user (but don't crash)
        await callback.answer("Database error. Try again later.", show_alert=True)
        return

    if not anime_names:
        # no results
        await callback.answer(f"No anime found starting with '{letter}'.", show_alert=True)
        return

    # Format list (limit display to 50 for readability)
    MAX_DISPLAY = 50
    display_list = anime_names[:MAX_DISPLAY]
    text_lines = [f"✨ Anime starting with '{letter}':\n"]
    for idx, name in enumerate(display_list, start=1):
        text_lines.append(f"{idx}. {name}")
    if len(anime_names) > MAX_DISPLAY:
        text_lines.append(f"\n...and {len(anime_names) - MAX_DISPLAY} more (truncated)")

    final_text = "\n".join(text_lines)

    # Edit message to show results and Back/Close keyboard
    try:
        await callback.message.edit_text(final_text, reply_markup=BACK_KB)
    except Exception:
        # If edit fails (message changed/deleted), try to send a new message
        await callback.message.reply_text(final_text, reply_markup=BACK_KB)

    await callback.answer()
