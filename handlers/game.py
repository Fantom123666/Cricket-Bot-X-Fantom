# handlers/game.py
import random
import time
from pyrogram import filters
from config import app
from database import Database

db = Database()
COOLDOWN = 60
user_cooldowns = {}

@app.on_message(filters.command(["toss", "dice", "basket", "football", "dart"]))
async def game_handler(client, message):
    user_id = message.from_user.id
    cmd = message.command[0]
    
    # Cooldown
    if user_id in user_cooldowns and time.time() - user_cooldowns[user_id] < COOLDOWN:
        return await message.reply_text("⏳ Please wait before playing again.")
    
    user_cooldowns[user_id] = time.time()
    
    win = False
    amount = 500 # Reward amount
    
    if cmd == "toss":
        result = random.choice(["Heads", "Tails"])
        await message.reply_text(f"🪙 Coin landed on **{result}**!")
        # Simple logic: 50% win chance if user bet (not implemented fully here)
        win = True # Just for demo
    
    elif cmd == "dice":
        roll = random.randint(1, 6)
        await message.reply_text(f"🎲 You rolled a **{roll}**!")
        if roll >= 4: win = True

    elif cmd == "basket":
        success = random.choice([True, False])
        if success:
            await message.reply_text("🏀 **Swish!** You scored!")
            win = True
        else:
            await message.reply_text("🏀 You missed!")

    # Reward
    if win:
        db.add_crystals(user_id, given=amount)
        await message.reply_text(f"🎉 You won **{amount}** crystals!")