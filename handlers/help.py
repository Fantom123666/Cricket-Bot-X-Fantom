# handlers/help.py

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import app, Config

# Role check (owner > admin > user)
def is_owner(user_id: int) -> bool:
    try:
        if getattr(Config, "OWNER_ID", None) and int(user_id) == int(Config.OWNER_ID):
            return True
        owner_ids = getattr(Config, "OWNER_IDS", None) or []
        if owner_ids and int(user_id) in [int(x) for x in owner_ids]:
            return True
    except Exception:
        pass
    return False

def is_admin(user_id: int) -> bool:
    try:
        # Owner should be considered admin as well
        if is_owner(user_id):
            return True
        admins = getattr(Config, "ADMINS", []) or []
        if admins and int(user_id) in [int(x) for x in admins]:
            return True
    except Exception:
        pass
    return False


# Plain-text command lists (no special parse_mode)
USER_TEXT = (
    "⚡ Collect Cricket players – Command Guide 🏏\n"
    "✨ Your elegant player is here to guide you through your card-collecting journey!\n\n"
    "🎀 General Commands\n"
    "/start – Begin your journey with Alisa\n"
    "/help – Show this help message\n"
    "/profile – View your collection stats\n"
    "/inventory – View your player collection\n"
    "/daily – Claim your daily gift (5,000 💎)\n"
    "/weekly – Claim your weekly treasure (25,000 💎)\n"
    "/monthly – Claim your monthly blessing (50,000 💎)\n"
    "/bonus – Redeem a weekly bonus (800,000 💎)\n"
    "/dailycode – Redeem today’s secret code for a random player\n"
    "/claim – Summon a random player (daily)\n"
    "/collect – Collect a player from an active drop\n"
    "/search [name] – Search players by name\n"
    "/checkplayer [id] – Show player details\n"
    "/craft [name] – Create a special logo & earn rewards\n"
    "/fav [player_id] – Set your favorite player\n"
    "/animesearch – Search anime by first letter\n\n"
    "💕 Love & Relationship\n"
    "/propose [player_id] – Propose to a player\n"
    "/marry [player_id] – Marry your chosen player\n"
    "/divorce – Break up with your current player\n"
    "/partner – See your current playerpartner\n"
    "/affection [player_id] – Increase bond with a player\n\n"
    "🏯 Clan System\n"
    "/createclan [name] – Create your own clan\n"
    "/myclan – View your clan’s details & members\n"
    "/joinclan [clan_id] – Join an existing clan\n"
    "/leaveclan – Leave your current clan\n"
    "/clanwar [clan_id] – Challenge another clan\n"
    "/clantop – Top clans leaderboard\n"
    "/clandonate [amount] – Donate crystals to your clan\n"
    "/clanbankwithdraw – Withdraw crystals from clan bank\n\n"
    "🛍 Market & Trading\n"
    "/mymarket – Browse your players for sale\n"
    "/sell [player_id] [price] – Sell player for crystals\n"
    "/gift [player_id] [user] – Gift a player to another collector\n"
    "/trade [user] – Trade players with another collector\n"
    "/auction [player_id] [min_price] – Start a player auction\n"
    "/bid [auction_id] [amount] – Bid in an ongoing auction\n\n"
    "📊 Stats & Leaderboards\n"
    "/top – Global top collectors\n"
    "/tdtop – Today’s top collectors\n"
    "/ctop – Top collecting chats\n"
    "/dropcount – Messages until next drop\n"
    "/rarity – View player rarity tiers\n"
    "/collectionvalue – See your collection’s total worth\n"
    "/luckyrank – Check your luck rating\n\n"
    "🎯 Mini Games with Rewards\n"
    "/dart – Throw a dart (+500 💎)\n"
    "/football – Kick a football (+500 💎)\n"
    "/basketball – Shoot a basketball (+500 💎)\n"
    "/dice – Roll a dice (+500 💎)\n"
)

