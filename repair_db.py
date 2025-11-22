import sqlite3

# Database file ka naam
DB_PATH = "waifu_bot.db"

def repair_database():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        print("🔧 Database repair shuru ho raha hai...")

        # 1. Rarity Mapping (Fancy Names -> Simple Names)
        # Code mein hum simple names ("Common", "Rare") use kar rahe hain
        updates = {
            "Common Blossom": "Common",
            "Charming Glow": "Medium",
            "Elegant Rose": "Rare",
            "Rare Sparkle": "Legendary",
            "Enchanted Flame": "Limited edition",
            "Animated Spirit": "Prime",
            "Chroma Pulse": "Cosmic",
            "Mythical Grace": "Ultimate",
            "Ethereal Whisper": "God",
            "Frozen Aurora": "God",
            "Volt Resonant": "God",
            "Holographic Mirage": "God",
            "Phantom Tempest": "God",
            "Celestia Bloom": "God",
            "Divine Ascendant": "God",
            "Timewoven Relic": "God",
            "Forbidden Desire": "God",
            "Cinematic Legend": "God"
        }

        print("🔄 Rarities fix kar raha hoon...")
        count = 0
        for old, new in updates.items():
            cursor.execute("UPDATE waifu_cards SET rarity = ? WHERE rarity = ?", (new, old))
            count += cursor.rowcount
        
        print(f"✅ Total {count} cards update kiye gaye.")

        # 2. Ensure user_settings table exists (Inventory filter ke liye zaroori hai)
        print("📦 Checking tables...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                rarity_filter TEXT DEFAULT NULL,
                anime_filter TEXT DEFAULT NULL
            )
        """)

        # 3. User Waifus count correction (Optional cleanup)
        # Kabhi kabhi delete hue cards user ke paas reh jaate hain
        print("🧹 Cleaning ghost entries...")
        cursor.execute("""
            DELETE FROM user_waifus 
            WHERE waifu_id NOT IN (SELECT id FROM waifu_cards)
        """)

        conn.commit()
        print("\n🎉 Repair Complete! Ab bot restart karke /inventory check karein.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    repair_database()