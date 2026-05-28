"""
Download popular Chess.com piece themes from GitHub.
Source: https://github.com/GiorgioMegrelli/chess.com-boards-and-pieces

Downloads 15 of the most popular 2D themes (~300KB total).
Skips themes that already exist locally.
"""

import requests
import os

PIECES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pieces")

BASE_URL = "https://raw.githubusercontent.com/GiorgioMegrelli/chess.com-boards-and-pieces/master/pieces"

PIECE_FILES = ["bb", "bk", "bn", "bp", "bq", "br", "wb", "wk", "wn", "wp", "wq", "wr"]

# Top 15 most popular 2D Chess.com piece themes
THEMES_TO_DOWNLOAD = [
    "neo",        # Default Chess.com theme
    "classic",    # Most popular alternative
    "neo_wood",   # Popular variant of neo
    "wood",       # Traditional players
    "glass",      # Popular modern look
    "metal",      # Commonly used
    "modern",     # Clean minimal style
    "tournament", # Serious/competitive players
    "bases",      # Common alternative
    "ocean",      # Popular themed set
    "marble",     # Premium style
    "vintage",    # Nostalgic players
    "club",       # Club environment
    "book",       # Classic book style
    "alpha",      # Clean design
]


def download_themes():
    os.makedirs(PIECES_DIR, exist_ok=True)
    
    total_downloaded = 0
    total_skipped = 0
    
    for theme in THEMES_TO_DOWNLOAD:
        theme_dir = os.path.join(PIECES_DIR, theme)
        
        # Check if theme already has all 12 pieces
        if os.path.isdir(theme_dir):
            existing = [f for f in os.listdir(theme_dir) if f.endswith(".png")]
            if len(existing) >= 12:
                print(f"  [SKIP] {theme}: already complete ({len(existing)} pieces)")
                total_skipped += 1
                continue
        
        os.makedirs(theme_dir, exist_ok=True)
        success = 0
        failed = 0
        
        for piece in PIECE_FILES:
            filename = f"{piece}.png"
            filepath = os.path.join(theme_dir, filename)
            
            if os.path.exists(filepath):
                success += 1
                continue
            
            url = f"{BASE_URL}/{theme}/{filename}"
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    with open(filepath, "wb") as f:
                        f.write(r.content)
                    success += 1
                else:
                    print(f"    [FAIL] {theme}/{filename} -- HTTP {r.status_code}")
                    failed += 1
            except Exception as e:
                print(f"    [FAIL] {theme}/{filename} -- {e}")
                failed += 1
        
        if failed == 0:
            print(f"  [OK] {theme}: {success} pieces downloaded")
            total_downloaded += 1
        else:
            print(f"  [WARN] {theme}: {success} OK, {failed} failed")
            total_downloaded += 1
    
    print(f"\nDone! Downloaded: {total_downloaded}, Skipped: {total_skipped}")
    print(f"Themes available in: {PIECES_DIR}")


if __name__ == "__main__":
    print("Downloading Chess.com piece themes...\n")
    download_themes()
