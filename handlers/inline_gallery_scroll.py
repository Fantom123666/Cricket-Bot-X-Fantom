# handlers/inline_gallery_scroll.py
import sqlite3
from pyrogram import filters
from pyrogram.types import (
    InlineQuery,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InputTextMessageContent
)
from config import app

DB_PATH = "waifu_bot.db"

def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def fetch_waifu_cards(search: str = "", limit: int = 50, offset: int = 0):
    conn = _conn()
    cur = conn.cursor()
    if search:
        q = f"%{search.lower()}%"
        cur.execute(
            "SELECT id, name, anime, rarity, media_type, media_file FROM waifu_cards "
            "WHERE LOWER(name) LIKE ? OR LOWER(anime) LIKE ? ORDER BY id ASC LIMIT ? OFFSET ?",
            (q, q, limit, offset)
        )
    else:
        cur.execute(
            "SELECT id, name, anime, rarity, media_type, media_file FROM waifu_cards ORDER BY id ASC LIMIT ? OFFSET ?",
            (limit, offset)
        )
    rows = cur.fetchall()
    conn.close()
    return rows

@app.on_inline_query()
async def inline_waifu_gallery(client, iq: InlineQuery):
    query = (iq.query or "").strip()
    offset = int(iq.offset or 0)
    limit = 50
    cards = fetch_waifu_cards(query, limit=limit, offset=offset)

    if not cards:
        await iq.answer(
            [],
            switch_pm_text="No waifus found 😢",
            switch_pm_parameter="start",
            cache_time=30
        )
        return

    results = []
    for wid, name, anime, rarity, media_type, media_file in cards:
        caption = f"🆔 ID: {wid}\n👤 Name: {name}\n🤝 Anime: {anime}\n❄️ Rarity: {rarity}"

        try:
            if media_type in ("photo", "image"):
                results.append(
                    InlineQueryResultCachedPhoto(
                        id=str(wid),
                        photo_file_id=media_file,
                        caption=caption    # ✅ send photo with caption
                    )
                )
            elif media_type in ("video", "animation"):
                results.append(
                    InlineQueryResultCachedVideo(
                        id=str(wid),
                        video_file_id=media_file,
                        title=f"{name} [{rarity}]",
                        caption=caption    # ✅ send video with caption
                    )
                )
        except Exception as e:
            print(f"[inline_gallery_scroll] error creating result for {name}: {e}")

    next_offset = str(offset + limit) if len(cards) == limit else ""

    await iq.answer(
        results,
        cache_time=30,
        is_personal=True,
        next_offset=next_offset
    )
