# handlers/bet.py
"""
/bet <amount> - open betting menu with 4 difficulty buttons:
- Easy   : 60% chance -> 2x
- Medium : 25% chance -> 3x
- Hard   : 14% chance -> 5x
- Hell   :  1% chance -> 10x

Flow:
1) User types: /bet 1000
2) Bot shows 4 inline buttons (only that user can press)
3) On button press, bot checks balance, deducts bet (proportionally across
   daily/weekly/monthly/given), then resolves outcome and credits winnings (if any).
"""
from datetime import datetime
import random
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import app
from database import Database

db = Database()

# Difficulty config: (label, win_probability, multiplier)
DIFFICULTIES = {
    "easy":   ("Easy",   0.60, 2),
    "medium": ("Medium", 0.25, 3),
    "hard":   ("Hard",   0.14, 5),
    "hell":   ("Hell",   0.01, 10)
}

# helper: get total crystals for display
def get_total_balance(user_id: int) -> int:
    try:
        daily, weekly, monthly, total, last_claim, given = db.get_crystals(user_id)
        return int(total)
    except Exception:
        # fallback: query directly
        try:
            db.cursor.execute("SELECT daily_crystals, weekly_crystals, monthly_crystals, given_crystals FROM users WHERE user_id = ?", (user_id,))
            row = db.cursor.fetchone()
            if not row:
                return 0
            vals = [int(v or 0) for v in row]
            return sum(vals)
        except Exception:
            return 0

# helper: deduct amount proportionally across columns (same logic as purchase_waifu)
def deduct_user_balance(user_id: int, amount: int) -> bool:
    """Return True if deduction succeeded (amount deducted); False if insufficient funds.
    This function updates user rows and commits.
    """
    if amount <= 0:
        return True
    # check total first
    try:
        daily, weekly, monthly, total, last_claim, given = db.get_crystals(user_id)
        if total < amount:
            return False
    except Exception:
        # fallback to direct query
        db.cursor.execute("SELECT daily_crystals, weekly_crystals, monthly_crystals, given_crystals FROM users WHERE user_id = ?", (user_id,))
        row = db.cursor.fetchone()
        if not row:
            return False
        vals = [int(r or 0) for r in row]
        if sum(vals) < amount:
            return False

    remaining = int(amount)
    cols = ["daily_crystals", "weekly_crystals", "monthly_crystals", "given_crystals"]
    try:
        # use a transaction
        db.cursor.execute("BEGIN IMMEDIATE")
        for col in cols:
            db.cursor.execute(f"SELECT {col} FROM users WHERE user_id = ?", (user_id,))
            r = db.cursor.fetchone()
            value = int(r[0]) if r and r[0] is not None else 0
            if value <= 0:
                continue
            deduction = min(value, remaining)
            db.cursor.execute(f"UPDATE users SET {col} = {col} - ? WHERE user_id = ?", (deduction, user_id))
            remaining -= deduction
            if remaining <= 0:
                break
        if remaining > 0:
            # something wrong (shouldn't happen if total checked), rollback
            db.conn.rollback()
            return False
        db.conn.commit()
        return True
    except Exception:
        try:
            db.conn.rollback()
        except Exception:
            pass
        return False

# helper: credit winnings (adds to given_crystals column using add_crystals)
def credit_user(user_id: int, amount: int):
    if amount <= 0:
        return
    try:
        # use given param so it increases given_crystals column
        db.add_crystals(user_id, daily=0, weekly=0, monthly=0, given=int(amount))
    except Exception:
        # fallback direct update
        try:
            db.cursor.execute("UPDATE users SET given_crystals = COALESCE(given_crystals,0) + ? WHERE user_id = ?", (int(amount), user_id))
            db.conn.commit()
        except Exception:
            pass

