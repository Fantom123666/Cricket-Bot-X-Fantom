# handlers/rarity.py

from pyrogram import filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import Config, app
from database import Database

db = Database()

RARITIES = [
    "Common", "Medium", "Rare", "Lagendary", "Limited edition",
    "Prime", "Cosmic", "Ultimate", "God"
]

RARITY_EMOJIS = [
    "😶","💨","🌹","💫","🔥","🔮","⚜️","🧚","🦋","🧊",
    "⚡"
]

# ---------------- /rarity Command ----------------
@app.on_message(filters.command("rarity"))
async def rarity_cmd(client, message: Message):
    buttons = []
    row = []
    for i, (r, e) in enumerate(zip(RARITIES, RARITY_EMOJIS), start=1):
        row.append(InlineKeyboardButton(f"{e} {r}", callback_data=f"rarity:{r}"))
        if i % 4 == 0:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    await message.reply_text(
        "🌸 Select a rarity to see the cards:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ---------------- Callback Query ----------------
PAGE_SIZE = 5

@app.on_callback_query(filters.regex(r"^rarity:"))
async def rarity_callback(client, callback_query: CallbackQuery):
    data = callback_query.data.split(":", 1)[1]  # rarity name or main
    chat_id = callback_query.message.chat.id
    page = 0
    if "::" in data:
        data, page = data.split("::")
        page = int(page)

    if data == "main":
        # Show main rarities menu
        buttons = []
        row = []
        for i, (r, e) in enumerate(zip(RARITIES, RARITY_EMOJIS), start=1):
            row.append(InlineKeyboardButton(f"{e} {r}", callback_data=f"rarity:{r}"))
            if i % 4 == 0:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        await callback_query.message.edit_text(
            "🌸 Select a rarity to see the cards:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        await callback_query.answer()
        return

    rarity_name = data

    # Fetch cards from DB
    db.cursor.execute("SELECT id, name FROM waifu_cards WHERE rarity=?", (rarity_name,))
    cards = db.cursor.fetchall()

    if not cards:
        await callback_query.message.edit_text(
            f"❌ No cards exist for rarity '{rarity_name}'.\nPlease ask admin to add cards for this rarity."
        )
        await callback_query.answer()
        return

    # Pagination
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_cards = cards[start:end]

    text = f"🌸 Cards for rarity: {rarity_name}\n\n"
    for i, card in enumerate(page_cards, start=1 + start):
        text += f"{i}. {card[1]} | ID: {card[0]}\n"

    # Navigation buttons
    nav_buttons = []
    if start > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Back", callback_data=f"rarity:{rarity_name}::{page-1}"))
    if end < len(cards):
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"rarity:{rarity_name}::{page+1}"))
    nav_buttons.append(InlineKeyboardButton("🔙 Back to rarities", callback_data="rarity:main"))

    await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([nav_buttons]))
    await callback_query.answer()
