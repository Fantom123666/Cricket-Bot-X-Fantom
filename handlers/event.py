# handlers/event.py
"""
Event system:
- /event <name>|<start>|<end>    (owner only)  -- create event
- /register                       (users)       -- register for active event
- /listuser                       (owner/admin) -- show registrations for active event
- /delwinner                      (owner only)  -- pick up to 10 random winners from registrations and DM them
"""

from datetime import datetime
from typing import Optional, List, Tuple
from pyrogram import filters
from pyrogram.types import Message
from config import app, Config
from database import Database
import random

db = Database()

# ---------------- Ensure tables ----------------
def ensure_event_tables():
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            start_at TEXT,
            end_at TEXT,
            created_by INTEGER,
            created_at TEXT
        )
    """)
    db.cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_registrations (
            event_id INTEGER,
            user_id INTEGER,
            registered_at TEXT,
            PRIMARY KEY (event_id, user_id)
        )
    """)
    db.conn.commit()

ensure_event_tables()

# ---------------- Helpers ----------------
def is_owner(uid: int) -> bool:
    try:
        if getattr(Config, "OWNER_ID", None) and int(uid) == int(Config.OWNER_ID):
            return True
        owner_ids = getattr(Config, "OWNER_IDS", []) or []
        if owner_ids and int(uid) in [int(x) for x in owner_ids]:
            return True
    except Exception:
        pass
    return False

def is_admin(uid: int) -> bool:
    try:
        if is_owner(uid):
            return True
        admins = getattr(Config, "ADMINS", []) or []
        if admins and int(uid) in [int(x) for x in admins]:
            return True
    except Exception:
        pass
    return False

def now_iso() -> str:
    return datetime.utcnow().isoformat()

def parse_datetime(text: str) -> Optional[datetime]:
    """Try multiple formats; return naive UTC datetime on success, else None."""
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt
        except Exception:
            continue
    return None

def create_event_row(name: str, start_iso: str, end_iso: str, created_by: int):
    db.cursor.execute(
        "INSERT INTO events (name, start_at, end_at, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, start_iso, end_iso, created_by, now_iso())
    )
    db.conn.commit()
    return db.cursor.lastrowid

def get_active_event() -> Optional[Tuple]:
    """Return the active event row (id, name, start_at, end_at, ...) where start<=now<=end, else None."""
    now = datetime.utcnow().isoformat()
    db.cursor.execute("""
        SELECT id, name, start_at, end_at, created_by, created_at
        FROM events
        WHERE start_at <= ? AND end_at >= ?
        ORDER BY id DESC
        LIMIT 1
    """, (now, now))
    row = db.cursor.fetchone()
    return row

def get_latest_event() -> Optional[Tuple]:
    db.cursor.execute("""
        SELECT id, name, start_at, end_at, created_by, created_at
        FROM events
        ORDER BY id DESC
        LIMIT 1
    """)
    return db.cursor.fetchone()

def register_user_for_event(event_id: int, user_id: int) -> bool:
    """Return True if registered added; False if already registered or error."""
    try:
        db.cursor.execute("INSERT OR IGNORE INTO event_registrations (event_id, user_id, registered_at) VALUES (?, ?, ?)",
                          (event_id, int(user_id), now_iso()))
        db.conn.commit()
        # check if inserted
        db.cursor.execute("SELECT 1 FROM event_registrations WHERE event_id = ? AND user_id = ?", (event_id, user_id))
        return db.cursor.fetchone() is not None
    except Exception:
        return False

def get_registration_count(event_id: int) -> int:
    db.cursor.execute("SELECT COUNT(*) FROM event_registrations WHERE event_id = ?", (event_id,))
    row = db.cursor.fetchone()
    return row[0] if row else 0

def get_registered_users(event_id: int) -> List[int]:
    db.cursor.execute("SELECT user_id FROM event_registrations WHERE event_id = ?", (event_id,))
    rows = db.cursor.fetchall()
    return [r[0] for r in rows]

async def dm_user(client, uid: int, text: str) -> bool:
    try:
        await client.send_message(uid, text)
        return True
    except Exception:
        return False

# ---------------- Commands ----------------

