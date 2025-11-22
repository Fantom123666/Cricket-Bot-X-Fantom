from pyrogram import filters
from config import app, OWNER_ID
from database import Database

db = Database()

@app.on_message(filters.command("paycrystal") & filters.user(OWNER_ID))
async def pay_crystal(client, message):
    if len(message.command) < 2 or not message.command[1].isdigit():
        await message.reply_text("Usage: /paycrystal <amount>")
        return

    amount = int(message.command[1])
    target = message.reply_to_message.from_user if message.reply_to_message else None

    if not target:
        await message.reply_text("Reply to a user's message to give crystals.")
        return

    db.add_crystals(target.id, given=amount)
    await message.reply_text(f"💎 Gave {amount} crystals to {target.first_name}.")
