"""
Evaluation Framework: Theme Auto-Detection & Piece Recognition
================================================================
Runs fen_builder.detect_best_theme() and fen_builder.build_fen() against
every image in the dataset/ directory and produces a comprehensive report.

Each image in dataset/{board_theme}/{piece_theme}.jpg is a real Chess.com
dynboard rendering of the starting position with that exact theme combination.

Metrics:
  1. Theme Detection Accuracy: Does detect_best_theme pick the correct piece theme?
  2. Piece Detection Count:    How many of the 32 pieces are detected (vs empty)?
  3. Piece Identification:     How many pieces are identified as the CORRECT type?
  4. Confusion Matrix:         Which pieces get confused with which?

Usage:
    python evaluate_detector.py [--dataset dataset] [--verbose]
"""

import cv2
import numpy as np
import os
import sys
import time
import argparse
from collections import defaultdict

# Add workspace to path
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WORKSPACE)

import fen_builder
import config

DATASET_DIR = os.path.join(WORKSPACE, "dataset")

# Ground truth: the starting position grid (row 0 = rank 8, row 7 = rank 1)
# This is what we expect to see in every dataset image.
GROUND_TRUTH_GRID = [
    "br", "bn", "bb", "bq", "bk", "bb", "bn", "br",  # rank 8
    "bp", "bp", "bp", "bp", "bp", "bp", "bp", "bp",  # rank 7
    ".",  ".",  ".",  ".",  ".",  ".",  ".",  ".",      # rank 6
    ".",  ".",  ".",  ".",  ".",  ".",  ".",  ".",      # rank 5
    ".",  ".",  ".",  ".",  ".",  ".",  ".",  ".",      # rank 4
    ".",  ".",  ".",  ".",  ".",  ".",  ".",  ".",      # rank 3
    "wp", "wp", "wp", "wp", "wp", "wp", "wp", "wp",  # rank 2
    "wr", "wn", "wb", "wq", "wk", "wb", "wn", "wr",  # rank 1
]

EXPECTED_FEN_PLACEMENT = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"


def crop_board_from_dynboard(img):
    """Crop the pure board area from a dynboard image.
    
    dynboard images may include coordinate labels around the edges.
    We need to detect and crop to just the 8x8 board area.
    The board is always the largest square region in the image.
    """
    h, w = img.shape[:2]
    # dynboard images are square and the board fills the image
    # but there may be thin coordinate borders
    # For size=3, the image is typically 720x720 with the board filling it
    # Let's try to detect the board by finding the main square region
    
    # Simple approach: the board IS the full image for dynboard (no coordinates by default)
    return img


def evaluate_single(board_theme, piece_theme, img_path, verbose=False):
    """Evaluate a single board image.
    
    Returns dict with:
      - detected_theme: what theme was auto-detected
      - theme_correct: bool
      - piece_count: how many pieces were detected (out of 32)
      - pieces_correct: how many pieces were correctly identified
      - grid: the detected grid
      - fen: the detected FEN string
      - confusions: list of (expected, got) for misidentified pieces
    """
    img = cv2.imread(img_path)
    if img is None:
        return None
    
    board_img = crop_board_from_dynboard(img)
    
    # Step 1: Theme detection
    # We need to reset the theme detection state for each test
    fen_builder._theme_auto_detected = False
    fen_builder._all_theme_templates.clear()
    fen_builder._color_templates.clear()
    
    detected_theme = fen_builder.detect_best_theme(board_img)
    theme_correct = (detected_theme == piece_theme)
    
    # Step 2: Load the CORRECT theme templates (to test piece identification independently)
    templates = fen_builder.load_templates(piece_theme)
    
    # Step 3: Build FEN
    fen_builder._prev_square_hashes = None
    fen_builder._prev_grid_cache = None
    
    try:
        result = fen_builder.build_fen(board_img, templates, None)
        fen_str, grid, is_flipped, active, orient_src, piece_count, matched = result
    except Exception as e:
        if verbose:
            print(f"    ERROR in build_fen: {e}")
        return {
            "detected_theme": detected_theme,
            "theme_correct": theme_correct,
            "piece_count": 0,
            "pieces_correct": 0,
            "grid": ["."] * 64,
            "fen": None,
            "confusions": [],
            "error": str(e),
        }
    
    # Step 4: Compare grid to ground truth
    pieces_correct = 0
    confusions = []
    detected_as_piece = 0
    
    for i in range(64):
        expected = GROUND_TRUTH_GRID[i]
        got = grid[i] if i < len(grid) else "."
        
        if expected == ".":
            # Empty square — correct if also empty
            if got == ".":
                pieces_correct += 1
            else:
                confusions.append((expected, got, i))
        else:
            # Piece square
            detected_as_piece += 1 if got != "." else 0
            if got == expected:
                pieces_correct += 1
            else:
                confusions.append((expected, got, i))
    
    return {
        "detected_theme": detected_theme,
        "theme_correct": theme_correct,
        "piece_count": detected_as_piece,
        "pieces_correct": pieces_correct,
        "grid": grid,
        "fen": fen_str,
        "confusions": confusions,
    }


