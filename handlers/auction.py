# handlers/auction.py
from main import app
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from database import Database
import threading
import asyncio

db = Database()

# Auction timing (in seconds)
BID_TIMEOUT_SECONDS = 10

# --- Create tables (safe) ---
db.cursor.execute("""
CREATE TABLE IF NOT EXISTS auctions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    waifu_id INTEGER,
    seller_id INTEGER,
    start_iso TEXT,
    end_iso TEXT,
    min_price INTEGER,
    status TEXT DEFAULT 'active',
    winner_id INTEGER,
    final_price INTEGER,
    transferred INTEGER DEFAULT 0,
    waifu_name TEXT,
    waifu_anime TEXT,
    waifu_rarity TEXT,
    waifu_media_type TEXT,
    waifu_media_file TEXT,
    waifu_media_file_id TEXT
)
""")
db.cursor.execute("""
CREATE TABLE IF NOT EXISTS auction_bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auction_id INTEGER,
    bidder_id INTEGER,
    amount INTEGER,
    bid_iso TEXT
)
""")
db.conn.commit()


# --- Helpers ---
def now_iso():
    return datetime.now().isoformat()


def iso_to_dt(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        try:
            return datetime.strptime(s.split("T")[0], "%Y-%m-%d")
        except Exception:
            return None


def _maybe_await_send(client, user_id, text):
    """
    Safely schedule or run client.send_message:
    - If an asyncio event loop is running, schedule the coroutine.
    - Otherwise run asyncio.run() to send (best-effort).
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(client.send_message(user_id, text))
    except RuntimeError:
        # No running loop in this thread — run send synchronously (best-effort)
        try:
            asyncio.run(client.send_message(user_id, text))
        except Exception:
            pass


def finalize_expired_auctions(client=None):
    """
    Finalize auctions whose end_iso <= now.
    - If no bids: return waifu to seller, mark finished.
    - If bids: winner already had funds reserved when bidding; credit seller and transfer card.
    """
    now = datetime.now().isoformat()
    db.cursor.execute("SELECT id FROM auctions WHERE status = 'active' AND end_iso <= ?", (now,))
    rows = db.cursor.fetchall()
    for (aid,) in rows:
        # highest bid (if any)
        db.cursor.execute(
            "SELECT bidder_id, amount FROM auction_bids WHERE auction_id = ? ORDER BY amount DESC, bid_iso ASC LIMIT 1",
            (aid,))
        top = db.cursor.fetchone()

        db.cursor.execute(
            "SELECT waifu_id, seller_id, waifu_name FROM auctions WHERE id = ?",
            (aid,))
        arow = db.cursor.fetchone()
        if not arow:
            db.cursor.execute("UPDATE auctions SET status = 'finished' WHERE id = ?", (aid,))
            db.conn.commit()
            continue

        waifu_id, seller_id, waifu_name = arow

        if not top:
            # no bids -> return card to seller
            db.cursor.execute("SELECT amount FROM user_waifus WHERE user_id = ? AND waifu_id = ?", (seller_id, waifu_id))
            r = db.cursor.fetchone()
            if r:
                db.cursor.execute("UPDATE user_waifus SET amount = amount + 1 WHERE user_id = ? AND waifu_id = ?",
                                  (seller_id, waifu_id))
            else:
                db.cursor.execute("INSERT INTO user_waifus (user_id, waifu_id, amount) VALUES (?, ?, 1)",
                                  (seller_id, waifu_id))
            db.cursor.execute("UPDATE auctions SET status = 'finished', transferred = 1 WHERE id = ?", (aid,))
            db.conn.commit()
            db.log_event("auction_unsold", user_id=seller_id, details=f"auction_id={aid} waifu_id={waifu_id}")
            if client:
                _maybe_await_send(client, seller_id,
                                  f"📦 Your auction #{aid} for **{waifu_name}** ended with no bids. The card has been returned to your inventory.")
            continue

        # there is a top bidder (winner)
        winner_id, final_price = top

        # Ensure winner has the card (idempotent)
        db.cursor.execute("SELECT amount FROM user_waifus WHERE user_id = ? AND waifu_id = ?", (winner_id, waifu_id))
        r = db.cursor.fetchone()
        if r:
            # if transferred flag already set, skip increment
            transferred_flag = db.cursor.execute("SELECT transferred FROM auctions WHERE id = ?", (aid,)).fetchone()[0]
            if not transferred_flag:
                db.cursor.execute("UPDATE user_waifus SET amount = amount + 1 WHERE user_id = ? AND waifu_id = ?",
                                  (winner_id, waifu_id))
        else:
            db.cursor.execute("INSERT INTO user_waifus (user_id, waifu_id, amount) VALUES (?, ?, 1)",
                              (winner_id, waifu_id))

        # credit seller if not already credited
        db.cursor.execute("SELECT transferred FROM auctions WHERE id = ?", (aid,))
        transferred_flag = db.cursor.fetchone()[0]
        if not transferred_flag:
            # credit seller using existing method (winner funds were already deducted at bid time)
            db.add_crystals(seller_id, given=final_price)
            db.log_event("auction_sold", user_id=seller_id, details=f"auction_id={aid} waifu_id={waifu_id} earned={final_price}")

        # mark auction finished and transferred
        db.cursor.execute("UPDATE auctions SET status = 'finished', winner_id = ?, final_price = ?, transferred = 1 WHERE id = ?",
                          (winner_id, final_price, aid))
        db.conn.commit()

        # notify winner and seller
        if client:
            _maybe_await_send(client, winner_id,
                              f"🏷️ You won auction #{aid} for **{waifu_name}** with {final_price:,} 💎! The card has been added to your inventory.")
            _maybe_await_send(client, seller_id,
                              f"💰 Your auction #{aid} for **{waifu_name}** sold for {final_price:,} 💎. Crystals have been added to your balance.")


def finalize_expired_auctions_sync(client=None):
    try:
        finalize_expired_auctions(client)
    except Exception:
        pass


# --- Commands ---
@app.on_message(filters.command("auction"))
async def auction_handler(client, message):
    """
    /auction [waifu_id] [min_price] -> start auction for 1 copy of waifu_id
    """
    finalize_expired_auctions_sync(client)

    user_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply_text("Usage: /auction [waifu_id] [min_price]\nExample: /auction 12 50000")

    try:
        waifu_id = int(parts[1])
        min_price = int(parts[2].replace(",", ""))
    except:
        return await message.reply_text("Invalid waifu id or min_price.")

    # check ownership
    db.cursor.execute("SELECT amount FROM user_waifus WHERE user_id = ? AND waifu_id = ?", (user_id, waifu_id))
    row = db.cursor.fetchone()
    if not row or row[0] <= 0:
        return await message.reply_text("You don't own that waifu or have 0 amount.")

    # reserve one copy (decrement by 1)
    if row[0] > 1:
        db.cursor.execute("UPDATE user_waifus SET amount = amount - 1 WHERE user_id = ? AND waifu_id = ?",
                          (user_id, waifu_id))
    else:
        db.cursor.execute("DELETE FROM user_waifus WHERE user_id = ? AND waifu_id = ?", (user_id, waifu_id))
    db.conn.commit()

    # fetch waifu snapshot
    db.cursor.execute("SELECT name, anime, rarity, media_type, media_file, media_file_id FROM waifu_cards WHERE id = ?",
                      (waifu_id,))
    w = db.cursor.fetchone()
    if not w:
        # rollback reserve (best-effort)
        db.cursor.execute("INSERT OR REPLACE INTO user_waifus (user_id, waifu_id, amount) VALUES (?, ?, COALESCE((SELECT amount FROM user_waifus WHERE user_id=? AND waifu_id=?), 0)+1))",
                          (user_id, waifu_id, user_id, waifu_id))
        db.conn.commit()
        return await message.reply_text("Waifu card not found in database.")

    name, anime, rarity, media_type, media_file, media_file_id = w

    # create auction
    start = datetime.now()
    end = start + timedelta(seconds=BID_TIMEOUT_SECONDS)
    db.cursor.execute("""
        INSERT INTO auctions (
            waifu_id, seller_id, start_iso, end_iso, min_price, waifu_name, waifu_anime, waifu_rarity, waifu_media_type, waifu_media_file, waifu_media_file_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (waifu_id, user_id, start.isoformat(), end.isoformat(), min_price, name, anime, rarity, media_type, media_file, media_file_id))
    db.conn.commit()
    auction_id = db.cursor.lastrowid

    # send preview
    caption = (
        f"🔨 Auction #{auction_id} started by {message.from_user.first_name or message.from_user.username}\n"
        f"📛 ID: {waifu_id}\n"
        f"💠 Name: {name}\n"
        f"🎬 Anime: {anime or '—'}\n"
        f"✨ Rarity: {rarity or '—'}\n"
        f"💰 Min price: {min_price:,} 💎\n"
        f"⏱️ Current timeout: {BID_TIMEOUT_SECONDS}s of silence (each bid resets timer)\n\n"
        f"Use /bid {auction_id} [amount] to place a bid."
    )

    media = media_file_id or media_file
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔎 Auction Info", callback_data=f"auction_info:{auction_id}")]])
    try:
        if media_type == "video" and media:
            await client.send_video(message.chat.id, media, caption=caption, reply_markup=kb)
        elif media:
            await client.send_photo(message.chat.id, media, caption=caption, reply_markup=kb)
        else:
            await client.send_message(message.chat.id, caption, reply_markup=kb)
    except:
        await message.reply_text(caption, reply_markup=kb)

    db.log_event("auction_started", user_id=user_id, details=f"auction_id={auction_id} waifu_id={waifu_id} min_price={min_price}")


@app.on_message(filters.command("bid"))
async def bid_handler(client, message):
    """
    /bid [auction_id] [amount]
    """
    finalize_expired_auctions_sync(client)

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply_text("Usage: /bid [auction_id] [amount]")

    try:
        auction_id = int(parts[1])
        amount = int(parts[2].replace(",", ""))
    except:
        return await message.reply_text("Invalid auction id or amount.")

    user_id = message.from_user.id

    # fetch auction
    db.cursor.execute("SELECT id, waifu_name, seller_id, end_iso, min_price, status FROM auctions WHERE id = ?", (auction_id,))
    a = db.cursor.fetchone()
    if not a:
        return await message.reply_text("Auction not found.")
    aid, waifu_name, seller_id, end_iso, min_price, status = a
    if status != "active":
        return await message.reply_text("This auction is not active anymore.")

    end_dt = iso_to_dt(end_iso)
    if end_dt and datetime.now() >= end_dt:
        finalize_expired_auctions_sync(client)
        return await message.reply_text("Auction has just ended; no more bids accepted.")

    # check user's available funds
    daily, weekly, monthly, total, last_claim, given = db.get_crystals(user_id)

    # find current highest bid for this auction
    db.cursor.execute("SELECT bidder_id, amount FROM auction_bids WHERE auction_id = ? ORDER BY amount DESC, bid_iso ASC LIMIT 1", (auction_id,))
    current = db.cursor.fetchone()

    # If current highest is the same user, they already have reserved curr_amount; allow using that reserved amount
    curr_amount = current[1] if current else 0
    curr_bidder = current[0] if current else None

    if curr_bidder == user_id:
        # available funds include their existing reserved bid
        available = total + curr_amount
    else:
        available = total

    if available < amount:
        return await message.reply_text("You don't have enough crystals to place that bid (consider your existing reserved bid).")

    # validate against current highest / min_price
    if current:
        if amount <= curr_amount:
            return await message.reply_text(f"Your bid must be higher than the current highest bid ({curr_amount:,} 💎).")
    else:
        if amount < min_price:
            return await message.reply_text(f"Your bid must be at least the minimum price ({min_price:,} 💎).")

    # place bid & handle funds:
    # - if bidder is raising their own bid -> deduct only the difference
    # - otherwise deduct full amount from new bidder, and refund the previous highest bidder (if any)
    bid_iso = datetime.now().isoformat()

    try:
        if curr_bidder == user_id:
            # user is increasing their own bid; deduct only the delta
            delta = amount - curr_amount
            if delta > 0:
                db.add_crystals(user_id, given=-delta)  # deduct delta from user's balance
        else:
            # deduct full amount from bidder
            db.add_crystals(user_id, given=-amount)
            # refund previous highest if exists and different user
            if current and curr_bidder:
                # refund curr_amount to previous highest bidder
                db.add_crystals(curr_bidder, given=curr_amount)
                # log refund
                db.log_event("auction_refund", user_id=curr_bidder, details=f"auction_id={auction_id} refunded={curr_amount}")

        # insert bid record (we keep history)
        db.cursor.execute("INSERT INTO auction_bids (auction_id, bidder_id, amount, bid_iso) VALUES (?, ?, ?, ?)",
                          (auction_id, user_id, amount, bid_iso))
        db.conn.commit()

        # extend auction end time by BID_TIMEOUT_SECONDS from now
        new_end = datetime.now() + timedelta(seconds=BID_TIMEOUT_SECONDS)
        db.cursor.execute("UPDATE auctions SET end_iso = ? WHERE id = ?", (new_end.isoformat(), auction_id))
        db.conn.commit()

        # notify previous highest bidder (if different user)
        if current and curr_bidder and curr_bidder != user_id:
            try:
                await client.send_message(curr_bidder,
                                          f"🔔 You have been outbid on auction #{auction_id} ({waifu_name}). New highest: {amount:,} 💎")
            except:
                pass

        db.log_event("auction_bid", user_id=user_id, details=f"auction_id={auction_id} amount={amount}")

    except Exception as e:
        # in case of failure trying to deduct/insert, attempt to rollback best-effort by refunding user if needed
        # (since db operations are not transactional here, this is best-effort)
        return await message.reply_text("Failed to place bid due to an internal error. Try again.")

    await message.reply_text(f"✅ Bid placed: {amount:,} 💎 on auction #{auction_id}. Timer extended by {BID_TIMEOUT_SECONDS}s.")


@app.on_message(filters.command("auctions"))
async def auctions_list_handler(client, message):
    finalize_expired_auctions_sync(client)

    db.cursor.execute("SELECT id, waifu_name, min_price, end_iso FROM auctions WHERE status = 'active' ORDER BY start_iso DESC LIMIT 20")
    rows = db.cursor.fetchall()
    if not rows:
        return await message.reply_text("No active auctions right now.")

    lines = []
    for aid, name, minp, end_iso in rows:
        end_dt = iso_to_dt(end_iso)
        remaining = ""
        if end_dt:
            rem = end_dt - datetime.now()
            secs = int(rem.total_seconds())
            if secs > 0:
                remaining = f"{secs}s remaining"
            else:
                remaining = "ending soon"
        lines.append(f"#{aid} — {name} — min {minp:,} 💎 — {remaining}")

    await message.reply_text("🔨 Active Auctions:\n\n" + "\n".join(lines))


@app.on_message(filters.command("auction_status"))
async def auction_status_handler(client, message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Usage: /auction_status [auction_id]")
    try:
        aid = int(parts[1])
    except:
        return await message.reply_text("Invalid auction id.")
    finalize_expired_auctions_sync(client)

    db.cursor.execute(
        "SELECT id, waifu_id, waifu_name, waifu_anime, waifu_rarity, waifu_media_type, waifu_media_file, waifu_media_file_id, min_price, end_iso, status FROM auctions WHERE id = ?",
        (aid,))
    a = db.cursor.fetchone()
    if not a:
        return await message.reply_text("Auction not found.")
    (aid, wid, name, anime, rarity, mtype, mfile, mfileid, min_price, end_iso, status) = a
    caption = (
        f"🔨 Auction #{aid}\n"
        f"📛 Waifu ID: {wid}\n"
        f"💠 Name: {name}\n"
        f"🎬 Anime: {anime}\n"
        f"✨ Rarity: {rarity}\n"
        f"💰 Min price: {min_price:,} 💎\n"
        f"Status: {status}\n"
    )
    db.cursor.execute("SELECT bidder_id, amount FROM auction_bids WHERE auction_id = ? ORDER BY amount DESC LIMIT 5", (aid,))
    bids = db.cursor.fetchall()
    if bids:
        caption += "\nTop bids:\n"
        for i, (uid, amt) in enumerate(bids, 1):
            db.cursor.execute("SELECT username, first_name FROM users WHERE user_id = ?", (uid,))
            u = db.cursor.fetchone()
            label = f"@{u[0]}" if u and u[0] else (u[1] if u and u[1] else str(uid))
            caption += f"{i}. {label} — {amt:,} 💎\n"
    else:
        caption += "\nNo bids yet.\n"

    media = mfileid or mfile
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Refresh", callback_data=f"auction_info:{aid}")]])
    try:
        if mtype == "video" and media:
            await client.send_video(message.chat.id, media, caption=caption, reply_markup=kb)
        elif media:
            await client.send_photo(message.chat.id, media, caption=caption, reply_markup=kb)
        else:
            await message.reply_text(caption, reply_markup=kb)
    except:
        await message.reply_text(caption, reply_markup=kb)


# Callback: show auction info or finalize if ended
@app.on_callback_query(filters.regex(r"^auction_info:"))
async def auction_info_cb(client, callback):
    aid = int(callback.data.split(":")[1])
    finalize_expired_auctions_sync(client)

    db.cursor.execute(
        "SELECT id, waifu_id, waifu_name, waifu_anime, waifu_rarity, waifu_media_type, waifu_media_file, waifu_media_file_id, min_price, end_iso, status, winner_id, final_price FROM auctions WHERE id = ?",
        (aid,))
    a = db.cursor.fetchone()
    if not a:
        await callback.answer("Auction not found.", show_alert=True)
        return
    (aid, wid, name, anime, rarity, mtype, mfile, mfileid, min_price, end_iso, status, winner_id, final_price) = a

    caption = (
        f"🔨 Auction #{aid}\n"
        f"📛 Waifu ID: {wid}\n"
        f"💠 Name: {name}\n"
        f"🎬 Anime: {anime}\n"
        f"✨ Rarity: {rarity}\n"
        f"💰 Min price: {min_price:,} 💎\n"
        f"Status: {status}\n"
    )
    if status == "finished":
        if winner_id:
            db.cursor.execute("SELECT username, first_name FROM users WHERE user_id = ?", (winner_id,))
            u = db.cursor.fetchone()
            label = f"@{u[0]}" if u and u[0] else (u[1] if u and u[1] else str(winner_id))
            caption += f"\n🏁 Winner: {label} — {final_price:,} 💎"
        else:
            caption += "\nNo winner (unsold)."

    buttons = []
    if status == "finished":
        buttons.append([InlineKeyboardButton("📥 Add to Inventory (winner)", callback_data=f"auction_claim:{aid}"),
                        InlineKeyboardButton("💎 Credit Seller", callback_data=f"auction_credit:{aid}")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="auction_close")])

    media = mfileid or mfile
    try:
        if mtype == "video" and media:
            await client.send_video(callback.message.chat.id, media, caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
        elif media:
            await client.send_photo(callback.message.chat.id, media, caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await callback.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(buttons))
    except:
        await callback.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(buttons))
    await callback.answer()


# Manual claim: idempotent
@app.on_callback_query(filters.regex(r"^auction_claim:"))
async def auction_claim_cb(client, callback):
    aid = int(callback.data.split(":")[1])
    db.cursor.execute("SELECT status, waifu_id, winner_id, transferred FROM auctions WHERE id = ?", (aid,))
    row = db.cursor.fetchone()
    if not row:
        return await callback.answer("Auction not found.", show_alert=True)
    status, waifu_id, winner_id, transferred = row
    if status != "finished":
        return await callback.answer("Auction not finished yet.", show_alert=True)
    if not winner_id:
        return await callback.answer("No winner for this auction.", show_alert=True)

    if not transferred:
        db.cursor.execute("SELECT amount FROM user_waifus WHERE user_id = ? AND waifu_id = ?", (winner_id, waifu_id))
        r = db.cursor.fetchone()
        if r:
            db.cursor.execute("UPDATE user_waifus SET amount = amount + 1 WHERE user_id = ? AND waifu_id = ?",
                              (winner_id, waifu_id))
        else:
            db.cursor.execute("INSERT INTO user_waifus (user_id, waifu_id, amount) VALUES (?, ?, 1)",
                              (winner_id, waifu_id))
        db.cursor.execute("UPDATE auctions SET transferred = 1 WHERE id = ?", (aid,))
        db.conn.commit()
        db.log_event("auction_claim_manual", user_id=winner_id, details=f"auction_id={aid}")
        await callback.answer("✅ Card added to winner's inventory.")
    else:
        await callback.answer("✅ Already transferred.")


@app.on_callback_query(filters.regex(r"^auction_credit:"))
async def auction_credit_cb(client, callback):
    aid = int(callback.data.split(":")[1])
    db.cursor.execute("SELECT status, seller_id, final_price, transferred FROM auctions WHERE id = ?", (aid,))
    row = db.cursor.fetchone()
    if not row:
        return await callback.answer("Auction not found.", show_alert=True)
    status, seller_id, final_price, transferred = row
    if status != "finished":
        return await callback.answer("Auction not finished yet.", show_alert=True)
    if transferred:
        await callback.answer("✅ Seller already credited (or transfer done).")
        return
    if not final_price:
        return await callback.answer("No final price recorded.", show_alert=True)

    db.add_crystals(seller_id, given=final_price)
    db.cursor.execute("UPDATE auctions SET transferred = 1 WHERE id = ?", (aid,))
    db.conn.commit()
    db.log_event("auction_credit_manual", user_id=seller_id, details=f"auction_id={aid} amount={final_price}")
    await callback.answer("💎 Seller credited.")


@app.on_callback_query(filters.regex(r"^auction_close"))
async def auction_close_cb(client, callback):
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()


# Try a small background finalize at startup (non-blocking)
def _background_finalize(client):
    try:
        finalize_expired_auctions(client)
    except:
        pass

threading.Thread(target=_background_finalize, args=(app,), daemon=True).start()
