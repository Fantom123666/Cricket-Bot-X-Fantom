# handlers/sanime.py

import sqlite3
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.enums import ParseMode

DB_PATH = "waifu_bot.db"
OWNER_ID = 7558715645   # replace with your ID
ADMIN_IDS = [OWNER_ID]  # add more admin IDs if needed


def get_anime_distribution(filter_anime: str = None):
    """Fetch anime distribution (optionally filter by one anime)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if filter_anime:
        cursor.execute(
            "SELECT anime, COUNT(*) FROM waifu_cards WHERE anime LIKE ? GROUP BY anime ORDER BY COUNT(*) DESC;",
            (f"%{filter_anime}%",),
        )
    else:
        cursor.execute(
            "SELECT anime, COUNT(*) FROM waifu_cards GROUP BY anime ORDER BY COUNT(*) DESC;"
        )

    results = cursor.fetchall()
    conn.close()
    return results


def format_page(anime_list, page, per_page=10, filter_anime=None):
    """Format the anime distribution text for one page."""
    start = page * per_page
    end = start + per_page
    sliced = anime_list[start:end]

    title = "📊 <b>Anime Character Distribution</b>\n"
    if filter_anime:
        title += f"🔎 Filter: <b>{filter_anime}</b>\n"
    title += "\n"

    if not sliced:
        return title + "❌ No anime found."

    total = sum([c for _, c in anime_list])
    text = title + f"📦 <b>Total Cards:</b> {total}\n\n"

    for idx, (anime, count) in enumerate(sliced, start=start + 1):
        text += f"{idx}. 🎬 {anime} — <b>{count} cards</b>\n"

    text += f"\nPage {page+1}/{(len(anime_list) - 1) // per_page + 1}"
    return text


def build_keyboard(page, total, filter_anime=None, per_page=10):
    """Build inline keyboard with prev/next buttons."""
    buttons = []
    if page > 0:
        buttons.append(
            InlineKeyboardButton(
                "⬅️ Prev",
                callback_data=f"sanime_page_{page-1}|{filter_anime or 'ALL'}",
            )
        )
    if (page + 1) * per_page < total:
        buttons.append(
            InlineKeyboardButton(
                "➡️ Next",
                callback_data=f"sanime_page_{page+1}|{filter_anime or 'ALL'}",
            )
        )

    return InlineKeyboardMarkup([buttons]) if buttons else None


# Register /sanime command
from config import app


@app.on_message(filters.command("sanime"))
async def sanime_handler(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply_text("⛔ This command is restricted to Admin/Owner only.")
        return

    args = message.text.split(maxsplit=1)
    filter_anime = args[1].strip() if len(args) > 1 else None

    anime_list = get_anime_distribution(filter_anime)
    if not anime_list:
        await message.reply_text("❌ No anime found in database yet.")
        return

    page = 0
    text = format_page(anime_list, page, filter_anime=filter_anime)
    keyboard = build_keyboard(page, len(anime_list), filter_anime)

    await message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# Handle callback pagination
@app.on_callback_query(filters.regex(r"^sanime_page_"))
async def sanime_callback(client: Client, query: CallbackQuery):
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("⛔ You are not allowed to use this.", show_alert=True)
        return

    data = query.data.split("_", 2)[-1]  # e.g., "2|Naruto" or "1|ALL"
    page_str, filter_anime = data.split("|", 1)
    page = int(page_str)
    filter_anime = None if filter_anime == "ALL" else filter_anime

    anime_list = get_anime_distribution(filter_anime)

    text = format_page(anime_list, page, filter_anime=filter_anime)
    keyboard = build_keyboard(page, len(anime_list), filter_anime)

    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    await query.answer()
