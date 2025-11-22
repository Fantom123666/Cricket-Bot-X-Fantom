# handlers/collection_and_luck.py
"""
Fixed version: awaits Pyrogram coroutines correctly.

Provides:
 - /collectionvalue
 - /luckyrank (with paginated leaderboard)
"""

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import app, Config
from database import Database
from datetime import datetime
import math

db = Database()

# ---------- Collection tiers ----------
COLLECTION_TIERS = [
    (0, 100, "🌱 Beginner Collector"),
    (101, 200, "📚 Novice Seeker"),
    (201, 300, "🎀 Charming Gatherer"),
    (301, 500, "💎 Rare Hunter"),
    (501, 700, "🌹 Elegant Collector"),
    (701, 1000, "🔥 Enchanted Master"),
    (1001, 1500, "🌈 Chroma Guardian"),
    (1501, 2000, "🦋 Ethereal Conqueror"),
    (2001, 3000, "👑 Divine Ascendant"),
    (3001, 10**9, "🐉 Eternal Waifu Emperor"),
]

# ---------- Lucky rank names (100 entries) ----------
LUCKY_NAMES = []
LUCKY_NAMES += [
    "🍂 Unlucky Soul", "🐌 Slow Fortune", "🪙 Pocket Change Finder", "🌧️ Rain Magnet",
    "🥀 Broken Charm Holder", "🦴 Dog Bone Luck", "🪤 Trap Stepped", "🪦 Grave Dice Roller",
    "🕳️ Void Gambler", "🦆 Duck Luck", "🍞 Stale Bread Finder", "🧩 Missing Piece",
    "🥢 Chopstick Dropper", "📉 Minus Fortune", "🐜 Ant Stepper", "🧹 Broom Rider",
    "🪀 Yo-Yo Luck", "🕷️ Cobweb Collector", "🧊 Slipped on Ice", "💸 Empty Pockets"
]
LUCKY_NAMES += [
    "🍀 Four-Leaf Finder","🐟 Fish Catcher","🎲 Dice Roller","🌈 Cloud Spotter",
    "🕊️ Gentle Breeze","🥠 Fortune Cookie Reader","🌊 Wave Rider","🕯️ Candle Light",
    "🌻 Sunflower Smiler","🧸 Lucky Teddy","🍫 Chocolate Bar Finder","🦉 Night Owl",
    "🛶 Smooth Sailor","🥂 Toast Holder","🎯 Bullseye Shooter","🪁 Kite Flyer",
    "🌼 Daisy Chain","🧩 Puzzle Solver","🐚 Seashell Collector","🌌 Star Gazer"
]
LUCKY_NAMES += [
    "🪄 Charm Holder","🦊 Fox Trickster","🕹️ Game Winner","💎 Crystal Carrier","🦄 Unicorn Touched",
    "🧚 Fairy Blessed","🌟 Shooting Star Spotter","🎻 Melody Keeper","🪙 Golden Coin Finder",
    "🌸 Sakura Whisper","🐉 Dragon’s Glimpse","🦅 Sky Rider","🪶 Feather Blessed","🌙 Moonlight Dancer",
    "🔥 Ember Keeper","🕊️ Peace Bringer","🧜 Siren’s Gift","🦋 Butterfly Touch","🕰️ Timeless One","🎐 Wind Chime Holder"
]
LUCKY_NAMES += [
    "🧿 Evil Eye Breaker","🦁 Lion’s Courage","🪞 Mirror Fate Holder","⚡ Thunder Spark","🌪️ Storm Rider",
    "🪂 Sky Diver","🧙 Wizard’s Blessing","🌋 Volcano Survivor","🏹 Archer of Fate","🧝 Elf’s Chosen",
    "🌠 Comet Rider","🪐 Cosmic Traveler","🧩 Destiny Solver","🕊️ Celestial Keeper","🦢 Swan’s Grace",
    "🧭 True North Seeker","🌄 Sunrise Holder","🌊 Ocean Whisperer","🪶 Phoenix Feather","🦅 Eagle’s Blessing"
]
LUCKY_NAMES += [
    "🧬 Fate Weaver","🐉 Dragon’s Chosen","🦄 Eternal Unicorn","🧚 Starlight Keeper","🕊️ Divine Messenger",
    "🌀 Infinity Spinner","🧿 Arcane Relic Holder","🪙 Treasure Keeper","🌌 Galaxy Blessed","🕰️ Timewoven Soul",
    "🌈 Rainbow Guardian","🦋 Ethereal Keeper","🧊 Frozen Aurora Bearer","⚡ Volt Resonant One","🪞 Phantom Mirror",
    "🕊️ Celestia Bloomed","👑 Divine Ascendant","🦄 Prismatic Deity","🐉 Draconic Eternal","🛸 Singularity Echo"
]
# pad/truncate to 100
if len(LUCKY_NAMES) < 100:
    last = LUCKY_NAMES[-1] if LUCKY_NAMES else "Lucky One"
    while len(LUCKY_NAMES) < 100:
        LUCKY_NAMES.append(last)
