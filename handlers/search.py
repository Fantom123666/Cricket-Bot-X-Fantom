# handlers/search.py
from pyrogram import filters
from config import app
from database import Database

db = Database()

@app.on_message(filters.command("search"))
async def search_card(client, message):
    try:
        query = message.text.split(" ", 1)[1]
    except:
        return await message.reply_text("Usage: /search <name>")

    db.cursor.execute("SELECT id, name, rarity, anime FROM waifu_cards WHERE name LIKE ? LIMIT 10", (f"%{query}%",))
    results = db.cursor.fetchall()
    
    if not results:
        return await message.reply_text("❌ No players found.")
    
    text = f"🔍 **Search Results for '{query}':**\n\n"
    for pid, name, rarity, anime in results:
        text += f"🆔 `{pid}`: **{name}** ({rarity}) - {anime}\n"
        
    await message.reply_text(text)