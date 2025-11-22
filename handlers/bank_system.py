# handlers/bank_system.py
"""
Alisa Waifu Bank - handlers/bank_system.py
Safe migrations included: adds missing columns instead of assuming they exist.
Features:
 - /bank, /openaccount, /atmcard, /passbook, /amount, /loan (+ callbacks)
 - /givealsia, /takealisa (+ callbacks)
 - /collectloan, /bankstats
 - /atm (view ATM cards) and /atmmachine (withdraw)
Notes:
 - Uses SQLite DB waifu_bot.db (same as rest of bot).
 - Owner ID taken from Config.OWNER_ID or fallback 7558715645.
"""

import sqlite3
import time
import io
import os
import random
import traceback
from datetime import datetime, timedelta
from typing import Optional

from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from config import app, Config

DB_PATH = "waifu_bot.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Bank owner config
BANK_OWNER_ID = getattr(Config, "OWNER_ID", 7558715645)
BANK_OWNER_NAME = "FANTOM"

BANK_NAME = "Cricket Bank Of India"
CURRENCY = "Cricket Rs"

# Settings
DEFAULT_INTEREST_RATE = 0.01
LOAN_INTEREST_RATE = 0.10
LOAN_DURATION_DAYS = 7
ATM_PRICES = {"normal": 100, "standard": 500, "platinum": 2000}
ATM_TIERS = ("normal", "standard", "platinum")

ATM_WITHDRAW_LIMIT = {"normal": 5_000, "standard": 20_000, "platinum": 100_000}
ATM_WITHDRAW_FEE = {"normal": 50, "standard": 25, "platinum": 10}
ATM_DAILY_LIMIT = {"normal": 15_000, "standard": 60_000, "platinum": 300_000}


# ----------------- Safe DB schema creation + migrations -----------------
def table_columns(table_name: str):
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        return [r[1] for r in cursor.fetchall()]
    except Exception:
        return []


def add_column_if_missing(table: str, column_def: str):
    """
    column_def example: "card_number TEXT"
    This will extract column name and add it if missing.
    """
    try:
        colname = column_def.split()[0]
        cols = table_columns(table)
        if colname not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            conn.commit()
    except sqlite3.OperationalError as e:
        # If ALTER TABLE not allowed or other error, just skip (avoid crash)
        print(f"[bank migrations] Could not add column {column_def} to {table}: {e}")
    except Exception as e:
        print(f"[bank migrations] Unexpected error adding column {column_def} to {table}: {e}")


# Create base tables (non-destructive)
cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_accounts (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    created_at TEXT,
    atm_tier TEXT DEFAULT 'normal'
)
""")

# safe: add account_no column if missing
add_column_if_missing("bank_accounts", "account_no TEXT")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount INTEGER,
    balance_after INTEGER,
    note TEXT,
    created_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    interest REAL,
    total_due INTEGER,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    due_at TEXT,
    approved_by INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_pending_ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_type TEXT,
    from_user INTEGER,
    to_user INTEGER,
    amount INTEGER,
    status TEXT DEFAULT 'pending',
    created_at TEXT
)
""")

# create atm table with minimal columns; we'll add extras with migrations
cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_atmcards (
    user_id INTEGER,
    tier TEXT,
    purchased_at TEXT,
    PRIMARY KEY (user_id, tier)
)
""")
# Add missing atm columns (safe)
add_column_if_missing("bank_atmcards", "card_number TEXT")
add_column_if_missing("bank_atmcards", "cvv TEXT")
add_column_if_missing("bank_atmcards", "expiry TEXT")
add_column_if_missing("bank_atmcards", "holder_name TEXT")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_atm_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    tier TEXT,
    amount INTEGER,
    fee INTEGER,
    balance_after INTEGER,
    created_at TEXT,
    atm_card TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_escrow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    item_type TEXT,
    item_id INTEGER,
    description TEXT,
    created_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bank_settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

# ensure user_waifus exists (many other handlers expect it)
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_waifus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    waifu_id INTEGER,
    amount INTEGER DEFAULT 0,
    UNIQUE(user_id, waifu_id)
)
""")

conn.commit()


# ----------------- Helpers -----------------
def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat()


def format_currency(amount: int) -> str:
    return f"{int(amount):,} {CURRENCY}"


def mask_card_number(card_no: str) -> str:
    if not card_no:
        return "—"
    s = str(card_no)
    if len(s) >= 16:
        return f"{s[:4]} {'*'*4} {'*'*4} {s[-4:]}"
    if len(s) >= 8:
        return f"{s[:4]} {'*'*4} {s[-len(s)+8:]}"
    return s


def generate_card_number() -> str:
    return "4" + "".join(str(random.randint(0, 9)) for _ in range(15))


def generate_cvv() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(3))


