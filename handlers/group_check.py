# handlers/group_check.py

from pyrogram import filters
from config import Config, app
from database import Database
from datetime import datetime
import os

db = Database()

# image used when logging a valid group
GROUP_LOG_IMAGE = "photo_2025-08-22_11-52-42.jpg"
MIN_MEMBERS = 1
LEAVE_MESSAGE = (
    "this Group cant afford me — group requires at least "
    f"{MIN_MEMBERS} members to add. Leaving now."
)

@app.on_chat_member_updated()
async def bot_added_to_group(client, event):
    """
    When bot is added to a group:
    - If group has fewer than MIN_MEMBERS: send message and leave (no DB/log)
    - Otherwise: add group to DB and log to SUPPORT_CHAT_ID (same behaviour as original)
    """
    try:
        # check that the update is about the bot being added
        if event.new_chat_member and event.new_chat_member.user.id == client.me.id:
            chat = event.chat
            chat_id = chat.id

            # Try to obtain member count (multiple fallbacks for robustness)
            member_count = None
            try:
                # preferred method
                member_count = await client.get_chat_members_count(chat_id)
            except Exception:
                try:
                    chat_info = await client.get_chat(chat_id)
                    # multiple possible attribute names depending on pyrogram version
                    member_count = getattr(chat_info, "members_count", None) or getattr(chat_info, "members_count_human", None) or getattr(chat_info, "members_count_estimate", None)
                except Exception:
                    member_count = None

            # If couldn't determine, treat as 0 to be safe
            if member_count is None:
                member_count = 0

            # If group too small -> notify and leave
            if int(member_count) < MIN_MEMBERS:
                try:
                    # best-effort notify (may fail if bot lacks send permission)
                    await client.send_message(chat_id=chat_id, text=LEAVE_MESSAGE)
                except Exception:
                    pass

                try:
                    await client.leave_chat(chat_id)
                except Exception as e:
                    print(f"❌ Failed to leave small group {chat_id}: {e}")

                # do not add to DB or log
                return

            # Group meets requirement -> record & log like original
            try:
                db.add_group(chat_id, chat.title)
            except Exception as e:
                print(f"⚠️ db.add_group failed for {chat_id}: {e}")

            now = datetime.now()
            date_str = now.strftime("%d/%m/%Y")
            time_str = now.strftime("%H:%M:%S")

            caption = f"""
🌸 𝒩𝑒𝓌 𝒢𝓇𝑜𝓊𝓅 𝐴𝒹𝒹𝑒𝒹! 🌸

📛 Group: {chat.title}
🆔 ID: {chat.id}
👥 Members: {member_count}

📅 Date: {date_str}
⏰ Time: {time_str}
"""

            try:
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
                print(f"❌ Failed to log group add to support chat: {e}")

    except Exception as e:
        print(f"❌ Failed in bot_added_to_group handler: {e}")
