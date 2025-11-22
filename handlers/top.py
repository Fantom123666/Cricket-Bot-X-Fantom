# handlers/top.py
from pyrogram import filters
from config import app
from database import Database

db = Database()

@app.on_message(filters.command("top"))
async def top_users(client, message):
    # Get top users by total waifus collected
    db.cursor.execute("""
        SELECT u.first_name, SUM(uw.amount) as total
        FROM user_waifus uw
        JOIN users u ON uw.user_id = u.user_id
        GROUP BY uw.user_id
        ORDER BY total DESC
        LIMIT 10
    """)
    rows = db.cursor.fetchall()
    
    if not rows:
        return await message.reply_text("No data found!")

    text = "🏆 **Top Collectors** 🏆\n\n"
    for idx, (name, count) in enumerate(rows, start=1):
        text += f"{idx}. {name} - {count} Players\n"
        
    await message.reply_text(text)

@app.on_message(filters.command("ctop"))
async def top_crystals(client, message):
    # Rich users
    db.cursor.execute("""
        SELECT first_name, (daily_crystals + weekly_crystals + monthly_crystals + given_crystals) as balance
        FROM users
        ORDER BY balance DESC
        LIMIT 10
    """)
    rows = db.cursor.fetchall()
    
    text = "💎 **Richest Users** 💎\n\n"
    for idx, (name, balance) in enumerate(rows, start=1):
        text += f"{idx}. {name} - {balance} 💎\n"
        
    await message.reply_text(text)