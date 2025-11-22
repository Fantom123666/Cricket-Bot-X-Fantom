# database.py

import sqlite3
from config import Config
from datetime import datetime
import os

DEFAULT_WAIFU_IMAGE = "photo_2025-08-29_13-53-48.jpg"

class Database:
    def __init__(self, db_path=Config.DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.setup()
        self.setup_profile_tables()
        self.setup_additional_tables()
        self.ensure_waifu_cards_schema()
        self.ensure_default_waifu_image()

    # ---------------- Setup ----------------
    def setup(self):
        """Create users, groups, logs tables and ensure columns exist"""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                language TEXT DEFAULT 'en',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                daily_crystals INTEGER DEFAULT 0,
                weekly_crystals INTEGER DEFAULT 0,
                monthly_crystals INTEGER DEFAULT 0,
                daily_claim TEXT,
                weekly_claim TEXT,
                monthly_claim TEXT,
                first_logged INTEGER DEFAULT 0,
                store_refresh_claim TEXT
            )
        """)
        self.conn.commit()

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT,
                user_id INTEGER,
                chat_id INTEGER,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

        # Ensure legacy columns exist
        for col in ["daily_claim", "weekly_claim", "monthly_claim", "first_logged", "store_refresh_claim"]:
            self._add_missing_column(col)

    def _add_missing_column(self, column_name):
        self.cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in self.cursor.fetchall()]
        if column_name not in columns:
            if column_name == "first_logged":
                self.cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} INTEGER DEFAULT 0")
            else:
                self.cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} TEXT")
            self.conn.commit()

    # ---------------- Additional Tables ----------------
    def setup_additional_tables(self):
        """Create inventory table and given_crystals column"""
        self.cursor.execute("PRAGMA table_info(users)")
        cols = [c[1] for c in self.cursor.fetchall()]
        if "given_crystals" not in cols:
            self.cursor.execute("ALTER TABLE users ADD COLUMN given_crystals INTEGER DEFAULT 0")
            self.conn.commit()

        # User inventory table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_waifus (
                user_id INTEGER,
                waifu_id INTEGER,
                amount INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, waifu_id)
            )
        """)
        
        # ✅ FIX: User Fav table yahan add kiya hai
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_fav (
                user_id INTEGER PRIMARY KEY,
                waifu_id INTEGER
            )
        """)
        self.conn.commit()

    # ---------------- User Management ----------------
    def add_user(self, user_id, username=None, first_name=None):
        self.cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
        """, (user_id, username, first_name))
        self.conn.commit()

    def is_first_logged(self, user_id):
        self.cursor.execute("SELECT first_logged FROM users WHERE user_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row[0] == 1 if row else False

    def set_first_logged(self, user_id):
        self.cursor.execute("UPDATE users SET first_logged = 1 WHERE user_id = ?", (user_id,))
        self.conn.commit()

    # ---------------- Crystal Management ----------------
    def add_crystals(self, user_id, daily=0, weekly=0, monthly=0, given=0):
        self.add_user(user_id)
        self.cursor.execute("""
            UPDATE users SET
                daily_crystals = daily_crystals + ?,
                weekly_crystals = weekly_crystals + ?,
                monthly_crystals = monthly_crystals + ?,
                given_crystals = given_crystals + ?
            WHERE user_id = ?
        """, (int(daily), int(weekly), int(monthly), int(given), user_id))
        self.conn.commit()

    def get_crystals(self, user_id):
        self.cursor.execute("""
            SELECT daily_crystals, weekly_crystals, monthly_crystals,
                   daily_claim, weekly_claim, monthly_claim, given_crystals
            FROM users WHERE user_id=?
        """, (user_id,))
        row = self.cursor.fetchone()
        if not row:
            return (0, 0, 0, 0, None, 0)
        daily, weekly, monthly, daily_c, weekly_c, monthly_c, given = row
        total = daily + weekly + monthly + given
        timestamps = [ts for ts in [daily_c, weekly_c, monthly_c] if ts]
        last_claim = max(timestamps) if timestamps else None
        return (daily, weekly, monthly, total, last_claim, given)

    def get_last_claim(self, user_id, claim_type):
        col = f"{claim_type}_claim"
        self.cursor.execute(f"SELECT {col} FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def update_last_claim(self, user_id, claim_type, time_iso):
        col = f"{claim_type}_claim"
        self.cursor.execute(f"UPDATE users SET {col} = ? WHERE user_id = ?", (time_iso, user_id))
        self.conn.commit()

    # ---------------- Purchase / Inventory ----------------
    def purchase_waifu(self, user_id, waifu_id, price=0):
        """Deduct crystals proportionally and add waifu safely"""
        self.add_user(user_id)
        daily, weekly, monthly, total, last_claim, given = self.get_crystals(user_id)
        if total < price:
            return False

        remaining = price
        for col in ["daily_crystals", "weekly_crystals", "monthly_crystals", "given_crystals"]:
            self.cursor.execute(f"SELECT {col} FROM users WHERE user_id=?", (user_id,))
            value = int(self.cursor.fetchone()[0])
            deduction = min(value, remaining)
            self.cursor.execute(f"UPDATE users SET {col} = {col} - ? WHERE user_id=?", (deduction, user_id))
            remaining -= deduction
            if remaining <= 0:
                break

        # Safe inventory addition
        self.cursor.execute("SELECT amount FROM user_waifus WHERE user_id=? AND waifu_id=?", (user_id, waifu_id))
        row = self.cursor.fetchone()
        if row:
            self.cursor.execute("UPDATE user_waifus SET amount = amount + 1 WHERE user_id=? AND waifu_id=?", (user_id, waifu_id))
        else:
            self.cursor.execute("INSERT INTO user_waifus (user_id, waifu_id, amount) VALUES (?, ?, 1)", (user_id, waifu_id))

        self.conn.commit()
        return True

    # ---------------- Groups / Logs ----------------
    def add_group(self, chat_id, title):
        self.cursor.execute("""
            INSERT OR IGNORE INTO groups (chat_id, title)
            VALUES (?, ?)
        """, (chat_id, title))
        self.conn.commit()

    def get_total_groups(self):
        self.cursor.execute("SELECT COUNT(*) FROM groups")
        return self.cursor.fetchone()[0]

    def log_event(self, event_type, user_id=None, chat_id=None, details=None):
        self.cursor.execute("""
            INSERT INTO logs (event_type, user_id, chat_id, details)
            VALUES (?, ?, ?, ?)
        """, (event_type, user_id, chat_id, details))
        self.conn.commit()

    # ---------------- Profile System ----------------
    def setup_profile_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 1,
                rank TEXT DEFAULT 'Newbie',
                badge TEXT DEFAULT 'None',
                total_collected INTEGER DEFAULT 0,
                progress INTEGER DEFAULT 0,
                balance INTEGER DEFAULT 0,
                global_position TEXT DEFAULT 'Unranked',
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_rarities (
                user_id INTEGER,
                rarity TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, rarity),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        self.conn.commit()

    # ---------------- WAIFU CARDS ----------------
    def ensure_waifu_cards_schema(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS waifu_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                anime TEXT,
                rarity TEXT,
                event TEXT,
                media_type TEXT,
                media_file TEXT,
                media_file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def ensure_default_waifu_image(self):
        """Set default image if media_file or media_file_id is empty"""
        self.cursor.execute("UPDATE waifu_cards SET media_file=? WHERE media_file IS NULL OR media_file=''", (DEFAULT_WAIFU_IMAGE,))
        self.cursor.execute("UPDATE waifu_cards SET media_file_id=? WHERE media_file_id IS NULL OR media_file_id=''", (DEFAULT_WAIFU_IMAGE,))
        self.conn.commit()


    # ---------------- Close ----------------
    def close(self):
        self.conn.close()