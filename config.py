# config.py

from pyrogram import Client

class Config:
    # Bot credentials
    BOT_TOKEN = "8291019887:AAEe6ge_X3XQlgz-KSgaDi89i31H3b18r2Y"
    API_ID = 37869233
    API_HASH = "c71c39e03fabd7a52c1ef8748df7dba5"

    # Database
    DB_PATH = "waifu_bot.db"

    # Owner & Support details
    OWNER_ID = 7558715645
    ADMINS = [6398668820, 8145220564, 8129006359]
    OWNER_USERNAME = "@Imfantommmm"
    SUPPORT_GROUP = "https://t.me/suppofcollectyourcrickers"
    SUPPORT_CHAT_ID = -1003314061685  # Group chat ID for logging & notifications
    UPDATE_CHANNEL = "https://t.me/CricketCollecterBot"
    
    BOT_USERNAME = "CollectCrickerPlayerssBot"

    # Crystal Rewards
    DAILY_CRYSTAL = 5000
    WEEKLY_CRYSTAL = 25000
    MONTHLY_CRYSTAL = 50000

# Create Pyrogram Client here so every handler can import and use it
app = Client(
    "waifu_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

# expose important constants at top level
OWNER_ID = Config.OWNER_ID
ADMINS = Config.ADMINS