def generate_expiry_years(years: int = 3) -> str:
    expiry = datetime.utcnow() + timedelta(days=365 * years)
    return expiry.strftime("%m/%Y")


def generate_account_number(user_id: int) -> str:
    last = str(user_id)[-4:].zfill(4)
    rand6 = "".join(str(random.randint(0, 9)) for _ in range(6))
    return f"{last}{rand6}"


# Account utilities
def ensure_account(user_id: int):
    cursor.execute("SELECT user_id, account_no FROM bank_accounts WHERE user_id = ?", (user_id,))
    r = cursor.fetchone()
    if not r:
        account_no = generate_account_number(user_id)
        cursor.execute("INSERT INTO bank_accounts (user_id, balance, created_at, account_no) VALUES (?, ?, ?, ?)",
                       (user_id, 0, now_iso(), account_no))
        conn.commit()
    else:
        if not r[1]:
            acc = generate_account_number(user_id)
            cursor.execute("UPDATE bank_accounts SET account_no = ? WHERE user_id = ?", (acc, user_id))
            conn.commit()


def get_balance(user_id: int) -> int:
    cursor.execute("SELECT balance FROM bank_accounts WHERE user_id = ?", (user_id,))
    r = cursor.fetchone()
    return int(r[0]) if r and r[0] is not None else 0