# /event <name>|<start>|<end>   owner only
@app.on_message(filters.command("event"))
async def event_cmd(client, message: Message):
    uid = message.from_user.id
    if not is_owner(uid):
        return await message.reply_text("❌ Only the bot owner can create events.")

    # Expect single line after command: name|start|end
    raw = (message.text or "").strip()
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text(
            "Usage (single-line):\n"
            "/event EventName|YYYY-MM-DD HH:MM|YYYY-MM-DD HH:MM\n\n"
            "Accepted date formats: YYYY-MM-DD HH:MM  or  YYYY-MM-DDTHH:MM  or  YYYY-MM-DD\n"
            "Example:\n"
            "/event SummerFest|2025-09-01 15:00|2025-09-07 23:59"
        )
        return

    payload = parts[1]
    if "|" not in payload:
        return await message.reply_text("Invalid format. Use: /event Name|start|end  (use '|' separators).")

    try:
        name, start_txt, end_txt = [p.strip() for p in payload.split("|", 2)]
    except Exception:
        return await message.reply_text("Invalid input. Use: /event Name|start|end")

    start_dt = parse_datetime(start_txt)
    end_dt = parse_datetime(end_txt)
    if not start_dt or not end_dt:
        return await message.reply_text("Invalid date format. Use: YYYY-MM-DD HH:MM or YYYY-MM-DD.")
    if end_dt < start_dt:
        return await message.reply_text("End date must be after start date.")

    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()
    ensure_event_tables()
    eid = create_event_row(name, start_iso, end_iso, uid)
    await message.reply_text(f"✅ Event created (ID: {eid})\n• {name}\n• Start: {start_iso}\n• End: {end_iso}")

    # If start <= now, optionally notify users immediately
    try:
        if start_dt <= datetime.utcnow():
            # notify all users in users table (best-effort)
            db.cursor.execute("SELECT user_id FROM users")
            users = db.cursor.fetchall()
            notified = 0
            for (u,) in users:
                try:
                    await dm_user(client, u, f"📣 Event Started: {name}\nStarts at: {start_iso}")
                    notified += 1
                except Exception:
                    continue
            await message.reply_text(f"📣 Event start notifications sent to {notified} users (best-effort).")
    except Exception:
        pass

# /register  (users)
@app.on_message(filters.command("register"))
async def register_cmd(client, message: Message):
    user = message.from_user
    if not user:
        return
    ensure_event_tables()
    event = get_active_event()
    if not event:
        return await message.reply_text("ℹ️ There is no active event at the moment. Try later.")
    event_id, name, start_at, end_at, *_ = event
    # attempt register
    success = register_user_for_event(event_id, user.id)
    if not success:
        # check if already registered
        db.cursor.execute("SELECT 1 FROM event_registrations WHERE event_id = ? AND user_id = ?", (event_id, user.id))
        if db.cursor.fetchone():
            return await message.reply_text(f"✅ You are already registered for **{name}** (Event ID: {event_id}).")
        return await message.reply_text("❌ Registration failed. Try again later.")
    await message.reply_text(f"✅ Registered for **{name}** (Event ID: {event_id}). Good luck!")

# /listuser  (owner/admin)
@app.on_message(filters.command("listuser"))
async def listuser_cmd(client, message: Message):
    uid = message.from_user.id
    if not (is_admin(uid) or is_owner(uid)):
        return await message.reply_text("❌ Only admins/owner can view the registration list.")
    ensure_event_tables()
    event = get_active_event()
    if not event:
        # fallback to latest event
        event = get_latest_event()
        if not event:
            return await message.reply_text("No events found.")
        note = "(latest event)"
    else:
        note = "(active event)"

    event_id, name, start_at, end_at, created_by, created_at = event
    count = get_registration_count(event_id)
    await message.reply_text(f"📋 Registrations for **{name}** {note} (ID: {event_id}):\nTotal registered: {count}")

# /delwinner  (owner only)
@app.on_message(filters.command("delwinner"))
async def delwinner_cmd(client, message: Message):
    uid = message.from_user.id
    if not is_owner(uid):
        return await message.reply_text("❌ Only the bot owner can declare winners.")

    ensure_event_tables()
    # prefer active event, else latest
    event = get_active_event() or get_latest_event()
    if not event:
        return await message.reply_text("No event available to pick winners from.")
    event_id, name, start_at, end_at, created_by, created_at = event

    users = get_registered_users(event_id)
    if not users:
        return await message.reply_text("No registered users for this event.")
    # choose up to 10 random unique winners
    winners = random.sample(users, min(10, len(users)))

    notified = []
    failed = []
    for w in winners:
        try:
            ok = await dm_user(client, w, f"🏆 Congratulations! You are a winner for event '{name}'! 🎉")
            if ok:
                notified.append(w)
            else:
                failed.append(w)
        except Exception:
            failed.append(w)

    # reply summary to owner
    text = f"🏆 Winners for event **{name}** (ID: {event_id}):\n"
    for i, w in enumerate(winners, start=1):
        text += f"{i}. `{w}`\n"
    text += f"\nNotified: {len(notified)}  Failed: {len(failed)}"
    await message.reply_text(text)

    # optionally log winners to DB as events_winners table (not requested), skip.

# ensure tables created on import
ensure_event_tables()
