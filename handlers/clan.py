# handlers/clan.py
from main import app
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta, date
from database import Database
import random

db = Database()

# ----------------- DB tables creation (safe) -----------------
db.cursor.execute("""
CREATE TABLE IF NOT EXISTS clans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clan_id TEXT UNIQUE,
    name TEXT,
    owner_id INTEGER,
    created_at TEXT,
    points INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    bank INTEGER DEFAULT 0
)
""")
db.cursor.execute("""
CREATE TABLE IF NOT EXISTS clan_members (
    clan_id INTEGER,
    user_id INTEGER,
    role TEXT DEFAULT 'member', -- 'owner' or 'member'
    joined_at TEXT,
    PRIMARY KEY (clan_id, user_id),
    FOREIGN KEY (clan_id) REFERENCES clans(id)
)
""")
db.cursor.execute("""
CREATE TABLE IF NOT EXISTS clan_wars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger_clan INTEGER,
    target_clan INTEGER,
    start_iso TEXT,
    end_iso TEXT,
    status TEXT DEFAULT 'active', -- active, finished
    challenger_points INTEGER DEFAULT 0,
    target_points INTEGER DEFAULT 0
)
""")
db.cursor.execute("""
CREATE TABLE IF NOT EXISTS clan_war_contrib (
    war_id INTEGER,
    clan_id INTEGER,
    user_id INTEGER,
    points INTEGER DEFAULT 0,
    PRIMARY KEY (war_id, user_id)
)
""")
db.cursor.execute("""
CREATE TABLE IF NOT EXISTS clan_withdrawals (
    clan_id INTEGER,
    user_id INTEGER,
    last_withdraw_iso TEXT,
    daily_withdraw_total INTEGER DEFAULT 0,
    daily_reset_date TEXT,
    PRIMARY KEY (clan_id, user_id)
)
""")
db.conn.commit()


# ----------------- Utility: Rank / Level -----------------
CLAN_LEVELS = [
    (0, "🌱 Seedling"),
    (500, "🍡 Sprout"),
    (1500, "🎀 Blooming"),
    (3000, "🌸 Guardian"),
    (5000, "🌟 Elite"),
    (7500, "🔥 Enchanted"),
    (10500, "🌙 Mystic"),
    (14000, "🦋 Ethereal"),
    (18000, "👑 Divine"),
    (23000, "💮 Supreme Master")
]


def clan_rank_from_points(points: int):
    level = 1
    rank_name = CLAN_LEVELS[0][1]
    for i, (threshold, name) in enumerate(CLAN_LEVELS):
        if points >= threshold:
            level = i + 1
            rank_name = name
    return level, rank_name


def gen_clan_code():
    # generate short unique clan code, try a few times
    for _ in range(10):
        code = str(random.randint(100000, 999999))
        db.cursor.execute("SELECT id FROM clans WHERE clan_id = ?", (code,))
        if not db.cursor.fetchone():
            return code
    # fallback to timestamp based
    return str(int(datetime.now().timestamp()))


def get_user_clan(user_id):
    db.cursor.execute("SELECT c.id, c.clan_id, c.name, c.owner_id, c.points, c.wins, c.losses, c.bank FROM clans c JOIN clan_members m ON c.id = m.clan_id WHERE m.user_id = ?", (user_id,))
    return db.cursor.fetchone()


# ----------------- /createclan -----------------
@app.on_message(filters.command("createclan"))
async def create_clan_handler(client, message):
    user_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply_text("Usage: /createclan [name]\nExample: /createclan SakuraLegion")

    clan_name = parts[1].strip()[:50]

    # check if user already in a clan
    if get_user_clan(user_id):
        return await message.reply_text("❌ You are already in a clan. Leave it first to create a new one (/leaveclan).")

    # create clan
    clan_code = gen_clan_code()
    now_iso = datetime.now().isoformat()
    db.cursor.execute("INSERT INTO clans (clan_id, name, owner_id, created_at) VALUES (?, ?, ?, ?)",
                      (clan_code, clan_name, user_id, now_iso))
    db.conn.commit()
    clan_db_id = db.cursor.lastrowid

    # add owner as member
    db.cursor.execute("INSERT INTO clan_members (clan_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
                      (clan_db_id, user_id, now_iso))
    db.conn.commit()

    # response card
    level, rank_name = clan_rank_from_points(0)
    text = (
        "🎉 Clan Created Successfully!\n\n"
        f"🏮 Clan Name: {clan_name}\n"
        f"🆔 Clan ID: {clan_code}\n"
        f"👑 Owner: {message.from_user.first_name or message.from_user.username}\n"
        f"👥 Members: 1/20\n"
        f"✨ Level: {level}\n"
        f"🏆 Rank: {rank_name}\n\n"
        "Share your clan ID with others to let them join!\nUse /myclan to view your clan details."
    )
    await message.reply_text(text)


