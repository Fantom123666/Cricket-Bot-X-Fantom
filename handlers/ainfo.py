# handlers/ainfo.py
"""
/ainfo <anime name>
Searches anime details on the web (Jikan / MyAnimeList) and returns:
 - cover image
 - title(s)
 - type, episodes, status, aired, duration
 - score, rank, popularity, members, favorites
 - studios, producers, source, genres, themes
 - synopsis (truncated)
Works in groups and private chats.
"""

import aiohttp
import asyncio
from textwrap import shorten

from pyrogram import filters
from pyrogram.types import Message
from config import app

JIKAN_SEARCH_URL = "https://api.jikan.moe/v4/anime"
JIKAN_ANIME_BY_ID = "https://api.jikan.moe/v4/anime/{}"  # append /full if needed
CAPTION_MAX = 1024  # Telegram caption practical limit

# safe shortener for synopsis
def _shorten(text: str, length: int = 750) -> str:
    if not text:
        return "—"
    # remove excessive whitespace
    t = " ".join(text.split())
    # shorten preserving words
    return shorten(t, width=length, placeholder="...")

def _join_names(items, key="name"):
    if not items:
        return "—"
    return ", ".join(i.get(key, "—") for i in items if i)

async def _jikan_get(session: aiohttp.ClientSession, url: str, params: dict = None):
    headers = {"Accept": "application/json"}
    try:
        async with session.get(url, params=params, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                return await resp.json()
            # bubble up useful errors
            return {"error": True, "status": resp.status, "text": await resp.text()}
    except asyncio.TimeoutError:
        return {"error": True, "status": "timeout"}
    except Exception as e:
        return {"error": True, "exception": str(e)}


@app.on_message(filters.command("info"))
async def anime_info_handler(client, message: Message):
    # Parse query
    parts = (message.text or "").strip().split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await message.reply_text("❗ Usage: `/info <anime name>`\nExample: `/info attack on titan`")
        return
    query = parts[1].strip()

    # Inform user we're searching (small quick reply)
    try:
        status_msg = await message.reply_text(f"🔎 Searching for **{query}**...", parse_mode="markdown")
    except Exception:
        status_msg = None

    async with aiohttp.ClientSession() as session:
        # 1) search for the anime (best match)
        search_resp = await _jikan_get(session, JIKAN_SEARCH_URL, params={"q": query, "limit": 1})
        if not search_resp or search_resp.get("error"):
            # handle common API errors
            err = search_resp.get("status") if isinstance(search_resp, dict) else "unknown"
            if status_msg:
                try:
                    await status_msg.edit_text(f"❌ Search failed (status: {err}). Try again later.")
                except Exception:
                    pass
            else:
                await message.reply_text(f"❌ Search failed (status: {err}). Try again later.")
            return

        data = search_resp.get("data")
        if not data:
            if status_msg:
                try:
                    await status_msg.edit_text("❌ No results found for that query.")
                except Exception:
                    pass
            else:
                await message.reply_text("❌ No results found for that query.")
            return

        anime = data[0]
        anime_id = anime.get("mal_id")

        # 2) fetch full anime details (more fields)
        details_resp = await _jikan_get(session, JIKAN_ANIME_BY_ID.format(anime_id))
        if not details_resp or details_resp.get("error"):
            # fallback: we'll use the search result if details failed
            details = anime
        else:
            details = details_resp.get("data") or anime

    # Build info fields (safe access)
    title = details.get("title") or details.get("title_english") or "—"
    title_jp = details.get("title_japanese") or "—"
    title_english = details.get("title_english") or "—"

    type_ = details.get("type") or "—"
    episodes = details.get("episodes") if details.get("episodes") is not None else "—"
    status = details.get("status") or "—"

    aired = "—"
    aired_info = details.get("aired")
    if aired_info:
        aired = aired_info.get("string") or "—"

    duration = details.get("duration") or "—"
    rating = details.get("rating") or "—"
    source = details.get("source") or "—"
    season = details.get("season") or "—"
    year = details.get("year") or "—"

    score = details.get("score") if details.get("score") is not None else "—"
    scored_by = details.get("scored_by") if details.get("scored_by") is not None else "—"
    rank = details.get("rank") if details.get("rank") is not None else "—"
    popularity = details.get("popularity") if details.get("popularity") is not None else "—"
    members = details.get("members") if details.get("members") is not None else "—"
    favorites = details.get("favorites") if details.get("favorites") is not None else "—"

    # producers / studios / licensors / genres / themes
    studios = _join_names(details.get("studios", []))
    producers = _join_names(details.get("producers", []))
    licensors = _join_names(details.get("licensors", []))
    genres = _join_names(details.get("genres", []))
    themes = _join_names(details.get("themes", []))
    demographics = _join_names(details.get("demographics", []))

    # synopsis
    synopsis = _shorten(details.get("synopsis") or anime.get("synopsis") or "—", 900)

    # image url (try best available)
    images = details.get("images") or {}
    image_url = None
    # Jikan v4 structure: images.jpg.large_image_url
    if isinstance(images, dict):
        try:
            jpg = images.get("jpg") or images.get("image_url") or {}
            if isinstance(jpg, dict):
                image_url = jpg.get("large_image_url") or jpg.get("image_url") or None
        except Exception:
            image_url = None

    # fallback to search result image
    if not image_url:
        image_url = anime.get("images", {}).get("jpg", {}).get("large_image_url") or anime.get("images", {}).get("jpg", {}).get("image_url")

    # Build caption (try keep under Telegram caption limit)
    caption_lines = [
        f"🎴 *{title}*",
        f"• _English:_ {title_english}",
        f"• _Japanese:_ {title_jp}",
        "",
        f"*Type:* {type_}    *Episodes:* {episodes}    *Status:* {status}",
        f"*Aired:* {aired}",
        f"*Duration:* {duration}    *Rating:* {rating}",
        f"*Source:* {source}    *Season/Year:* {season or '-'} / {year or '-'}",
        "",
        f"*Score:* {score} ({scored_by} votes)    *Rank:* {rank}    *Popularity:* {popularity}",
        f"*Members:* {members}    *Favorites:* {favorites}",
        "",
        f"*Studios:* {studios}",
        f"*Producers:* {producers}",
        f"*Licensors:* {licensors}",
        f"*Genres:* {genres}",
        f"*Themes:* {themes}",
        f"*Demographics:* {demographics}",
        "",
        f"*Synopsis:*\n{synopsis}"
    ]
    caption = "\n".join(line for line in caption_lines if line is not None)

    # If caption too long for photo, send image then long text separately
    try:
        if image_url:
            if len(caption) <= CAPTION_MAX:
                await message.reply_photo(image_url, caption=caption, parse_mode="markdown")
            else:
                await message.reply_photo(image_url, caption=f"🎴 *{title}*", parse_mode="markdown")
                await message.reply_text(caption, parse_mode="markdown")
        else:
            await message.reply_text(caption, parse_mode="markdown")
    except Exception:
        # Last resort: send a plain text reply with a short summary and fallback image url if any
        fallback = [
            f"{title} ({type_}, eps: {episodes})",
            f"Aired: {aired}",
            f"Score: {score}    Rank: {rank}",
            "",
            f"Synopsis:\n{synopsis}",
        ]
        if image_url:
            fallback.append(f"\nImage: {image_url}")
        await message.reply_text("\n".join(fallback))

    # clean up: delete status message if exists
    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass
