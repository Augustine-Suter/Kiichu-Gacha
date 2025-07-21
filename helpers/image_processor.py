import os
import requests
import asyncio
import time
import base64
from PIL import Image
import aiosqlite
import json

# Base directory (root of the project)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAYS_DIR = os.path.join(BASE_DIR, "overlays")
CARDS_DIR = os.path.join(BASE_DIR, "cards")
DATABASE_PATH = os.path.join(BASE_DIR, "database", "database.db")

# ImgBB Configuration
IMG_BB_API_URL = "https://api.imgbb.com/1/upload"
IMG_BB_API_KEY = "4904ff8e85a665874e744822e5626ee4"  # Replace with your actual key

# Paths for overlay assets
BORDER_OVERLAY_PATH = os.path.join(OVERLAYS_DIR, "border.png")
HOLO_OVERLAY_PATH = os.path.join(OVERLAYS_DIR, "holo_overlay.png")
SIGNATURE_OVERLAY_PATH = os.path.join(OVERLAYS_DIR, "regular_signature.png")
GOLDEN_SIGNATURE_OVERLAY_PATH = os.path.join(OVERLAYS_DIR, "golden_signature.png")

def generate_card_variations():
    """Main function to generate card variations."""
    os.makedirs(CARDS_DIR, exist_ok=True)

    # Validate overlay files
    required_files = {
        "Border": BORDER_OVERLAY_PATH,
        "Holo": HOLO_OVERLAY_PATH,
        "Signature": SIGNATURE_OVERLAY_PATH,
        "Golden Signature": GOLDEN_SIGNATURE_OVERLAY_PATH
    }
    for name, path in required_files.items():
        if not os.path.exists(path):
            raise FileNotFoundError(f"{name} overlay missing: {path}")

    # Load overlays
    overlays = {
        "border": Image.open(BORDER_OVERLAY_PATH).convert("RGBA"),
        "holo": Image.open(HOLO_OVERLAY_PATH).convert("RGBA"),
        "signature": Image.open(SIGNATURE_OVERLAY_PATH).convert("RGBA"),
        "golden_signature": Image.open(GOLDEN_SIGNATURE_OVERLAY_PATH).convert("RGBA")
    }

    async def process_cards():
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("SELECT id, image_url FROM cards ORDER BY id")
            cards = await cursor.fetchall()
            card_data = []
            
            for card_index, (card_id, image_url) in enumerate(cards):
                try:
                    card_name = f"card_{card_id}"
                    print(f"\nProcessing card {card_id}...")
                    
                    # Process base image
                    base_image = await get_base_image(image_url, card_name)
                    if not base_image:
                        continue
                    
                    # Apply border overlay
                    bordered_image = Image.alpha_composite(base_image, overlays["border"])
                    bordered_image.save(os.path.join(CARDS_DIR, f"{card_name}_bordered.png"))
                    
                    # Generate variants
                    variants = generate_variants(bordered_image, overlays)
                    
                    # Upload with rate limiting
                    variant_urls = {}
                    for var_name, var_image in variants.items():
                        if card_index > 0:
                            time.sleep(1.5)  # Rate limiting
                        path = save_variant(var_image, card_name, var_name)
                        url = upload_to_imgbb(path)
                        if url:
                            variant_urls[var_name] = url
                            print(f"Uploaded {var_name}: {url}")
                        else:
                            print(f"Failed to upload {var_name}")
                    
                    card_data.append({"id": card_id, **variant_urls})

                except Exception as e:
                    print(f"Error processing card {card_id}: {str(e)}")
            
            # Save results
            with open(os.path.join(BASE_DIR, "card_urls.json"), "w") as f:
                json.dump(card_data, f, indent=4)
            print(f"\nSuccessfully processed {len(card_data)} cards!")

    asyncio.run(process_cards())

async def get_base_image(image_url: str, card_name: str) -> Image.Image:
    """Download or load base image with retries"""
    base_path = os.path.join(CARDS_DIR, f"{card_name}_base.png")
    if os.path.exists(base_path):
        return Image.open(base_path).convert("RGBA")
    
    try:
        response = requests.get(image_url, stream=True, timeout=10)
        response.raise_for_status()
        base_image = Image.open(response.raw).convert("RGBA")
        base_image.save(base_path)
        return base_image
    except Exception as e:
        print(f"Failed to download base image: {str(e)}")
        return None

def generate_variants(bordered_image: Image.Image, overlays: dict) -> dict:
    """Generate all card variants from bordered base image"""
    return {
        "base": bordered_image,
        "holo": Image.alpha_composite(bordered_image, overlays["holo"]),
        "signed": Image.alpha_composite(bordered_image, overlays["signature"]),
        "golden_signed": Image.alpha_composite(bordered_image, overlays["golden_signature"]),
        "holo_signed": Image.alpha_composite(
            Image.alpha_composite(bordered_image, overlays["holo"]),
            overlays["signature"]
        ),
        "holo_golden_signed": Image.alpha_composite(
            Image.alpha_composite(bordered_image, overlays["holo"]),
            overlays["golden_signature"]
        )
    }

def save_variant(image: Image.Image, card_name: str, variant: str) -> str:
    """Save variant image to disk"""
    filename = f"{card_name}_{variant}.png"
    path = os.path.join(CARDS_DIR, filename)
    image.save(path)
    return path

def upload_to_imgbb(image_path: str) -> str:
    """Upload image to ImgBB with API key"""
    try:
        with open(image_path, "rb") as file:
            base64_image = base64.b64encode(file.read()).decode("utf-8")
        
        response = requests.post(
            IMG_BB_API_URL,
            data={
                "key": IMG_BB_API_KEY,
                "image": base64_image,
                "name": os.path.basename(image_path)
            },
            timeout=15
        )
        response.raise_for_status()
        return response.json()["data"]["url"]
    except Exception as e:
        print(f"Upload failed for {os.path.basename(image_path)}: {str(e)}")
        return None

if __name__ == "__main__":
    generate_card_variations()