elif len(LUCKY_NAMES) > 100:
    LUCKY_NAMES = LUCKY_NAMES[:100]


# ---------- Helpers - DB wrappers ----------
def get_user_total_waifus(user_id: int) -> int:
    try:
        db.cursor.execute("SELECT SUM(amount) FROM user_waifus WHERE user_id = ?", (user_id,))
        row = db.cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0

def get_user_balance(user_id: int) -> int:
    try:
        db.cursor.execute("SELECT daily_crystals, weekly_crystals, monthly_crystals, given_crystals FROM users WHERE user_id = ?", (user_id,))
        row = db.cursor.fetchone()
        if not row:
            return 0
        daily, weekly, monthly, given = (int(v or 0) for v in row)
        return daily + weekly + monthly + given
    except Exception:
        return 0

def get_user_profile(user_id: int):
    try:
        db.cursor.execute("SELECT total_collected, progress FROM user_profiles WHERE user_id = ?", (user_id,))
        row = db.cursor.fetchone()
        if row:
            return int(row[0] or 0), int(row[1] or 0)
    except Exception:
        pass
    return None

async def async_get_user_display_name(client, user_id: int) -> str:
    try:
        u = await client.get_users(user_id)
        name = getattr(u, "first_name", "") or ""
        if getattr(u, "username", None):
            return f"{name} (@{u.username})"
        return name.strip() or f"User {user_id}"
    except Exception:
        return f"User {user_id}"


# ---------- Tier mapping ----------
def map_collection_tier(total: int) -> str:
    for lo, hi, label in COLLECTION_TIERS:
        if lo <= total <= hi:
            return label
    return COLLECTION_TIERS[-1][2]


# ---------- Lucky rank calculation ----------
def compute_luck_score(user_id: int, total_waifus: int = None) -> int:
    if total_waifus is None:
        total_waifus = get_user_total_waifus(user_id)
    if getattr(Config, "OWNER_ID", None) and int(user_id) == int(getattr(Config, "OWNER_ID")):
        return 100
    owner_ids = getattr(Config, "OWNER_IDS", []) or []
    if owner_ids and int(user_id) in [int(x) for x in owner_ids]:
        return 100
    profile = get_user_profile(user_id)
    progress = profile[1] if profile else 0
    part_a = min(50.0, float(total_waifus) / 30.0)
    part_b = min(50.0, float(progress) * 0.5)
    score = int(min(100, math.floor(part_a + part_b)))
    return max(1, score)

def luck_name_from_score(score: int) -> str:
    idx = max(1, min(100, int(score))) - 1
    return LUCKY_NAMES[idx]


