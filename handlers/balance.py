from pyrogram import filters
from config import app
from database import Database

db = Database()

@app.on_message(filters.command("balance"))
async def balance_cmd(client, message):
    user_id = message.from_user.id
    daily, weekly, monthly, total, last_claim, given = db.get_crystals(user_id)

    await message.reply_text(
        f"💎 Your crystal balance:\n\n"
        f"• Daily: {daily}\n"
        f"• Weekly: {weekly}\n"
        f"• Monthly: {monthly}\n"
        f"• Given by owner: {given}\n"
        f"• Total: {total}\n"
        f"⏰ Last claim: {last_claim if last_claim else 'Never'}"
    )