ADMIN_TEXT = (
    "👮 Admin Commands\n\n"
    "🔧 Moderation\n"
    "Reply to a user with /gban – Globally ban (reply-only)\n"
    "Reply to a user with /gunban – Globally unban (reply-only)\n"
    "/mute [user] [time] – Temporarily mute a user (group reply)\n"
    "/warn [user] [reason] – Give a warning (group reply)\n"
    "/checkuser [user_id] – See full user profile\n\n"
    "🎲 Game Control\n"
    "/addplayer – Add new players card\n"
    "/delcard – Delete a player card\n"
    "/editcard – Edit card details\n"
    "/setdrop – Set message limit for card drops\n\n"
    "💰 Market Control\n"
    "/clearmarket [user_id] – Clear a user’s market listings\n"
    "/banmarket [user_id] – Block user from trading/selling\n"
)

OWNER_TEXT = (
    "👑 Owner Commands\n\n"
    "📊 Bot Stats\n"
    "/stats – Show bot usage statistics\n"
    "/event [name] – Start a global player event\n\n"
    "💎 Economy\n"
    "/reset [user_id] – Reset user’s collection\n"
    "/paycrystals [user_id] [amount] – Add crystals\n"
    "/setmultiplier [x2/x3] [duration] – Double/Triple rewards\n\n"
    "🎟 Special\n"
    "/create [player_id] [limit] – Generate redeem code\n"
    "/forcecode [user_id] [code] – Give redeem code\n"
    "/give [user] [player_id] – Give player to a user\n"
    "/removeplayer [user_id] [player_id] – Take away a player\n"
    "/seteventreward [type] [amount] – Configure event rewards\n"
)

# Keyboard (three buttons + cancel/back)
MAIN_KB = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("👤 User", callback_data="help_role:user")],
        [InlineKeyboardButton("🛡 Admin", callback_data="help_role:admin")],
        [InlineKeyboardButton("👑 Owner", callback_data="help_role:owner")],
    ]
)

BACK_KB = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("⬅️ Back", callback_data="help_back")]
    ]
)


# /help command: show role selector
@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    header = "🌸 Collect Cricket Players – Command Guide 🌸\n✨ Tap a button to view commands for that role."
    await message.reply_text(header, reply_markup=MAIN_KB)


# Callback: role selection
@app.on_callback_query(filters.regex(r"^help_role:(user|admin|owner)$"))
async def help_role_callback(client, callback: CallbackQuery):
    role = callback.data.split(":")[1]
    user_id = callback.from_user.id

    # USER: always allowed
    if role == "user":
        await callback.message.edit_text(USER_TEXT, reply_markup=BACK_KB)
        await callback.answer()
        return

    # ADMIN: only admins and owners allowed
    if role == "admin":
        if not is_admin(user_id):
            await callback.answer("❌ You are not an admin — think again.", show_alert=True)
            return
        await callback.message.edit_text(ADMIN_TEXT, reply_markup=BACK_KB)
        await callback.answer()
        return

    # OWNER: only owner(s) allowed
    if role == "owner":
        if not is_owner(user_id):
            await callback.answer("❌ You are not the owner — access denied.", show_alert=True)
            return
        # owner: show owner + admin + user (owner can see everything)
        full = OWNER_TEXT + "\n\n" + ADMIN_TEXT + "\n\n" + USER_TEXT
        await callback.message.edit_text(full, reply_markup=BACK_KB)
        await callback.answer()
        return


# Callback: back to main selector
@app.on_callback_query(filters.regex(r"^help_back$"))
async def help_back_callback(client, callback: CallbackQuery):
    await callback.message.edit_text(
        "🌸 Collect Cricket Players – Command Guide 🌸\n✨ Your elegant player is here to guide you through your card-collecting journey!\n\nTap a button to view commands for that role.",
        reply_markup=MAIN_KB
    )
    await callback.answer()