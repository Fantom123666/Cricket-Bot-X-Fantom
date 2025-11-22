# handlers/command.py
"""
Owner-only: /commands
Scans the handlers/ folder for filters.command(...) decorators and sends a .txt
file to the bot owner (Config.OWNER_ID) listing every discovered command.
Includes duplicates removal and the filename where each command was found.

Usage (owner only):
  /commands
"""

import os
import re
import io
from datetime import datetime

from pyrogram import filters
from config import app, Config

OWNER_ID = getattr(Config, "OWNER_ID", None)
HANDLERS_DIR = "handlers"


@appt := app.on_message(filters.command("commands"))
async def send_all_commands(client, message):
    # Owner-only
    if not message.from_user or OWNER_ID is None or message.from_user.id != OWNER_ID:
        await message.reply_text("❌ This command is owner-only.")
        return

    await message.reply_text("📦 Collecting all commands from handlers...")

    commands_found = []

    # Pattern to catch filters.command(...) - we'll extract quoted strings inside the parentheses
    # This approach captures "single" and "double" quoted command names even inside lists/tuples.
    pattern = re.compile(r"filters\.command\(([^)]*)\)", re.S)

    for root, _, files in os.walk(HANDLERS_DIR):
        for file in files:
            if not file.endswith(".py"):
                continue
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception as e:
                print(f"⚠️ Could not read {path}: {e}")
                continue

            for m in pattern.finditer(text):
                inside = m.group(1)
                # find all quoted string tokens inside parentheses
                quoted = re.findall(r'["\']([^"\']+)["\']', inside)
                for q in quoted:
                    q = q.strip()
                    if not q:
                        continue
                    # normalize command (no leading slash)
                    if q.startswith("/"):
                        cmdname = q[1:]
                    else:
                        cmdname = q
                    commands_found.append((cmdname, os.path.relpath(path)))

    # Deduplicate while preserving source files (choose first occurrence)
    unique = {}
    for cmd, src in commands_found:
        if cmd not in unique:
            unique[cmd] = src

    if not unique:
        await message.reply_text("❌ No commands found in handlers/ directory.")
        return

    # Build report
    lines = []
    header = f"Bot Command List\nGenerated: {datetime.utcnow().isoformat()} UTC\nTotal Commands: {len(unique)}\n\n"
    lines.append(header)
    lines.append("Commands (command — source file):\n")
    for cmd in sorted(unique.keys()):
        lines.append(f"/{cmd}  —  {unique[cmd]}")

    content = "\n".join(lines)
    bio = io.BytesIO(content.encode("utf-8"))
    bio.name = f"command_list_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"

    # Send to owner DM
    try:
        await client.send_document(OWNER_ID, bio, caption="📜 Complete list of all bot commands.")
        await message.reply_text("✅ Sent the commands list to owner's DM.")
    except Exception as e:
        # fallback to send in chat where command was used
        try:
            bio.seek(0)
            await client.send_document(message.chat.id, bio, caption=f"📜 Command list (fallback): {e}")
        except Exception as e2:
            await message.reply_text(f"Failed to send command list: {e}; fallback error: {e2}")
