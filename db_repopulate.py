import asyncio
import aiosqlite
import json

# Configuration
DATABASE_PATH = "./database/database.db"

async def repopulate_from_json():
    """Repopulate card_variants table from card_urls.json"""
    try:
        with open("card_urls.json", "r") as f:
            card_data = json.load(f)
    except Exception as e:
        print(f"Error loading JSON file: {e}")
        return

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        
        # Clear existing variants using truncate optimization
        await db.execute("DELETE FROM card_variants")
        
        # Reset autoincrement counter (SQLite specific)
        await db.execute("DELETE FROM sqlite_sequence WHERE name='card_variants'")

        # Insert new variants
        for card in card_data:
            try:
                await db.executemany(
                    """INSERT INTO card_variants (
                        card_id, 
                        holo_type, 
                        signature_type, 
                        image_url
                    ) VALUES (?, ?, ?, ?)""",
                    [
                        (card["id"], 0, 0, card["base"]),
                        (card["id"], 1, 0, card["holo"]),
                        (card["id"], 0, 1, card["signed"]),
                        (card["id"], 0, 2, card["golden_signed"]),
                        (card["id"], 1, 1, card["holo_signed"]),
                        (card["id"], 1, 2, card["holo_golden_signed"])
                    ]
                )
            except KeyError as e:
                print(f"Missing key in card {card.get('id', 'unknown')}: {e}")
            except Exception as e:
                print(f"Error inserting card {card.get('id', 'unknown')}: {e}")

        await db.commit()
        print(f"Successfully inserted {len(card_data)*6} variants")

# Run the repopulation
asyncio.run(repopulate_from_json())