# ---------------- /bet command ----------------
@app.on_message(filters.command("bet"))
async def bet_cmd(client, message):
    user = message.from_user
    if not user:
        return
    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.reply_text("Usage: /bet <amount>\nExample: /bet 1000")
        return
    try:
        amount = int(parts[1])
        if amount <= 0:
            raise ValueError()
    except Exception:
        await message.reply_text("Invalid amount. Use a positive integer, e.g. /bet 1000")
        return

    balance = get_total_balance(user.id)
    if balance < amount:
        await message.reply_text(f"❌ Insufficient balance. Your balance: {balance} 💎")
        return

    # build buttons: include user id and amount so only that one can click it
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Easy (60% → 2x)", callback_data=f"bet:{user.id}:{amount}:easy"),
            InlineKeyboardButton("Medium (25% → 3x)", callback_data=f"bet:{user.id}:{amount}:medium")
        ],
        [
            InlineKeyboardButton("Hard (14% → 5x)", callback_data=f"bet:{user.id}:{amount}:hard"),
            InlineKeyboardButton("Hell (1% → 10x)", callback_data=f"bet:{user.id}:{amount}:hell")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"bet_cancel:{user.id}:{amount}")]
    ])

    txt = (
        f"🎲 Bet Menu\n\n"
        f"Player: {user.first_name} (ID: {user.id})\n"
        f"Bet Amount: {amount} 💎\n"
        f"Your Balance: {balance} 💎\n\n"
        "Choose difficulty (only you may press a button)."
    )
    await message.reply_text(txt, reply_markup=kb)

# ---------------- Cancel button ----------------
@app.on_callback_query(filters.regex(r"^bet_cancel:(\d+):(\d+)$"))
async def bet_cancel_cb(client, callback):
    try:
        uid = int(callback.matches[0].group(1))
        amt = int(callback.matches[0].group(2))
    except Exception:
        await callback.answer("Invalid cancel data.", show_alert=True)
        return

    if callback.from_user.id != uid:
        await callback.answer("This button isn't for you.", show_alert=True)
        return

    try:
        await callback.message.edit_text(f"❌ Bet cancelled by user. Bet amount: {amt} 💎")
    except Exception:
        pass
    await callback.answer("Bet cancelled.")

# ---------------- Main bet button handler ----------------
@app.on_callback_query(filters.regex(r"^bet:(\d+):(\d+):(\w+)$"))
async def bet_callback(client, callback):
    try:
        uid = int(callback.matches[0].group(1))
        amount = int(callback.matches[0].group(2))
        level = callback.matches[0].group(3)
    except Exception:
        await callback.answer("Invalid data.", show_alert=True)
        return

    # only the original user may press their button
    if callback.from_user.id != uid:
        await callback.answer("This bet button is for another user.", show_alert=True)
        return

    if level not in DIFFICULTIES:
        await callback.answer("Unknown difficulty.", show_alert=True)
        return

    label, prob, mult = DIFFICULTIES[level]

    # Re-check balance and attempt to deduct
    balance_before = get_total_balance(uid)
    if balance_before < amount:
        await callback.answer(f"❌ You don't have enough crystals. Balance: {balance_before} 💎", show_alert=True)
        try:
            await callback.message.edit_text(f"❌ Bet failed: insufficient balance ({balance_before} 💎).")
        except Exception:
            pass
        return

    # Attempt to deduct bet (transactional)
    ok = deduct_user_balance(uid, amount)
    if not ok:
        await callback.answer("❌ Failed to deduct bet (insufficient funds or DB error).", show_alert=True)
        try:
            await callback.message.edit_text("❌ Bet failed: could not deduct amount from your balance.")
        except Exception:
            pass
        return

    # Determine outcome
    roll = random.random()  # 0.0 - 1.0
    win = roll < prob
    # compute payout: if win => user receives amount * multiplier
    payout = amount * mult if win else 0

    # If win, credit payout
    if win and payout > 0:
        # add payout back (this includes returning the bet + profit)
        credit_user(uid, payout)
        result_text = f"🎉 You WON!\nDifficulty: {label}\nBet: {amount} 💎\nPayout: {payout} 💎 (x{mult})"
    else:
        result_text = f"💀 You LOST.\nDifficulty: {label}\nBet: {amount} 💎\nPayout: 0 💎"

    new_balance = get_total_balance(uid)
    result_text += f"\n\nYour new balance: {new_balance} 💎"

    # edit the message to show result (remove buttons)
    try:
        await callback.message.edit_text(f"{result_text}\n\n(roll={roll:.4f}, need<{prob:.2f} to win)")
    except Exception:
        try:
            await callback.message.reply_text(f"{result_text}\n\n(roll={roll:.4f}, need<{prob:.2f} to win)")
        except Exception:
            pass

    # short notification to pressing user
    await callback.answer("Resolved.", show_alert=False)
