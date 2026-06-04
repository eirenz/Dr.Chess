import requests
import os
import sys

PIECES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pieces")
PIECE_FILES = ["bb", "bk", "bn", "bp", "bq", "br", "wb", "wk", "wn", "wp", "wq", "wr"]

def fetch_json(url):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []

def download_cdn_pieces():
    print("Fetching list of Piece themes from GitHub (to get the list of folder names)...")
    API_BASE = "https://api.github.com/repos/GiorgioMegrelli/chess.com-boards-and-pieces/contents"
    pieces_data = fetch_json(f"{API_BASE}/pieces")
    piece_themes = [item['name'] for item in pieces_data if item['type'] == 'dir']
    
    # Also explicitly add known themes just in case they are missing from github
    for known in ['3d_staunton', 'classic', 'icy_sea', 'neo', 'alpha', 'neo_wood', 'marble', '3d_chesskid', '3d_plastic', '3d_wood', 'tournament', 'wood', 'metal']:
        if known not in piece_themes:
            piece_themes.append(known)

    print(f"Found {len(piece_themes)} Piece Themes. Downloading from Chess.com CDN...")
    os.makedirs(PIECES_DIR, exist_ok=True)
    
    for i, theme in enumerate(piece_themes, 1):
        theme_dir = os.path.join(PIECES_DIR, theme)
        os.makedirs(theme_dir, exist_ok=True)
        
        sys.stdout.write(f"[{i}/{len(piece_themes)}] {theme}: ")
        sys.stdout.flush()
        
        success = 0
        for piece in PIECE_FILES:
            filename = f"{piece}.png"
            filepath = os.path.join(theme_dir, filename)
            url = f"https://images.chesscomfiles.com/chess-themes/pieces/{theme}/150/{filename}"
            
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    with open(filepath, "wb") as f:
                        f.write(r.content)
                    success += 1
            except:
                pass
                
        print(f"{success}/12 pieces downloaded")

if __name__ == "__main__":
    download_cdn_pieces()