def run_evaluation(dataset_dir, verbose=False):
    """Run full evaluation across all images in the dataset."""
    
    if not os.path.isdir(dataset_dir):
        print(f"Dataset directory not found: {dataset_dir}")
        return
    
    board_themes = sorted([d for d in os.listdir(dataset_dir) 
                          if os.path.isdir(os.path.join(dataset_dir, d))])
    
    if not board_themes:
        print("No board theme directories found in dataset.")
        return
    
    print("=" * 80)
    print("EVALUATION: Theme Auto-Detection & Piece Recognition")
    print("=" * 80)
    print(f"Dataset: {dataset_dir}")
    print(f"Board themes: {len(board_themes)}")
    print()
    
    # Collect results
    all_results = []
    theme_accuracy = defaultdict(lambda: {"correct": 0, "total": 0})
    piece_accuracy_by_theme = defaultdict(lambda: {"detected": 0, "correct": 0, "total": 0})
    piece_accuracy_by_board = defaultdict(lambda: {"detected": 0, "correct": 0, "total": 0})
    confusion_matrix = defaultdict(int)  # (expected, got) -> count
    
    total_images = 0
    for bt in board_themes:
        board_dir = os.path.join(dataset_dir, bt)
        for f in os.listdir(board_dir):
            if f.endswith(".jpg") or f.endswith(".png"):
                total_images += 1
    
    processed = 0
    start_time = time.time()
    
    for bt in board_themes:
        board_dir = os.path.join(dataset_dir, bt)
        piece_files = sorted([f for f in os.listdir(board_dir) 
                             if f.endswith(".jpg") or f.endswith(".png")])
        
        for pf in piece_files:
            pt = os.path.splitext(pf)[0]  # piece theme name from filename
            img_path = os.path.join(board_dir, pf)
            processed += 1
            
            sys.stdout.write(f"\r  [{processed}/{total_images}] {bt}/{pt}...        ")
            sys.stdout.flush()
            
            result = evaluate_single(bt, pt, img_path, verbose)
            if result is None:
                continue
            
            result["board_theme"] = bt
            result["piece_theme"] = pt
            all_results.append(result)
            
            # Theme accuracy
            theme_accuracy[pt]["total"] += 1
            if result["theme_correct"]:
                theme_accuracy[pt]["correct"] += 1
            
            # Piece accuracy by piece theme
            piece_accuracy_by_theme[pt]["detected"] += result["piece_count"]
            piece_accuracy_by_theme[pt]["correct"] += result["pieces_correct"]
            piece_accuracy_by_theme[pt]["total"] += 64  # 64 squares
            
            # Piece accuracy by board theme
            piece_accuracy_by_board[bt]["detected"] += result["piece_count"]
            piece_accuracy_by_board[bt]["correct"] += result["pieces_correct"]
            piece_accuracy_by_board[bt]["total"] += 64
            
            # Confusion matrix
            for expected, got, idx in result["confusions"]:
                confusion_matrix[(expected, got)] += 1
            
            if verbose and not result["theme_correct"]:
                print(f"\n    WRONG THEME: {bt}/{pt} -> detected '{result['detected_theme']}'")
    
    elapsed = time.time() - start_time
    print(f"\r  Evaluation complete! ({elapsed:.1f}s for {processed} images)          ")
    print()
    
    # ===== REPORT =====
    print("=" * 80)
    print("REPORT: Theme Detection Accuracy")
    print("=" * 80)
    print(f"{'Piece Theme':<20} {'Correct':<10} {'Total':<10} {'Accuracy':<10} {'Status'}")
    print("-" * 65)
    
    total_correct = 0
    total_total = 0
    for pt in sorted(theme_accuracy.keys()):
        data = theme_accuracy[pt]
        acc = data["correct"] / max(data["total"], 1)
        total_correct += data["correct"]
        total_total += data["total"]
        status = "PASS" if acc >= 0.8 else "WARN" if acc >= 0.5 else "FAIL"
        print(f"{pt:<20} {data['correct']:<10} {data['total']:<10} {acc:<10.1%} {status}")
    
    overall_theme_acc = total_correct / max(total_total, 1)
    print("-" * 65)
    print(f"{'OVERALL':<20} {total_correct:<10} {total_total:<10} {overall_theme_acc:<10.1%}")
    print()
    
    # Piece detection by piece theme
    print("=" * 80)
    print("REPORT: Piece Detection by Piece Theme (out of 32 pieces per image)")
    print("=" * 80)
    print(f"{'Piece Theme':<20} {'Avg Detected':<15} {'Avg Correct':<15} {'Sq Accuracy':<12}")
    print("-" * 65)
    
    for pt in sorted(piece_accuracy_by_theme.keys()):
        data = piece_accuracy_by_theme[pt]
        n_images = theme_accuracy[pt]["total"]
        avg_det = data["detected"] / max(n_images, 1)
        avg_corr = data["correct"] / max(n_images, 1)
        sq_acc = data["correct"] / max(data["total"], 1)
        print(f"{pt:<20} {avg_det:<15.1f} {avg_corr:<15.1f} {sq_acc:<12.1%}")
    print()
    
    # Piece detection by board theme
    print("=" * 80)
    print("REPORT: Piece Detection by Board Theme")
    print("=" * 80)
    print(f"{'Board Theme':<20} {'Avg Detected':<15} {'Avg Correct':<15} {'Sq Accuracy':<12}")
    print("-" * 65)
    
    for bt in sorted(piece_accuracy_by_board.keys()):
        data = piece_accuracy_by_board[bt]
        n_images = sum(1 for r in all_results if r["board_theme"] == bt)
        avg_det = data["detected"] / max(n_images, 1)
        avg_corr = data["correct"] / max(n_images, 1)
        sq_acc = data["correct"] / max(data["total"], 1)
        print(f"{bt:<20} {avg_det:<15.1f} {avg_corr:<15.1f} {sq_acc:<12.1%}")
    print()
    
    # Top confusions
    print("=" * 80)
    print("REPORT: Top 20 Piece Confusions (Expected -> Got)")
    print("=" * 80)
    sorted_conf = sorted(confusion_matrix.items(), key=lambda x: -x[1])[:20]
    if sorted_conf:
        print(f"{'Expected':<12} {'Got':<12} {'Count':<10}")
        print("-" * 35)
        for (expected, got), count in sorted_conf:
            print(f"{expected:<12} {got:<12} {count:<10}")
    else:
        print("No confusions found! Perfect detection.")
    print()
    
    # Worst combinations
    print("=" * 80)
    print("REPORT: Worst 10 Combinations (by square accuracy)")
    print("=" * 80)
    scored = [(r["pieces_correct"] / 64, r) for r in all_results]
    scored.sort(key=lambda x: x[0])
    print(f"{'Board':<15} {'Piece':<15} {'Detected':<10} {'Correct/64':<12} {'Theme Det':<15}")
    print("-" * 70)
    for acc, r in scored[:10]:
        det_theme = r["detected_theme"]
        theme_mark = "OK" if r["theme_correct"] else f"WRONG({det_theme})"
        print(f"{r['board_theme']:<15} {r['piece_theme']:<15} {r['piece_count']:<10} {r['pieces_correct']:<12} {theme_mark}")
    
    print()
    print("=" * 80)
    print(f"SUMMARY: Theme accuracy={overall_theme_acc:.1%}, "
          f"Evaluated {len(all_results)} images in {elapsed:.1f}s")
    print("=" * 80)
    
    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate theme detection and piece recognition")
    parser.add_argument("--dataset", type=str, default=DATASET_DIR,
                        help=f"Dataset directory (default: {DATASET_DIR})")
    parser.add_argument("--verbose", action="store_true",
                        help="Print detailed per-image results")
    
    args = parser.parse_args()
    run_evaluation(args.dataset, args.verbose)