def set_balance(user_id: int, new_balance: int, note: str = ""):
    ensure_account(user_id)
    cursor.execute("UPDATE bank_accounts SET balance = ? WHERE user_id = ?", (int(new_balance), user_id))
    cursor.execute("INSERT INTO bank_transactions (user_id, type, amount, balance_after, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, "admin_adjust", int(new_balance), int(new_balance), note or "Balance set by system", now_iso()))
    conn.commit()


def add_balance(user_id: int, delta: int, tx_type: str = "deposit", note: str = ""):
    ensure_account(user_id)
    bal = get_balance(user_id)
    new_bal = int(bal) + int(delta)
    cursor.execute("UPDATE bank_accounts SET balance = ? WHERE user_id = ?", (new_bal, user_id))
    cursor.execute("INSERT INTO bank_transactions (user_id, type, amount, balance_after, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (user_id, tx_type, int(delta), new_bal, note or "", now_iso()))
    conn.commit()
    return new_bal


def bank_reserve_total() -> int:
    cursor.execute("SELECT SUM(balance) FROM bank_accounts")
    r = cursor.fetchone()
    return int(r[0]) if r and r[0] is not None else 0


def get_account_no(user_id: int) -> str:
    cursor.execute("SELECT account_no FROM bank_accounts WHERE user_id = ?", (user_id,))
    r = cursor.fetchone()
    if r and r[0]:
        return r[0]
    acc = generate_account_number(user_id)
    cursor.execute("UPDATE bank_accounts SET account_no = ? WHERE user_id = ?", (acc, user_id))
    conn.commit()
    return acc


# ----------------- Commands (keeps previous behavior) -----------------
@app.on_message(filters.command("bank"))
async def cmd_bank(client, message: Message):
    total_accounts = cursor.execute("SELECT COUNT(*) FROM bank_accounts").fetchone()[0]
    total_balance = bank_reserve_total()
    atm_counts = cursor.execute("SELECT tier, COUNT(*) FROM bank_atmcards GROUP BY tier").fetchall()
    atm_info = "\n".join([f"  - {t}: {c}" for t, c in atm_counts]) if atm_counts else "  - None"
    loan_pending = cursor.execute("SELECT COUNT(*) FROM bank_loans WHERE status = 'pending'").fetchone()[0]
    loan_active = cursor.execute("SELECT COUNT(*) FROM bank_loans WHERE status = 'approved'").fetchone()[0]

    text = (
        f"🏦 {BANK_NAME}\n"
        f"💱 Currency: {CURRENCY}\n"
        f"👑 Bank Owner: {BANK_OWNER_NAME}\n\n"
        f"📊 Accounts: {total_accounts}\n"
        f"💰 Total Reserves: {format_currency(total_balance)}\n\n"
        f"💳 ATM cards issued:\n{atm_info}\n\n"
        f"📈 Interest: Savings ~{DEFAULT_INTEREST_RATE*100:.2f}% (informational)\n"
        f"💸 Loan interest (on approval): {LOAN_INTEREST_RATE*100:.0f}%\n"
        f"⏳ Loan pending: {loan_pending}, active: {loan_active}\n\n"
        f"Commands (examples):\n"
        f"/openaccount — Open your account\n"
        f"/atmcard normal|standard|platinum — Buy ATM card\n"
        f"/passbook — Get your passbook\n"
        f"/loan <amount> — Apply for loan (owner will review)\n"
        f"/amount — Show your balance\n"
    )
    await message.reply_text(text)


@app.on_message(filters.command("openaccount"))
async def cmd_openaccount(client, message: Message):
    user = message.from_user
    ensure_account(user.id)
    await message.reply_text(f"✅ Account opened for {user.first_name}.\nUse /passbook to view history and /atmcard to get an ATM card.")


@app.on_message(filters.command("atmcard"))
async def cmd_atmcard(client, message: Message):
    user = message.from_user
    ensure_account(user.id)
    parts = (message.text or "").strip().split()
    tier = None
    if len(parts) >= 2:
        candidate = parts[1].lower()
        if candidate in ATM_TIERS:
            tier = candidate
        else:
            await message.reply_text(f"Invalid tier. Choose one of: {', '.join(ATM_TIERS)}")
            return

    if not tier:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Normal (100)", callback_data=f"bank_atm_buy:{user.id}:normal"),
             InlineKeyboardButton("Standard (500)", callback_data=f"bank_atm_buy:{user.id}:standard")],
            [InlineKeyboardButton("Platinum (2000)", callback_data=f"bank_atm_buy:{user.id}:platinum")]
        ])
        await message.reply_text("Choose ATM card tier to purchase:", reply_markup=kb)
        return

    price = ATM_PRICES[tier]
    bal = get_balance(user.id)
    if bal < price:
        await message.reply_text(f"❌ You need {format_currency(price)} to buy the {tier} ATM card. Your balance: {format_currency(bal)}")
        return

    new_bal = add_balance(user.id, -price, tx_type="atm_purchase", note=f"Bought {tier} ATM card")
    card_number = generate_card_number()
    cvv = generate_cvv()
    expiry = generate_expiry_years(3)
    holder_name = user.first_name or user.username or str(user.id)
    purchased_at = now_iso()

    # use INSERT OR REPLACE to keep table shape even if columns absent (migrations added them prior)
    try:
        cursor.execute("""INSERT OR REPLACE INTO bank_atmcards
                          (user_id, tier, purchased_at, card_number, cvv, expiry, holder_name)
                          VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (user.id, tier, purchased_at, card_number, cvv, expiry, holder_name))
        conn.commit()
    except Exception:
        # fallback if DB somehow doesn't accept new columns: insert into existing columns
        try:
            cursor.execute("INSERT OR REPLACE INTO bank_atmcards (user_id, tier, purchased_at) VALUES (?, ?, ?)",
                           (user.id, tier, purchased_at))
            conn.commit()
        except Exception as e:
            print(f"[atmcard] fallback insert failed: {e}")

    await message.reply_text(
        f"✅ Purchased {tier} ATM card for {format_currency(price)}.\n"
        f"Card: {mask_card_number(card_number)}\nExpiry: {expiry}\nCVV: {cvv}\nAccount no: {get_account_no(user.id)}\nNew balance: {format_currency(new_bal)}"
    )


@app.on_callback_query(filters.regex(r"^bank_atm_buy:(\d+):(normal|standard|platinum)$"))
async def cb_atm_buy(client, callback: CallbackQuery):
    try:
        user_id = int(callback.matches[0].group(1))
        tier = callback.matches[0].group(2)
    except Exception:
        await callback.answer("Invalid data", show_alert=True)
        return

    caller = callback.from_user
    if caller.id != user_id:
        await callback.answer("This selection is for the user who opened the menu.", show_alert=True)
        return

    price = ATM_PRICES.get(tier, None)
    if price is None:
        await callback.answer("Invalid tier.", show_alert=True)
        return

    bal = get_balance(user_id)
    if bal < price:
        await callback.answer(f"Not enough balance. You need {format_currency(price)}.", show_alert=True)
        return

    new_bal = add_balance(user_id, -price, tx_type="atm_purchase", note=f"Bought {tier} ATM card")
    card_number = generate_card_number()
    cvv = generate_cvv()
    expiry = generate_expiry_years(3)
    holder_name = caller.first_name or caller.username or str(caller.id)
    purchased_at = now_iso()

    try:
        cursor.execute("""INSERT OR REPLACE INTO bank_atmcards
                          (user_id, tier, purchased_at, card_number, cvv, expiry, holder_name)
                          VALUES (?, ?, ?, ?, ?, ?, ?)""",
                       (user_id, tier, purchased_at, card_number, cvv, expiry, holder_name))
        conn.commit()
    except Exception:
        try:
            cursor.execute("INSERT OR REPLACE INTO bank_atmcards (user_id, tier, purchased_at) VALUES (?, ?, ?)",
                           (user_id, tier, purchased_at))
            conn.commit()
        except Exception as e:
            print(f"[cb_atm_buy] fallback insert failed: {e}")

    try:
        await callback.message.edit_text(
            f"✅ Purchased {tier} ATM card for {format_currency(price)}.\n"
            f"Card: {mask_card_number(card_number)}\nExpiry: {expiry}\nCVV: {cvv}\nAccount no: {get_account_no(user_id)}\nNew balance: {format_currency(new_bal)}"
        )
    except Exception:
        pass
    await callback.answer()


@app.on_message(filters.command("atm"))
async def cmd_atm_view(client, message: Message):
    user = message.from_user
    target_id = user.id

    # owner may view other's via reply or /atm <id>
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    else:
        parts = (message.text or "").strip().split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[1])
            except Exception:
                await message.reply_text("Invalid user id.")
                return

    if target_id != user.id and user.id != BANK_OWNER_ID:
        await message.reply_text("❌ Only the bank owner may view other users' ATM details.")
        return

    # Query columns safely; if new columns absent, fetch what exists
    cols = table_columns("bank_atmcards")
    select_cols = ["tier", "purchased_at"]
    if "card_number" in cols:
        select_cols.append("card_number")
    if "cvv" in cols:
        select_cols.append("cvv")
    if "expiry" in cols:
        select_cols.append("expiry")
    if "holder_name" in cols:
        select_cols.append("holder_name")

    q = f"SELECT {', '.join(select_cols)} FROM bank_atmcards WHERE user_id = ?"
    cursor.execute(q, (target_id,))
    rows = cursor.fetchall()
    if not rows:
        await message.reply_text("ℹ️ No ATM card found for that user (they need to buy one with /atmcard).")
        return

    lines = []
    for r in rows:
        # map results based on selected cols
        data = dict(zip(select_cols, r))
        lines.append(
            f"💳 Tier: {data.get('tier','—')}\n"
            f"Holder: {data.get('holder_name','—')}\n"
            f"Card Number: {data.get('card_number','—')}\n"
            f"Masked: {mask_card_number(data.get('card_number',''))}\n"
            f"CVV: {data.get('cvv','—')}\n"
            f"Expiry: {data.get('expiry','—')}\n"
            f"Created: {data.get('purchased_at','—')}\n"
            f"Account No: {get_account_no(target_id)}\n"
            "—"
        )
    text = f"ATM cards for user {target_id}:\n\n" + "\n\n".join(lines)
    if len(text) > 3000:
        bio = io.BytesIO(text.encode("utf-8"))
        bio.name = f"atm_{target_id}.txt"
        bio.seek(0)
        try:
            await client.send_document(message.chat.id, bio, caption="ATM details (file)")
        except Exception:
            await message.reply_text("Could not send file — maybe user hasn't started the bot in PM.")
    else:
        await message.reply_text(text)


@app.on_message(filters.command("atmmachine"))
async def cmd_atmmachine(client, message: Message):
    user = message.from_user
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.reply_text("Usage: /atmmachine <amount>")
        return
    try:
        amount = int(parts[1])
    except Exception:
        await message.reply_text("Invalid amount. Must be an integer.")
        return
    if amount <= 0:
        await message.reply_text("Amount must be positive.")
        return

    ensure_account(user.id)
    cursor.execute("SELECT tier, card_number, cvv, expiry, purchased_at FROM bank_atmcards WHERE user_id = ? ORDER BY CASE tier WHEN 'platinum' THEN 3 WHEN 'standard' THEN 2 ELSE 1 END DESC LIMIT 1", (user.id,))
    card = cursor.fetchone()
    if not card:
        await message.reply_text("❌ You don't own an ATM card. Buy one with /atmcard.")
        return
    # card may have fewer columns depending on schema; map safely
    tier = card[0]
    card_number = card[1] if len(card) > 1 else None

    tier_limit = ATM_WITHDRAW_LIMIT.get(tier, ATM_WITHDRAW_LIMIT["normal"])
    if amount > tier_limit:
        await message.reply_text(f"❌ Exceeds per-withdraw limit for your {tier} card: {tier_limit:,} {CURRENCY}.")
        return

    since = (datetime.utcnow() - timedelta(days=1)).replace(microsecond=0).isoformat()
    cursor.execute("SELECT SUM(amount) FROM bank_atm_transactions WHERE user_id = ? AND created_at >= ?", (user.id, since))
    today_sum = cursor.fetchone()[0] or 0
    daily_limit = ATM_DAILY_LIMIT.get(tier, ATM_DAILY_LIMIT["normal"])
    if (today_sum + amount) > daily_limit:
        await message.reply_text(f"❌ Daily withdrawal limit reached/exceeded for your {tier} card. Daily limit: {daily_limit:,} {CURRENCY}. Already withdrawn today: {today_sum:,}.")
        return

    fee = ATM_WITHDRAW_FEE.get(tier, 0)
    total_debit = amount + fee
    bal = get_balance(user.id)
    if bal < total_debit:
        await message.reply_text(f"❌ Insufficient balance. Withdrawal amount + fee = {total_debit:,}. Your balance: {bal:,}.")
        return

    new_bal = add_balance(user.id, -total_debit, tx_type="atm_withdraw", note=f"ATM withdraw {amount} (fee {fee})")
    try:
        cursor.execute("INSERT INTO bank_atm_transactions (user_id, tier, amount, fee, balance_after, created_at, atm_card) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (user.id, tier, amount, fee, new_bal, now_iso(), mask_card_number(card_number)))
        conn.commit()
    except Exception:
        conn.commit()

    try:
        await message.reply_text(f"✅ Withdrawal successful.\nDispensed: {amount:,} {CURRENCY}\nFee: {fee:,} {CURRENCY}\nNew balance: {new_bal:,} {CURRENCY}\nCard: {mask_card_number(card_number)} (tier: {tier})")
    except Exception:
        pass


# ----------------- Passbook / amount / loan / give/take / loan callbacks / collectloan / bankstats -----------------
# The remainder replicates the previously working logic (unchanged) for:
# - /passbook
# - /amount
# - /loan and loan approval/decline callbacks
# - /givealsia and /takealisa and their callbacks
# - /collectloan
# - /bankstats
#
# They are included here verbatim (kept as in your working version) to avoid breaking
# existing behavior. If you already have these blocks in your file, ensure they are present
# after this ATM code. For completeness I include them below.

@app.on_message(filters.command("passbook"))
async def cmd_passbook(client, message: Message):
    user = message.from_user
    ensure_account(user.id)

    cursor.execute("SELECT id, type, amount, balance_after, note, created_at FROM bank_transactions WHERE user_id = ? ORDER BY id DESC LIMIT 200", (user.id,))
    rows = cursor.fetchall()

    if not rows:
        await message.reply_text("ℹ️ No transactions found for your account.")
        return

    lines = [f"Passbook for {user.first_name} — {CURRENCY}\nGenerated: {now_iso()}\n", "-"*40]
    for r in rows:
        tid, ttype, amount, bal_after, note, created_at = r
        lines.append(f"{created_at} | {ttype} | {amount:,} | Bal:{bal_after:,} | {note or ''}")

    text = "\n".join(lines)

    try:
        await message.reply_text(text if len(text) < 3000 else text[:2900] + "\n\n(see attached full passbook)")
    except Exception:
        pass

    bio = io.BytesIO(text.encode("utf-8"))
    bio.name = f"passbook_{user.id}.txt"
    bio.seek(0)
    try:
        await client.send_document(user.id, document=bio, caption=f"Full passbook for {user.first_name}")
    except Exception:
        try:
            await client.send_document(message.chat.id, document=bio, caption=f"Full passbook for {user.first_name}")
        except Exception:
            await message.reply_text("Could not deliver passbook file (maybe user hasn't started the bot in PM).")


@app.on_message(filters.command("amount"))
async def cmd_amount(client, message: Message):
    parts = (message.text or "").strip().split()
    user = message.from_user

    if len(parts) >= 2 and parts[1].lower() == "total":
        if user.id != BANK_OWNER_ID:
            await message.reply_text("❌ Only the bank owner can use /amount total.")
            return
        total = bank_reserve_total()
        await message.reply_text(f"🏦 Bank total reserves: {format_currency(total)}")
        return

    if len(parts) >= 2:
        try:
            target_id = int(parts[1])
        except Exception:
            await message.reply_text("Invalid user id.")
            return
        if user.id != BANK_OWNER_ID:
            await message.reply_text("❌ Only bank owner may check other users' balances.")
            return
        bal = get_balance(target_id)
        await message.reply_text(f"User {target_id} balance: {format_currency(bal)}")
        return

    ensure_account(user.id)
    bal = get_balance(user.id)
    await message.reply_text(f"💰 Your balance: {format_currency(bal)}")


@app.on_message(filters.command("loan"))
async def cmd_loan(client, message: Message):
    user = message.from_user
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.reply_text("Usage: /loan <amount>")
        return
    try:
        amount = int(parts[1])
    except Exception:
        await message.reply_text("Invalid amount (must be an integer).")
        return

    if amount <= 0:
        await message.reply_text("Loan amount must be positive.")
        return

    interest = LOAN_INTEREST_RATE
    total_due = int(amount + (amount * interest))
    created_at = now_iso()
    due_at = (datetime.utcnow() + timedelta(days=LOAN_DURATION_DAYS)).replace(microsecond=0).isoformat()

    cursor.execute("INSERT INTO bank_loans (user_id, amount, interest, total_due, status, created_at, due_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (user.id, amount, interest, total_due, "pending", created_at, due_at))
    loan_id = cursor.lastrowid
    conn.commit()

    caption = (
        f"💳 Loan Request #{loan_id}\n\n"
        f"From: {user.first_name} (ID: {user.id})\n"
        f"Amount: {format_currency(amount)}\n"
        f"Interest: {interest*100:.0f}%\n"
        f"Total due by {due_at}: {format_currency(total_due)}\n\n"
        "Owner: use the buttons below to Approve or Decline the loan."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"bank_loan_approve:{loan_id}"),
         InlineKeyboardButton("❌ Decline", callback_data=f"bank_loan_decline:{loan_id}")]
    ])
    try:
        await client.send_message(BANK_OWNER_ID, caption, reply_markup=kb)
    except Exception:
        await message.reply_text("Could not DM owner. Sending the loan request in this chat for owner to act.")
        await message.reply_text(caption, reply_markup=kb)

    await message.reply_text(f"✅ Loan request #{loan_id} submitted. Owner will review it.")


@app.on_callback_query(filters.regex(r"^bank_loan_approve:(\d+)$"))
async def cb_loan_approve(client, callback: CallbackQuery):
    loan_id = int(callback.matches[0].group(1))
    user = callback.from_user

    if user.id != BANK_OWNER_ID:
        await callback.answer("Only the bank owner may approve loans.", show_alert=True)
        return

    cursor.execute("SELECT id, user_id, amount, total_due, status FROM bank_loans WHERE id = ?", (loan_id,))
    row = cursor.fetchone()
    if not row:
        await callback.answer("Loan not found.", show_alert=True)
        return
    _, borrower_id, amount, total_due, status = row
    if status != "pending":
        await callback.answer(f"Loan is already {status}.", show_alert=True)
        return

    add_balance(borrower_id, int(amount), tx_type="loan_disburse", note=f"Loan #{loan_id} approved")
    cursor.execute("UPDATE bank_loans SET status = ?, approved_by = ? WHERE id = ?", ("approved", user.id, loan_id))
    conn.commit()

    try:
        await client.send_message(borrower_id, f"🎉 Your loan #{loan_id} for {format_currency(amount)} was approved by the bank owner. Total due: {format_currency(total_due)}")
    except Exception:
        pass

    try:
        await callback.message.edit_reply_markup(None)
    except Exception:
        pass

    await callback.answer("Loan approved.")


@app.on_callback_query(filters.regex(r"^bank_loan_decline:(\d+)$"))
async def cb_loan_decline(client, callback: CallbackQuery):
    loan_id = int(callback.matches[0].group(1))
    user = callback.from_user
    if user.id != BANK_OWNER_ID:
        await callback.answer("Only the bank owner may decline loans.", show_alert=True)
        return

    cursor.execute("SELECT id, user_id, status FROM bank_loans WHERE id = ?", (loan_id,))
    row = cursor.fetchone()
    if not row:
        await callback.answer("Loan not found.", show_alert=True)
        return

    if row[2] != "pending":
        await callback.answer(f"Loan already {row[2]}.", show_alert=True)
        return

    cursor.execute("UPDATE bank_loans SET status = ? WHERE id = ?", ("declined", loan_id))
    conn.commit()

    borrower = row[1]
    try:
        await client.send_message(borrower, f"❌ Your loan #{loan_id} was declined by the bank owner.")
    except Exception:
        pass

    try:
        await callback.message.edit_reply_markup(None)
    except Exception:
        pass

    await callback.answer("Loan declined.")


@app.on_message(filters.command("givealsia"))
async def cmd_givealsia(client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply_text("Reply to the target user's message with /givealsia <amount> to propose giving them money.")
        return

    owner = message.from_user
    if owner.id != BANK_OWNER_ID:
        await message.reply_text("❌ Only the bank owner can give Alisa Dollars to users.")
        return

    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.reply_text("Usage: reply + /givealsia <amount>")
        return

    try:
        amount = int(parts[1])
    except Exception:
        await message.reply_text("Invalid amount.")
        return

    target = message.reply_to_message.from_user
    created_at = now_iso()
    cursor.execute("INSERT INTO bank_pending_ops (op_type, from_user, to_user, amount, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   ("give", owner.id, target.id, amount, "pending", created_at))
    op_id = cursor.lastrowid
    conn.commit()

    caption = f"🎁 Bank Give Proposal #{op_id}\nFrom: {owner.first_name}\nTo: {target.first_name} (ID: {target.id})\nAmount: {format_currency(amount)}\n\n{target.first_name}, do you accept?"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Accept", callback_data=f"bank_op_accept:{op_id}"),
         InlineKeyboardButton("❌ Decline", callback_data=f"bank_op_decline:{op_id}")]
    ])
    try:
        await client.send_message(target.id, caption, reply_markup=kb)
    except Exception:
        await message.reply_text("Could not DM the user. Sending the proposal here.")
        await message.reply_text(caption, reply_markup=kb)

    await message.reply_text(f"✅ Give proposal #{op_id} sent to the user.")


@app.on_message(filters.command("takealisa"))
async def cmd_takealisa(client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply_text("Reply to the target user's message with /takealisa <amount> [force] to take money.")
        return

    owner = message.from_user
    if owner.id != BANK_OWNER_ID:
        await message.reply_text("❌ Only the bank owner can take Alisa Dollars from users.")
        return

    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.reply_text("Usage: reply + /takealisa <amount> [force]")
        return

    try:
        amount = int(parts[1])
    except Exception:
        await message.reply_text("Invalid amount.")
        return

    force = False
    if len(parts) >= 3 and parts[2].lower() == "force":
        force = True

    target = message.reply_to_message.from_user
    bal = get_balance(target.id)
    if force:
        take_amount = min(bal, amount)
        if take_amount <= 0:
            await message.reply_text("User has no balance to take.")
            return
        new_bal = add_balance(target.id, -take_amount, tx_type="admin_withdraw", note=f"Force taken by owner")
        await message.reply_text(f"✅ Force-taken {format_currency(take_amount)} from {target.first_name}. New balance: {format_currency(new_bal)}")
        try:
            await client.send_message(target.id, f"⚠️ {format_currency(take_amount)} was taken from your bank account by the owner.")
        except Exception:
            pass
        return

    created_at = now_iso()
    cursor.execute("INSERT INTO bank_pending_ops (op_type, from_user, to_user, amount, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   ("take", owner.id, target.id, amount, "pending", created_at))
    op_id = cursor.lastrowid
    conn.commit()

    caption = f"⚠️ Bank Take Proposal #{op_id}\nFrom: {owner.first_name}\nTo: {target.first_name} (ID: {target.id})\nAmount: {format_currency(amount)}\n\n{target.first_name}, do you accept giving this amount? (Decline to refuse)"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Accept (give)", callback_data=f"bank_op_accept:{op_id}"),
         InlineKeyboardButton("❌ Decline", callback_data=f"bank_op_decline:{op_id}")]
    ])
    try:
        await client.send_message(target.id, caption, reply_markup=kb)
    except Exception:
        await message.reply_text("Could not DM the user. Sending the proposal here.")
        await message.reply_text(caption, reply_markup=kb)

    await message.reply_text(f"✅ Take proposal #{op_id} sent to the user.")


@app.on_callback_query(filters.regex(r"^bank_op_accept:(\d+)$"))
async def cb_bank_op_accept(client, callback: CallbackQuery):
    op_id = int(callback.matches[0].group(1))
    caller = callback.from_user

    cursor.execute("SELECT id, op_type, from_user, to_user, amount, status FROM bank_pending_ops WHERE id = ?", (op_id,))
    row = cursor.fetchone()
    if not row:
        await callback.answer("Operation not found.", show_alert=True)
        return
    _, op_type, from_user, to_user, amount, status = row
    if caller.id != to_user:
        await callback.answer("Only the target user can respond to this operation.", show_alert=True)
        return
    if status != "pending":
        await callback.answer(f"Operation already {status}.", show_alert=True)
        return

    if op_type == "give":
        new_bal = add_balance(to_user, int(amount), tx_type="admin_deposit", note=f"Owner gave funds (op#{op_id})")
        cursor.execute("UPDATE bank_pending_ops SET status = ? WHERE id = ?", ("accepted", op_id))
        conn.commit()
        try:
            await callback.message.edit_reply_markup(None)
        except Exception:
            pass
        await callback.answer("You accepted the funds. Check your balance.")
        try:
            await client.send_message(to_user, f"✅ You received {format_currency(amount)} from the bank owner. New balance: {format_currency(new_bal)}")
        except Exception:
            pass
        try:
            await client.send_message(from_user, f"✅ User {to_user} accepted the give proposal #{op_id}.")
        except Exception:
            pass
        return

    if op_type == "take":
        bal = get_balance(to_user)
        take_amount = min(int(amount), bal)
        if take_amount <= 0:
            cursor.execute("UPDATE bank_pending_ops SET status = ? WHERE id = ?", ("cancelled", op_id))
            conn.commit()
            await callback.answer("You have no balance to give.")
            return
        new_bal = add_balance(to_user, -take_amount, tx_type="admin_withdraw", note=f"User accepted take (op#{op_id})")
        cursor.execute("UPDATE bank_pending_ops SET status = ? WHERE id = ?", ("accepted", op_id))
        conn.commit()
        try:
            await callback.message.edit_reply_markup(None)
        except Exception:
            pass
        await callback.answer("You accepted to give the funds.")
        try:
            await client.send_message(to_user, f"✅ You gave {format_currency(take_amount)} to the owner. New balance: {format_currency(new_bal)}")
        except Exception:
            pass
        try:
            await client.send_message(from_user, f"✅ User {to_user} accepted the take proposal #{op_id}.")
        except Exception:
            pass
        return

    await callback.answer("Unknown operation type.", show_alert=True)


@app.on_callback_query(filters.regex(r"^bank_op_decline:(\d+)$"))
async def cb_bank_op_decline(client, callback: CallbackQuery):
    op_id = int(callback.matches[0].group(1))
    caller = callback.from_user

    cursor.execute("SELECT id, op_type, from_user, to_user, amount, status FROM bank_pending_ops WHERE id = ?", (op_id,))
    row = cursor.fetchone()
    if not row:
        await callback.answer("Operation not found.", show_alert=True)
        return
    _, op_type, from_user, to_user, amount, status = row
    if caller.id != to_user:
        await callback.answer("Only the target user can respond to this operation.", show_alert=True)
        return
    if status != "pending":
        await callback.answer(f"Operation already {status}.", show_alert=True)
        return

    cursor.execute("UPDATE bank_pending_ops SET status = ? WHERE id = ?", ("declined", op_id))
    conn.commit()
    try:
        await callback.message.edit_reply_markup(None)
    except Exception:
        pass
    await callback.answer("You declined the proposal.")
    try:
        await client.send_message(from_user, f"❌ User {to_user} declined the proposal #{op_id}.")
    except Exception:
        pass


@app.on_message(filters.command("collectloan"))
async def cmd_collectloan(client, message: Message):
    owner = message.from_user
    if owner.id != BANK_OWNER_ID:
        await message.reply_text("❌ Only the bank owner can collect loans / mark defaults.")
        return

    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.reply_text("Usage: /collectloan <loan_id>")
        return

    try:
        loan_id = int(parts[1])
    except Exception:
        await message.reply_text("Invalid loan id.")
        return

    cursor.execute("SELECT id, user_id, amount, total_due, status, due_at FROM bank_loans WHERE id = ?", (loan_id,))
    row = cursor.fetchone()
    if not row:
        await message.reply_text("Loan not found.")
        return
    _id, user_id, amount, total_due, status, due_at = row

    if status != "approved":
        await message.reply_text(f"Loan #{loan_id} is not active (status: {status}).")
        return

    try:
        due_dt = datetime.fromisoformat(due_at)
    except Exception:
        due_dt = None

    if due_dt and datetime.utcnow() < due_dt:
        await message.reply_text(f"Loan #{loan_id} is not overdue yet. Due at: {due_at}")
        return

    cursor.execute("UPDATE bank_loans SET status = ? WHERE id = ?", ("defaulted", loan_id))
    try:
        cursor.execute("SELECT cricketer_id, amount FROM user_cricketers WHERE user_id = ?", (user_id,))
        waifus = cursor.fetchall()
        seized = 0
        if waifus:
            for wid, amt in waifus:
                cursor.execute("INSERT INTO bank_escrow (user_id, item_type, item_id, description, created_at) VALUES (?, ?, ?, ?, ?)",
                               (user_id, "cricketers", wid, f"Seized for loan #{loan_id}", now_iso()))
                seized += 1
            cursor.execute("DELETE FROM user_cricketers WHERE user_id = ?", (user_id,))
        conn.commit()
        await message.reply_text(f"Loan #{loan_id} marked DEFAULTED. Seized {seized} cricketer entries into escrow (if any).")
        try:
            await client.send_message(user_id, f"⚠️ Your loan #{loan_id} defaulted. The owner seized available inventory into escrow.")
        except Exception:
            pass
    except Exception:
        conn.commit()
        await message.reply_text("Loan defaulted but failed to seize inventory (maybe user_cricketers table missing).")


@app.on_message(filters.command("bankstats"))
async def cmd_bankstats(client, message: Message):
    owner = message.from_user
    if owner.id != BANK_OWNER_ID:
        await message.reply_text("❌ Only the bank owner can view bank stats.")
        return

    total_accounts = cursor.execute("SELECT COUNT(*) FROM bank_accounts").fetchone()[0]
    total_reserves = bank_reserve_total()
    loans_total = cursor.execute("SELECT SUM(amount) FROM bank_loans WHERE status = 'approved'").fetchone()[0] or 0
    loans_pending = cursor.execute("SELECT COUNT(*) FROM bank_loans WHERE status = 'pending'").fetchone()[0]
    escrow_count = cursor.execute("SELECT COUNT(*) FROM bank_escrow").fetchone()[0]

    text = (
        f"🏦 {BANK_NAME} — Detailed Stats\n\n"
        f"Accounts: {total_accounts}\n"
        f"Total reserves: {format_currency(total_reserves)}\n"
        f"Active loans total: {format_currency(loans_total)}\n"
        f"Pending loan requests: {loans_pending}\n"
        f"Items in escrow: {escrow_count}\n"
    )
    await message.reply_text(text)


# ----------------- End of bank_system.py -----------------