# ---------- /collectionvalue handler ----------
@app.on_message(filters.command("collectionvalue"))
async def collectionvalue_cmd(client, message):
    user = message.from_user
    if not user:
        return
    uid = user.id
    total = get_user_total_waifus(uid)
    balance = get_user_balance(uid)
    profile = get_user_profile(uid)
    profile_total = profile[0] if profile else total
    progress = profile[1] if profile else 0
    tier_label = map_collection_tier(total)

    caption_lines = [
        f"🌸 Collection Worth Report 🌸",
        "",
        f"👤 {user.first_name} {(f'(@{user.username})' if getattr(user,'username',None) else '')}",
        f"📦 Total Waifus: {total}",
        f"💎 Total Balance: {balance} 💎",
        f"🏷️ Tier: {tier_label}",
        f"📈 Profile Total Collected: {profile_total}",
        f"🔋 Progress: {progress}%",
        "",
        f"✨ Keep collecting to climb the tiers!",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    ]
    caption = "\n".join(caption_lines)

    # attempt to fetch the user's profile photo (await)
    try:
        photos = await client.get_profile_photos(uid, limit=1)
        if photos and getattr(photos, "total_count", 0) and getattr(photos, "photos", None):
            # photos.photos is a list of Photo objects; pick first size's file_id
            file_id = photos.photos[0][0].file_id if photos.photos and photos.photos[0] else None
            if file_id:
                await client.send_photo(message.chat.id if message.chat else uid, file_id, caption=caption)
                return
    except Exception:
        pass

    await message.reply_text(caption)


# ---------- /luckyrank handler + leaderboard ----------
LEADERBOARD_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🏆 View Leaderboard", callback_data="luck:leader:1")]]
)

@app.on_message(filters.command("luckyrank"))
async def luckyrank_cmd(client, message):
    user = message.from_user
    if not user:
        return
    uid = user.id
    total = get_user_total_waifus(uid)
    score = compute_luck_score(uid, total)
    name = luck_name_from_score(score)
    profile = get_user_profile(uid)
    progress = profile[1] if profile else 0
    display_name = f"{user.first_name} {(f'(@{user.username})' if getattr(user,'username',None) else '')}"
    text = (
        f"🎲 Your Lucky Rank 🎲\n\n"
        f"👤 {display_name}\n"
        f"🔢 Rank (1-100): {score}\n"
        f"🏷️ Rank Name: {name}\n\n"
        f"📦 Total Waifus: {total}\n"
        f"📈 Progress: {progress}%\n\n"
        "Tap below to view the global leaderboard (top collectors by luck score)."
    )
    await message.reply_text(text, reply_markup=LEADERBOARD_KB)


# helper: compute users' luck scores (no await here)
def compute_all_users_luck():
    rows = []
    try:
        db.cursor.execute("SELECT user_id FROM users")
        users = [r[0] for r in db.cursor.fetchall()]
    except Exception:
        users = []
    res = []
    for uid in users:
        total = get_user_total_waifus(uid)
        score = compute_luck_score(uid, total)
        res.append((uid, score, total))
    res.sort(key=lambda t: (t[1], t[2]), reverse=True)
    return res

# leaderboard callback — await client.get_users properly
from pyrogram import enums
@app.on_callback_query(filters.regex(r"^luck:leader:(\d+)$"))
async def luck_leader_cb(client, callback):
    page = int(callback.matches[0].group(1))
    page = max(1, page)
    per_page = 10
    data = compute_all_users_luck()
    total_items = len(data)
    if total_items == 0:
        await callback.answer("No users found.", show_alert=True)
        return

    start = (page - 1) * per_page
    end = start + per_page
    page_items = data[start:end]

    lines = [f"🏆 Global Lucky Rank Leaderboard — Page {page}"]
    for i, (uid, score, total) in enumerate(page_items, start=start+1):
        try:
            u = await client.get_users(uid)
            if getattr(u, "username", None):
                uname = f"{getattr(u,'first_name','')} (@{u.username})"
            else:
                uname = f"{getattr(u,'first_name','') or 'User'} ({uid})"
        except Exception:
            uname = f"User {uid}"
        name = luck_name_from_score(score)
        lines.append(f"{i}. {uname} — {score}/100 — {name} — {total} waifus")

    kb = []
    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"luck:leader:{page-1}"))
    if end < total_items:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"luck:leader:{page+1}"))
    if nav_row:
        kb.append(nav_row)
    kb.append([InlineKeyboardButton("🔁 Refresh", callback_data=f"luck:leader:{page}")])
    kb.append([InlineKeyboardButton("❌ Close", callback_data="luck:close")])

    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        await callback.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb))
    await callback.answer()

@app.on_callback_query(filters.regex(r"^luck:close$"))
async def luck_close_cb(client, callback):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()
