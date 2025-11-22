# main.py
import importlib
import os
import asyncio
from pyrogram.types import BotCommand
from config import app

# Handlers load karne ka function
def load_handlers():
    handlers_dir = "handlers"
    if not os.path.exists(handlers_dir):
        print(f"❌ Error: '{handlers_dir}' folder nahi mila!")
        return

    for filename in os.listdir(handlers_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = f"{handlers_dir}.{filename[:-3]}"
            try:
                importlib.import_module(module_name)
                print(f"✅ Loaded: {filename}")
            except Exception as e:
                print(f"❌ Failed to load {filename}: {e}")

async def start_bot():
    print("-----------------------------------------")
    print("   🚀 Starting CricketBot... ")
    print("-----------------------------------------")

    # 1. Handlers load karein
    load_handlers()

    # 2. Bot Start karein
    await app.start()
    print("✅ Bot Connected to Telegram!")

    # 3. Menu Commands set karein (Saare User Features)
    print("⏳ Setting up Menu Commands...")
    try:
        await app.set_bot_commands([
            # Basic
            BotCommand("start", "🎮 Start Journey"),
            BotCommand("help", "📚 Command List"),
            BotCommand("id", "🆔 User/Chat ID"),

            # Profile & Collection
            BotCommand("profile", "👤 Check Profile"),
            BotCommand("inventory", "🎒 Your Cards"),
            BotCommand("wmode", "⚙️ Sort Inventory"),
            BotCommand("partner", "💞 View Partner"),
            BotCommand("fav", "❤️ Set Favorite"),

            # Collecting
            BotCommand("claim", "🎲 Daily Summon"),
            BotCommand("collect", "grab dropped card"),
            BotCommand("search", "🔍 Search Card"),
            BotCommand("checkwaifu", "📄 Card Details"),

            # Rewards & Economy
            BotCommand("daily", "💰 Daily Reward"),
            BotCommand("weekly", "🎁 Weekly Reward"),
            BotCommand("monthly", "🌙 Monthly Reward"),
            BotCommand("bonus", "💎 Bonus Reward"),
            BotCommand("redeem", "🎟 Redeem Code"),
            BotCommand("balance", "💳 Check Balance"),

            # Banking
            BotCommand("bank", "🏦 Waifu Bank"),
            BotCommand("atmcard", "💳 Buy ATM Card"),
            BotCommand("atmmachine", "🏧 Withdraw Cash"),
            BotCommand("loan", "💸 Apply Loan"),

            # Market & Trading
            BotCommand("mymarket", "🛒 Buying Market"),
            BotCommand("buy", "🛍 Buy Card"),
            BotCommand("trade", "🤝 Trade Cards"),
            BotCommand("gift", "🎁 Gift Card"),
            BotCommand("auction", "🔨 Start Auction"),
            BotCommand("bid", "🙋‍♂️ Place Bid"),

            # Clan System
            BotCommand("myclan", "🏯 Clan Info"),
            BotCommand("createclan", "⚔️ Create Clan"),
            BotCommand("clantop", "🏆 Top Clans"),

            # Relationships
            BotCommand("propose", "💍 Propose Waifu"),
            BotCommand("marry", "💒 Marry Waifu"),
            BotCommand("divorce", "💔 Breakup"),
            BotCommand("affection", "💗 Increase Bond"),

            # Mini Games (Earning)
            BotCommand("bet", "🎰 Betting"),
            BotCommand("toss", "🪙 Coin Toss"),
            BotCommand("dice", "🎲 Dice Roll"),
            BotCommand("basket", "🏀 Basketball"),
            BotCommand("football", "⚽ Football"),

            # Stats & Info
            BotCommand("top", "🌍 Global Top"),
            BotCommand("ctop", "💎 Richest Users"),
            BotCommand("rarity", "✨ Rarity List"),
            BotCommand("dropcount", "⏳ Drop Status"),
            BotCommand("collectionvalue", "💲 Collection Worth"),
            BotCommand("luckyrank", "🍀 Your Luck")
        ])
        print("✅ All User Features Added to Menu!")
        

    except Exception as e:
    print(f"⚠️ Failed to set commands: {e}")

print("🤖 Bot is now running... (Press CTRL+C to stop)")

await asyncio.Event().wait()

if __name__ == "__main__":
    # Asyncio loop chalayenge
    try:
        app.run(start_bot())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ Error: {e}")