# ----------------- /myclan -----------------
@app.on_message(filters.command("myclan"))
async def myclan_handler(client, message):
    user_id = message.from_user.id
    clan = get_user_clan(user_id)
    if not clan:
        return await message.reply_text("You are not in any clan. Create one with /createclan or join with /joinclan [clan_id].")

    cid, clan_code, name, owner_id, points, wins, losses, bank = clan
    # members count
    db.cursor.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id = ?", (cid,))
    members_count = db.cursor.fetchone()[0]
    level, rank_name = clan_rank_from_points(points or 0)

    text = (
        f"🏮 Clan: {name}\n"
        f"🆔 Clan ID: {clan_code}\n"
        f"👑 Owner: {owner_id}\n"
        f"👥 Members: {members_count}/20\n"
        f"✨ Level: {level}\n"
        f"🏆 Rank: {rank_name}\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"💎 Bank: {bank} 💎\n\n"
        "Share your clan ID to invite others!"
    )

    buttons = []
    if owner_id == user_id:
        buttons.append([InlineKeyboardButton("🗑️ Delete Clan", callback_data=f"clan_delete:{cid}")])
    buttons.append([InlineKeyboardButton("👥 View Members", callback_data=f"clan_members:{cid}")])

    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


# ----------------- Delete clan (owner) -----------------
@app.on_callback_query(filters.regex(r"^clan_delete:"))
async def clan_delete_cb(client, callback):
    cid = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    db.cursor.execute("SELECT owner_id, name FROM clans WHERE id = ?", (cid,))
    row = db.cursor.fetchone()
    if not row:
        await callback.answer("Clan not found.", show_alert=True)
        return
    owner_id, name = row
    if user_id != owner_id:
        await callback.answer("Only the clan owner can delete the clan.", show_alert=True)
        return

    # remove members & clan
    db.cursor.execute("DELETE FROM clan_members WHERE clan_id = ?", (cid,))
    db.cursor.execute("DELETE FROM clans WHERE id = ?", (cid,))
    db.conn.commit()
    await callback.message.edit_text(f"🗑️ Clan `{name}` deleted successfully.")
    await callback.answer()


# ----------------- View members -----------------
@app.on_callback_query(filters.regex(r"^clan_members:"))
async def clan_members_cb(client, callback):
    cid = int(callback.data.split(":")[1])
    db.cursor.execute("SELECT user_id, role FROM clan_members WHERE clan_id = ? ORDER BY role DESC, joined_at ASC", (cid,))
    rows = db.cursor.fetchall()
    if not rows:
        await callback.answer("No members found.", show_alert=True)
        return
    lines = []
    for user_id, role in rows:
        # fetch username or first_name
        db.cursor.execute("SELECT username, first_name FROM users WHERE user_id = ?", (user_id,))
        u = db.cursor.fetchone()
        if u:
            uname, fname = u
            label = f"@{uname}" if uname else (fname or str(user_id))
        else:
            label = str(user_id)
        lines.append(f"{label} — {role}")
    await callback.message.reply_text("👥 Clan Members:\n\n" + "\n".join(lines))
    await callback.answer()


