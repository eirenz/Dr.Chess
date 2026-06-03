"""
Download ALL Chess.com piece and board themes from GitHub.
Source: https://github.com/GiorgioMegrelli/chess.com-boards-and-pieces

Downloads 38 piece themes (12 images each) and 30 board themes.
Skips files that already exist locally.
"""

import requests
import os
import sys

# Workspace paths
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
PIECES_DIR = os.path.join(WORKSPACE_DIR, "pieces")
BOARDS_DIR = os.path.join(WORKSPACE_DIR, "boards")

API_BASE = "https://api.github.com/repos/GiorgioMegrelli/chess.com-boards-and-pieces/contents"
RAW_BASE = "https://raw.githubusercontent.com/GiorgioMegrelli/chess.com-boards-and-pieces/master"

PIECE_FILES = ["bb", "bk", "bn", "bp", "bq", "br", "wb", "wk", "wn", "wp", "wq", "wr"]

def fetch_json(url):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
        print(f"Failed to fetch {url} (HTTP {r.status_code})")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return []

def download_file(url, filepath):
    if os.path.exists(filepath):
        return True # Already downloaded
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(r.content)
            return True
    except:
        pass
    return False

def download_themes():
    os.makedirs(PIECES_DIR, exist_ok=True)
    os.makedirs(BOARDS_DIR, exist_ok=True)
    
    print("Fetching list of Piece themes from GitHub...")
    pieces_data = fetch_json(f"{API_BASE}/pieces")
    piece_themes = [item['name'] for item in pieces_data if item['type'] == 'dir']
    
    print("Fetching list of Board themes from GitHub...")
    boards_data = fetch_json(f"{API_BASE}/boards")
    board_themes = [item['name'] for item in boards_data if item['type'] == 'file' and item['name'].endswith('.png')]
    
    print(f"\nFound {len(piece_themes)} Piece Themes and {len(board_themes)} Board Themes.")
    
    # 1. Download Piece Themes
    print(f"\n--- Downloading Piece Themes (saving to {PIECES_DIR}) ---")
    for i, theme in enumerate(piece_themes, 1):
        theme_dir = os.path.join(PIECES_DIR, theme)
        os.makedirs(theme_dir, exist_ok=True)
        
        # Check completion
        existing = [f for f in os.listdir(theme_dir) if f.endswith(".png")]
        if len(existing) >= 12:
            print(f"[{i}/{len(piece_themes)}] {theme}: Already complete (Skipping)")
            continue
            
        success = 0
        sys.stdout.write(f"[{i}/{len(piece_themes)}] {theme}: Downloading... ")
        sys.stdout.flush()
        
        for piece in PIECE_FILES:
            filename = f"{piece}.png"
            filepath = os.path.join(theme_dir, filename)
            url = f"{RAW_BASE}/pieces/{theme}/{filename}"
            if download_file(url, filepath):
                success += 1
                
        print(f"{success}/12 pieces OK")

    # 2. Download Board Themes
    print(f"\n--- Downloading Board Themes (saving to {BOARDS_DIR}) ---")
    for i, board_img in enumerate(board_themes, 1):
        filepath = os.path.join(BOARDS_DIR, board_img)
        url = f"{RAW_BASE}/boards/{board_img}"
        
        if os.path.exists(filepath):
            print(f"[{i}/{len(board_themes)}] {board_img}: Already exists (Skipping)")
            continue
            
        sys.stdout.write(f"[{i}/{len(board_themes)}] {board_img}: Downloading... ")
        sys.stdout.flush()
        
        if download_file(url, filepath):
            print("OK")
        else:
            print("FAILED")

    print("\nDownload complete! All assets are saved in the workspace.")

if __name__ == "__main__":
    download_themes()
