# handlers/start.py

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import Config, app
from database import Database
from datetime import datetime
import os
import asyncio

db = Database()

# Paths for images
LOG_IMAGE_PATH = "log.jpg"          # For user log
WELCOME_IMAGE_PATH = "welcome.jpg"  # For welcome message
GROUP_LOG_IMAGE = "photo_2025-08-22_11-52-42.jpg"   # For group log

# ------------------- Reaction / animation settings -------------------
# Use only standard Unicode emojis here — not custom/animated Telegram emojis.
REACTION_SEQUENCE = ["🏏", "🥎", "⚡"]
DELAY_BETWEEN = 0.6   # seconds between frames of the "animation"
EPHEMERAL_LIFETIME = 1.2  # seconds to keep final frame before deleting (set 0 to keep)
# --------------------------------------------------------------------

# ------------------- USER START -------------------
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    # ignore messages coming from other bots
    if message.from_user and getattr(message.from_user, "is_bot", False):
        return

    # get message id compatibly across pyrogram versions
    msg_id = getattr(message, "id", None) or getattr(message, "message_id", None)

    # Attempt real reaction first (may raise BOT_METHOD_INVALID for bots)
    reacted = False
    if msg_id:
        for emoji in REACTION_SEQUENCE:
            try:
                await client.send_reaction(chat_id=message.chat.id, message_id=msg_id, emoji=emoji)
                reacted = True
            except Exception as exc:
                # Detect BOT_METHOD_INVALID from exception string (pyrogram error class may vary)
                err_str = repr(exc)
                # If it's the BOT_METHOD_INVALID (can't use method as bot), stop trying and use fallback.
                if "BOT_METHOD_INVALID" in err_str or "The method can't be used by bots" in err_str:
                    # fallback path below
                    try:
                        client.logger.info("start_reaction: send_reaction not allowed for bot -> using fallback animation")
                    except Exception:
                        print("start_reaction: send_reaction not allowed for bot -> using fallback animation")
                    reacted = False
                    break
                # If other error (permissions etc.), stop trying further.
                try:
                    client.logger.warning("start_reaction: failed to add %s on chat %s -> %s", emoji, message.chat.id, err_str)
                except Exception:
                    print("start_reaction: failed to add", emoji, message.chat.id, err_str)
                reacted = False
                break

            await asyncio.sleep(DELAY_BETWEEN)

    # If real reaction was not possible, use fallback animation (ephemeral edited reply)
    if not reacted and msg_id:
        try:
            # send an ephemeral reply (first frame)
            ephemeral = await client.send_message(
                chat_id=message.chat.id,
                reply_to_message_id=msg_id,
                text=REACTION_SEQUENCE[0]
            )
            # sequentially edit that ephemeral message to other emojis to simulate animation
            for frame in REACTION_SEQUENCE[1:]:
                await asyncio.sleep(DELAY_BETWEEN)
                try:
                    await client.edit_message_text(
                        chat_id=ephemeral.chat.id,
                        message_id=ephemeral.id,
                        text=frame
                    )
                except Exception as exc:
                    # editing may fail in very restricted groups; ignore and stop animation
                    try:
                        client.logger.warning("start_reaction fallback edit failed: %s", repr(exc))
                    except Exception:
                        print("start_reaction fallback edit failed:", repr(exc))
                    break

            # keep final frame visible briefly, then delete the ephemeral message (cleanup)
            if EPHEMERAL_LIFETIME > 0:
                await asyncio.sleep(EPHEMERAL_LIFETIME)
                try:
                    await client.delete_messages(chat_id=ephemeral.chat.id, message_ids=ephemeral.id)
                except Exception:
                    # Deletion might fail in some groups if bot lacks rights; ignore silently
                    pass

        except Exception as exc:
            # If sending the ephemeral message failed, just continue without animation.
            try:
                client.logger.warning("start_reaction fallback send failed: %s", repr(exc))
            except Exception:
                print("start_reaction fallback send failed:", repr(exc))

    # --- existing logic preserved below (unchanged) ---
    user = message.from_user
    user_id = user.id
    username = user.username if user.username else "None"
    first_name = user.first_name if user.first_name else "Unknown"

    # Save user in DB
    db.add_user(user_id, username, first_name)

    # --------- One-time User Log (only in DM) ---------
    if message.chat.type == "private" and not db.is_first_logged(user_id):
        now = datetime.now()
        date_str = now.strftime("%d/%m/%Y")
        time_str = now.strftime("%H:%M:%S")

        caption = f"""
🌸 𝒩𝑒𝓌 𝒰𝓈𝑒𝓇 𝒥𝑜𝒾𝓃𝑒𝒹! 🌸

👤 Name: {first_name}
🏷️ Username: @{username}
🆔 ID: {user_id}

📅 Date: {date_str}
⏰ Time: {time_str}
"""

        try:
            if os.path.exists(LOG_IMAGE_PATH):
                await client.send_photo(
                    chat_id=Config.SUPPORT_CHAT_ID,
                    photo=LOG_IMAGE_PATH,
                    caption=caption
                )
            else:
                await client.send_message(
                    chat_id=Config.SUPPORT_CHAT_ID,
                    text=caption
                )
            db.set_first_logged(user_id)
        except Exception as e:
            print(f"❌ Failed to send user log: {e}")

    # --------- Welcome Message (DM or Group) ---------
    welcome_text = f"""
🏏 Welcome Lagend ! Collect players and make your team ⚡

🍰 You’ve been warmly greeted by **Collect Cricket Players ** 💕

👤 **User Info**:
🌸 Name: {first_name}
🏷️ Username: @{username}
🆔 ID: {user_id}

📜 **Available Commands:**
Type /help to explore 🎀

✨ “Let’s collect Cricketers and build team together~” 💫
"""

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add me to Group", url=f"https://t.me/{Config.BOT_USERNAME}?startgroup=true")],
        [
            InlineKeyboardButton("💬 Support Group", url=Config.SUPPORT_GROUP),
            InlineKeyboardButton("📢 Support Channel", url=Config.UPDATE_CHANNEL)
        ],
        [InlineKeyboardButton("👑 Owner", url=f"https://t.me/{Config.OWNER_USERNAME.strip('@')}")]
    ])

    if os.path.exists(WELCOME_IMAGE_PATH):
        await message.reply_photo(
            photo=WELCOME_IMAGE_PATH,
            caption=welcome_text,
            reply_markup=buttons
        )
    else:
        await message.reply_text(
            text=welcome_text,
            reply_markup=buttons
        )

# ------------------- GROUP LOG -------------------
@app.on_chat_member_updated()
async def bot_added_to_group(client, event):
    """
    Triggered when bot is added to a group
    Works with Pyrogram v1
    """
    try:
        if event.new_chat_member and event.new_chat_member.user.id == client.me.id:
            # Bot was added to a group
            chat = event.chat
            db.add_group(chat.id, chat.title)

            now = datetime.now()
            date_str = now.strftime("%d/%m/%Y")
            time_str = now.strftime("%H:%M:%S")

            caption = f"""
🌸 𝒢𝓇𝑜𝓊𝓅 𝒜𝒹𝒹𝑒𝒹! 🌸

📛 Group: {chat.title}
🆔 ID: {chat.id}

📅 Date: {date_str}
⏰ Time: {time_str}
"""

            if os.path.exists(GROUP_LOG_IMAGE):
                await client.send_photo(
                    chat_id=Config.SUPPORT_CHAT_ID,
                    photo=GROUP_LOG_IMAGE,
                    caption=caption
                )
            else:
                await client.send_message(
                    chat_id=Config.SUPPORT_CHAT_ID,
                    text=caption
                )

    except Exception as e:
        print(f"❌ Failed to log group add: {e}")
