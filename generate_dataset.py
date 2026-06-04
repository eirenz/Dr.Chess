"""
Dataset Generator: Chess.com dynboard API
==========================================
Downloads real-world rendered board screenshots from Chess.com's dynboard endpoint
for every combination of piece theme × board theme we have locally.

This gives us ACTUAL browser-rendered images (with proper anti-aliasing, shadows,
3D effects) instead of synthetic composites, which is critical for testing the
overlay's auto-detection against what users actually see.

Usage:
    python generate_dataset.py [--pieces neo,classic] [--boards walnut,green] [--size 3]
    
Output:
    dataset/
      walnut/
        neo.jpg
        classic.jpg
        3d_staunton.jpg
        ...
      green/
        neo.jpg
        ...
"""

import requests
import os
import sys
import time
import argparse

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(WORKSPACE, "dataset")
PIECES_DIR = os.path.join(WORKSPACE, "pieces")
BOARDS_DIR = os.path.join(WORKSPACE, "boards")

# Starting position FEN (always test with full 32-piece board for maximum signal)
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"

DYNBOARD_URL = "https://www.chess.com/dynboard"


def get_local_piece_themes():
    """Get all piece theme names from local pieces/ directory."""
    if not os.path.isdir(PIECES_DIR):
        return []
    return sorted([
        d for d in os.listdir(PIECES_DIR)
        if os.path.isdir(os.path.join(PIECES_DIR, d)) and d != "blindfold"
    ])


def get_local_board_themes():
    """Get all board theme names from local boards/ directory."""
    if not os.path.isdir(BOARDS_DIR):
        return []
    return sorted([
        os.path.splitext(f)[0] for f in os.listdir(BOARDS_DIR)
        if f.endswith(".png") and f != "overlay.png"
    ])


def download_board_image(piece_theme, board_theme, size=3):
    """Download a rendered board image from Chess.com dynboard API.
    
    Args:
        piece_theme: Chess.com piece theme name (e.g., 'neo', '3d_staunton')
        board_theme: Chess.com board theme name (e.g., 'walnut', 'green')
        size: Image size multiplier (2=small, 3=medium, 4=large)
    
    Returns:
        bytes of the image, or None on failure.
    """
    params = {
        "fen": START_FEN,
        "board": board_theme,
        "piece": piece_theme,
        "size": str(size),
    }
    try:
        r = requests.get(DYNBOARD_URL, params=params, timeout=15)
        if r.status_code == 200 and len(r.content) > 5000:
            return r.content
    except Exception as e:
        pass
    return None


def generate_dataset(piece_themes=None, board_themes=None, size=3):
    """Generate the full dataset of board screenshots.
    
    Args:
        piece_themes: List of piece theme names, or None for all local themes.
        board_themes: List of board theme names, or None for all local themes.
        size: dynboard size parameter.
    """
    if piece_themes is None:
        piece_themes = get_local_piece_themes()
    if board_themes is None:
        board_themes = get_local_board_themes()
    
    total = len(piece_themes) * len(board_themes)
    print(f"Generating dataset: {len(piece_themes)} piece themes x {len(board_themes)} board themes = {total} combinations")
    print(f"Output directory: {DATASET_DIR}")
    print()
    
    os.makedirs(DATASET_DIR, exist_ok=True)
    
    success = 0
    skipped = 0
    failed = 0
    failed_combos = []
    
    for bi, bt in enumerate(board_themes, 1):
        board_dir = os.path.join(DATASET_DIR, bt)
        os.makedirs(board_dir, exist_ok=True)
        
        for pi, pt in enumerate(piece_themes, 1):
            idx = (bi - 1) * len(piece_themes) + pi
            filepath = os.path.join(board_dir, f"{pt}.jpg")
            
            # Skip if already downloaded
            if os.path.exists(filepath) and os.path.getsize(filepath) > 5000:
                skipped += 1
                continue
            
            sys.stdout.write(f"\r  [{idx}/{total}] {bt}/{pt}...        ")
            sys.stdout.flush()
            
            img_data = download_board_image(pt, bt, size)
            if img_data:
                with open(filepath, "wb") as f:
                    f.write(img_data)
                success += 1
            else:
                failed += 1
                failed_combos.append(f"{bt}/{pt}")
            
            # Be polite to Chess.com servers
            time.sleep(0.3)
        
        print(f"\r  Board '{bt}': done ({bi}/{len(board_themes)})            ")
    
    print(f"\n{'='*60}")
    print(f"Dataset generation complete!")
    print(f"  Success:  {success}")
    print(f"  Skipped:  {skipped} (already existed)")
    print(f"  Failed:   {failed}")
    if failed_combos:
        print(f"  Failed combos: {failed_combos[:10]}{'...' if len(failed_combos) > 10 else ''}")
    print(f"  Output:   {DATASET_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate chess board dataset from Chess.com dynboard API")
    parser.add_argument("--pieces", type=str, default=None,
                        help="Comma-separated list of piece themes (default: all local)")
    parser.add_argument("--boards", type=str, default=None,
                        help="Comma-separated list of board themes (default: all local)")
    parser.add_argument("--size", type=int, default=3,
                        help="Image size multiplier (default: 3)")
    
    args = parser.parse_args()
    
    pieces = args.pieces.split(",") if args.pieces else None
    boards = args.boards.split(",") if args.boards else None
    
    generate_dataset(pieces, boards, args.size)