# ----------------- /joinclan -----------------
@app.on_message(filters.command("joinclan"))
async def join_clan_handler(client, message):
    user_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Usage: /joinclan [clan_id]\nExample: /joinclan 123456")

    code = parts[1].strip()
    # check user already in clan
    if get_user_clan(user_id):
        return await message.reply_text("You are already in a clan. Leave it first with /leaveclan.")

    db.cursor.execute("SELECT id, name FROM clans WHERE clan_id = ?", (code,))
    row = db.cursor.fetchone()
    if not row:
        return await message.reply_text("Clan ID not found.")

    cid, name = row
    # check capacity
    db.cursor.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id = ?", (cid,))
    count = db.cursor.fetchone()[0]
    if count >= 20:
        return await message.reply_text("Clan is full (20 members).")

    now_iso = datetime.now().isoformat()
    db.cursor.execute("INSERT INTO clan_members (clan_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                      (cid, user_id, now_iso))
    db.conn.commit()

    # notify owner
    db.cursor.execute("SELECT owner_id FROM clans WHERE id = ?", (cid,))
    owner_id = db.cursor.fetchone()[0]
    try:
        await client.send_message(owner_id, f"🔔 {message.from_user.first_name or message.from_user.username} has joined your clan `{name}`.")
    except Exception:
        pass

    await message.reply_text(f"✅ You joined clan `{name}`. Say hi to your clan!")


# ----------------- /leaveclan -----------------
@app.on_message(filters.command("leaveclan"))
async def leave_clan_handler(client, message):
    user_id = message.from_user.id
    clan = get_user_clan(user_id)
    if not clan:
        return await message.reply_text("You are not in any clan.")

    cid, clan_code, name, owner_id, points, wins, losses, bank = clan
    db.cursor.execute("DELETE FROM clan_members WHERE clan_id = ? AND user_id = ?", (cid, user_id))
    db.conn.commit()

    if user_id == owner_id:
        # transfer ownership to earliest joined member if exists
        db.cursor.execute("SELECT user_id FROM clan_members WHERE clan_id = ? ORDER BY joined_at ASC LIMIT 1", (cid,))
        nxt = db.cursor.fetchone()
        if nxt:
            new_owner = nxt[0]
            db.cursor.execute("UPDATE clans SET owner_id = ? WHERE id = ?", (new_owner, cid))
            db.cursor.execute("UPDATE clan_members SET role = 'owner' WHERE clan_id = ? AND user_id = ?", (cid, new_owner))
            db.conn.commit()
            try:
                await client.send_message(new_owner, f"👑 You are now the owner of clan `{name}` (transferred).")
            except Exception:
                pass
        else:
            # no members left → delete clan
            db.cursor.execute("DELETE FROM clans WHERE id = ?", (cid,))
            db.conn.commit()
            await message.reply_text(f"Clan `{name}` had no members left and was deleted.")
            return

    await message.reply_text("You left the clan.")


# ----------------- /clanwar -----------------
@app.on_message(filters.command("clanwar"))
async def clanwar_handler(client, message):
    user_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Usage: /clanwar [target_clan_id]")

    target_code = parts[1].strip()
    # ensure user in a clan
    myclan = get_user_clan(user_id)
    if not myclan:
        return await message.reply_text("You must be in a clan to start a war.")

    my_cid = myclan[0]
    # find target clan
    db.cursor.execute("SELECT id, name FROM clans WHERE clan_id = ?", (target_code,))
    target = db.cursor.fetchone()
    if not target:
        return await message.reply_text("Target clan not found.")
    target_cid, target_name = target

    if target_cid == my_cid:
        return await message.reply_text("You cannot challenge your own clan.")

    # create war (active for 24 hours)
    now = datetime.now()
    end = now + timedelta(hours=24)
    db.cursor.execute("INSERT INTO clan_wars (challenger_clan, target_clan, start_iso, end_iso, status) VALUES (?, ?, ?, ?, 'active')",
                      (my_cid, target_cid, now.isoformat(), end.isoformat()))
    db.conn.commit()
    war_id = db.cursor.lastrowid

    # initialize war_contrib rows maybe not necessary until contributions occur
    # notify both clans' members by DM
    for clanid in (my_cid, target_cid):
        db.cursor.execute("SELECT user_id FROM clan_members WHERE clan_id = ?", (clanid,))
        for (uid,) in db.cursor.fetchall():
            try:
                await client.send_message(uid, f"⚔️ Clan War started (ID: {war_id})! Your clan was challenged. War runs until {end.isoformat()}. Contribute points to win!")
            except Exception:
                pass

    await message.reply_text(f"⚔️ Clan war started vs `{target_name}` (war_id: {war_id}). Members have 24 hours to contribute points.")


# Helper to add contribution points during active war
def add_war_points(war_id: int, clan_id: int, user_id: int, points: int):
    # increase war_contrib row and clan_wars totals
    db.cursor.execute("SELECT points FROM clan_wars WHERE id = ?", (war_id,))
    war = db.cursor.fetchone()
    if not war:
        return False
    # upsert war_contrib
    db.cursor.execute("SELECT points FROM clan_war_contrib WHERE war_id = ? AND user_id = ?", (war_id, user_id))
    row = db.cursor.fetchone()
    if row:
        db.cursor.execute("UPDATE clan_war_contrib SET points = points + ? WHERE war_id = ? AND user_id = ?", (points, war_id, user_id))
    else:
        db.cursor.execute("INSERT INTO clan_war_contrib (war_id, clan_id, user_id, points) VALUES (?, ?, ?, ?)", (war_id, clan_id, user_id, points))
    # increment clan total in clan_wars
    # determine whether clan is challenger or target
    db.cursor.execute("SELECT challenger_clan, target_clan FROM clan_wars WHERE id = ?", (war_id,))
    cw = db.cursor.fetchone()
    if not cw:
        return False
    challenger_clan, target_clan = cw
    if clan_id == challenger_clan:
        db.cursor.execute("UPDATE clan_wars SET challenger_points = challenger_points + ? WHERE id = ?", (points, war_id))
    elif clan_id == target_clan:
        db.cursor.execute("UPDATE clan_wars SET target_points = target_points + ? WHERE id = ?", (points, war_id))
    db.conn.commit()
    return True


# ----------------- resolve war (helper + accessible command) -----------------
def resolve_war_if_ended(war_id):
    db.cursor.execute("SELECT id, challenger_clan, target_clan, end_iso, status, challenger_points, target_points FROM clan_wars WHERE id = ?", (war_id,))
    row = db.cursor.fetchone()
    if not row:
        return None
    wid, chal, targ, end_iso, status, cpts, tpts = row
    try:
        end_dt = datetime.fromisoformat(end_iso)
    except Exception:
        return None
    if status != "active":
        return None
    if datetime.now() >= end_dt:
        # finish
        winner = None
        if cpts > tpts:
            winner = chal
            loser = targ
        elif tpts > cpts:
            winner = targ
            loser = chal
        else:
            # tie = no update
            winner = None

        # update clans points/wins/losses and mark war finished
        if winner:
            # winner gets + total points to clan points (simple)
            awarded = (cpts + tpts)
            db.cursor.execute("UPDATE clans SET points = points + ?, wins = wins + 1 WHERE id = ?", (awarded, winner))
            db.cursor.execute("UPDATE clans SET losses = losses + 1 WHERE id = ?", (loser,))
        db.cursor.execute("UPDATE clan_wars SET status = 'finished' WHERE id = ?", (wid,))
        db.conn.commit()
        return {"war_id": wid, "winner": winner, "challenger_points": cpts, "target_points": tpts}
    return None


@app.on_message(filters.command("finishwar"))
async def finish_war_cmd(client, message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Usage: /finishwar [war_id]")
    try:
        war_id = int(parts[1].strip())
    except:
        return await message.reply_text("Invalid war id.")
    res = resolve_war_if_ended(war_id)
    if not res:
        return await message.reply_text("War not finished yet or invalid.")
    # notify owners
    wid = res["war_id"]
    winner = res["winner"]
    db.cursor.execute("SELECT challenger_clan, target_clan FROM clan_wars WHERE id = ?", (wid,))
    cw = db.cursor.fetchone()
    if cw:
        ch, ta = cw
        for clanid in (ch, ta):
            db.cursor.execute("SELECT owner_id FROM clans WHERE id = ?", (clanid,))
            orow = db.cursor.fetchone()
            if orow:
                try:
                    await client.send_message(orow[0], f"🏁 War {wid} finished. Result: {res}")
                except:
                    pass
    await message.reply_text("War resolved (if end time passed).")


# ----------------- /clantop -----------------
@app.on_message(filters.command("clantop"))
async def clantop_handler(client, message):
    db.cursor.execute("SELECT clan_id, name, points, wins, losses FROM clans ORDER BY points DESC LIMIT 10")
    rows = db.cursor.fetchall()
    if not rows:
        return await message.reply_text("No clans yet.")
    lines = []
    for i, (code, name, pts, wins, losses) in enumerate(rows, start=1):
        level, rank = clan_rank_from_points(pts or 0)
        lines.append(f"{i}. {name} ({code}) — {pts or 0} pts — {rank} — Wins:{wins} Losses:{losses}")
    await message.reply_text("🏆 Top Clans\n\n" + "\n".join(lines))


# ----------------- /clandonate -----------------
@app.on_message(filters.command("clandonate"))
async def clandonate_handler(client, message):
    user_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Usage: /clandonate [amount]")

    try:
        amount = int(parts[1].replace(",", "").strip())
    except:
        return await message.reply_text("Invalid amount.")

    if amount <= 0:
        return await message.reply_text("Amount must be positive.")

    clan = get_user_clan(user_id)
    if not clan:
        return await message.reply_text("You are not in a clan.")

    cid = clan[0]

    # check user has enough crystals (use get_crystals total)
    daily, weekly, monthly, total, last_claim, given = db.get_crystals(user_id)
    if total < amount:
        return await message.reply_text("You don't have enough crystals to donate.")

    # deduct from user (use add_crystals with negative given)
    db.add_crystals(user_id, given=-amount)

    # add to clan bank
    db.cursor.execute("UPDATE clans SET bank = bank + ? WHERE id = ?", (amount, cid))
    db.conn.commit()
    db.log_event("clan_donate", user_id=user_id, details=f"donated {amount} to clan {cid}")

    await message.reply_text(f"✅ Donated {amount} 💎 to your clan bank.")


# ----------------- /clanbankwithdraw -----------------
@app.on_message(filters.command("clanbankwithdraw"))
async def clanbank_withdraw_handler(client, message):
    user_id = message.from_user.id
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Usage: /clanbankwithdraw [amount]")

    try:
        amount = int(parts[1].replace(",", "").strip())
    except:
        return await message.reply_text("Invalid amount.")

    if amount <= 0:
        return await message.reply_text("Amount must be positive.")

    clan = get_user_clan(user_id)
    if not clan:
        return await message.reply_text("You are not in a clan.")
    cid, clan_code, name, owner_id, points, wins, losses, bank = clan

    # only owner can withdraw (simpler rule). Change if you want members to withdraw.
    if user_id != owner_id:
        return await message.reply_text("Only the clan owner can withdraw from clan bank.")

    if bank < amount:
        return await message.reply_text("Clan bank does not have enough crystals.")

    # check cooldown per owner in clan_withdrawals table (3 hours)
    today_iso = date.today().isoformat()
    db.cursor.execute("SELECT last_withdraw_iso, daily_withdraw_total, daily_reset_date FROM clan_withdrawals WHERE clan_id = ? AND user_id = ?", (cid, user_id))
    row = db.cursor.fetchone()
    last_iso, daily_total, daily_reset = (None, 0, None) if not row else row

    now_dt = datetime.now()
    if last_iso:
        try:
            last_dt = datetime.fromisoformat(last_iso)
            if now_dt < last_dt + timedelta(hours=3):
                return await message.reply_text("Withdraw cooldown: you must wait 3 hours between withdrawals.")
        except:
            pass

    # reset daily total if day changed
    if not daily_reset or daily_reset != today_iso:
        daily_total = 0
        daily_reset = today_iso

    # optional daily limit per clan - let's set high limit (e.g., bank itself), so just enforce no more than bank
    # perform withdraw
    db.cursor.execute("UPDATE clans SET bank = bank - ? WHERE id = ?", (amount, cid))
    db.conn.commit()

    # credit to owner (add_crystals given)
    db.add_crystals(user_id, given=amount)

    # update withdrawals table
    if row:
        db.cursor.execute("UPDATE clan_withdrawals SET last_withdraw_iso = ?, daily_withdraw_total = ?, daily_reset_date = ? WHERE clan_id = ? AND user_id = ?",
                          (now_dt.isoformat(), (daily_total or 0) + amount, today_iso, cid, user_id))
    else:
        db.cursor.execute("INSERT INTO clan_withdrawals (clan_id, user_id, last_withdraw_iso, daily_withdraw_total, daily_reset_date) VALUES (?, ?, ?, ?, ?)",
                          (cid, user_id, now_dt.isoformat(), amount, today_iso))
    db.conn.commit()

    db.log_event("clan_withdraw", user_id=user_id, details=f"withdrew {amount} from clan {cid}")
    await message.reply_text(f"✅ Withdrawn {amount} 💎 from clan bank to your balance.")


# ----------------- Helper endpoint: show clan by id (admin or general) -----------------
@app.on_message(filters.command("claninfo"))
async def claninfo_handler(client, message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Usage: /claninfo [clan_id]")
    code = parts[1].strip()
    db.cursor.execute("SELECT id, clan_id, name, owner_id, points, wins, losses, bank FROM clans WHERE clan_id = ?", (code,))
    row = db.cursor.fetchone()
    if not row:
        return await message.reply_text("Clan not found.")
    cid, code, name, owner_id, points, wins, losses, bank = row
    lv, rank_name = clan_rank_from_points(points or 0)
    await message.reply_text(
        f"🏮 {name}\n🆔 {code}\n👑 Owner: {owner_id}\n✨ Level: {lv}\n🏆 Rank: {rank_name}\n✅ Wins: {wins}\n❌ Losses: {losses}\n💎 Bank: {bank}"
    )

# End of handlers/clan.py
