# rewards.py

from pyrogram import filters, types
from config import Config, app
from database import Database
from datetime import datetime, timedelta

db = Database()

SUPPORT_GROUP = "@suppofcollectyourcrickers"
SUPPORT_CHANNEL = "@CricketCollecterBot"

# ---------------- Helper Functions ----------------

async def is_member(user_id):
    """Check if user is member of both group and channel."""
    try:
        group_status = await app.get_chat_member(SUPPORT_GROUP, user_id)
        channel_status = await app.get_chat_member(SUPPORT_CHANNEL, user_id)
        # If not banned or left
        if group_status.status not in ["left", "kicked"] and channel_status.status not in ["left", "kicked"]:
            return True
        return False
    except:
        return False

async def send_claim_prompt(message, reward_type, reward_amount, user_id):
    """Send join buttons or claim button based on membership."""
    if not await is_member(user_id):
        buttons = [
            [types.InlineKeyboardButton("Join Support Group", url=f"https://t.me/{SUPPORT_GROUP[1:]}")],
            [types.InlineKeyboardButton("Join Support Channel", url=f"https://t.me/{SUPPORT_CHANNEL[1:]}")],
        ]
        keyboard = types.InlineKeyboardMarkup(buttons)
        await message.reply_text(
            "❌ You must join the support group and channel to claim your reward!",
            reply_markup=keyboard
        )
        return False
    else:
        buttons = [
            [types.InlineKeyboardButton("✅ Claim Now", callback_data=f"claim:{reward_type}:{reward_amount}")]
        ]
        keyboard = types.InlineKeyboardMarkup(buttons)
        await message.reply_text(
            f"💎 Your {reward_type} reward is ready! Click ✅ Claim Now to receive {reward_amount} crystals.",
            reply_markup=keyboard
        )
        return True

async def give_reward(user_id, reward_type, reward_amount, cooldown, message=None):
    """Grant reward with cooldown check."""
    db.add_user(user_id, message.from_user.username if message else None,
                message.from_user.first_name if message else None)

    last_claim = db.get_last_claim(user_id, reward_type)
    if last_claim:
        last_claim_dt = datetime.fromisoformat(last_claim)
        if datetime.utcnow() - last_claim_dt < cooldown:
            if message:
                await message.reply_text(f"⏳ You already claimed your **{reward_type} reward**! Try again later.")
            return False

    db.add_crystals(user_id, **{reward_type: reward_amount})
    db.update_last_claim(user_id, reward_type, datetime.utcnow().isoformat())

    if message:
        await message.reply_text(f"✅ You received {reward_amount} 💎 {reward_type} crystals!")
    return True

# ---------------- Commands ----------------

@app.on_message(filters.command("daily"))
async def daily_cmd(client, message):
    await send_claim_prompt(message, "daily", Config.DAILY_CRYSTAL, message.from_user.id)

@app.on_message(filters.command("weekly"))
async def weekly_cmd(client, message):
    await send_claim_prompt(message, "weekly", Config.WEEKLY_CRYSTAL, message.from_user.id)

@app.on_message(filters.command("monthly"))
async def monthly_cmd(client, message):
    await send_claim_prompt(message, "monthly", Config.MONTHLY_CRYSTAL, message.from_user.id)

# ---------------- Callback ----------------

@app.on_callback_query(filters.regex(r"^claim:(daily|weekly|monthly):(\d+)$"))
async def claim_callback(client, callback_query):
    reward_type = callback_query.data.split(":")[1]
    reward_amount = int(callback_query.data.split(":")[2])
    user_id = callback_query.from_user.id

    # Re-check membership before giving reward
    if not await is_member(user_id):
        await callback_query.answer("❌ You must join the support group and channel to claim.", show_alert=True)
        return

    cooldowns = {
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "monthly": timedelta(days=30)
    }

    success = await give_reward(user_id, reward_type, reward_amount, cooldowns[reward_type], callback_query.message)
    if success:
        await callback_query.answer("✅ Reward claimed!", show_alert=True)
        await callback_query.message.edit_text(f"✅ You claimed your {reward_type} reward of {reward_amount} 💎!")
    else:
        await callback_query.answer("⏳ You already claimed this reward.", show_alert=True)
