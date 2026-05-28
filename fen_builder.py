import cv2
import numpy as np
import os
import chess
from PyQt6.QtCore import QSettings
import config

# Persistent orientation state
_settings = QSettings("ChessOverlay", "Settings")
_last_valid_orientation = False  # False = Standard (white bottom), True = Flipped

# --- Performance: smaller template size for matching ---
_FAST_SIZE = 64  # Downscaled template size (was 150 — 5.5x fewer pixels)

# Cached grayscale templates (built once)
_gray_templates = {}
_prev_square_hashes = None  # 64-element array of per-square pixel hashes for change detection
_prev_grid_cache = None     # Last computed grid, reused for unchanged squares


def load_templates() -> dict:
    """Load piece templates and pre-compute fast grayscale versions."""
    global _gray_templates
    templates = {}
    pieces = ["wk", "wq", "wr", "wb", "wn", "wp", "bk", "bq", "br", "bb", "bn", "bp"]
    theme_dir = os.path.join(config.PIECES_DIR, config.PIECE_THEME)
    
    for p in pieces:
        matched_path = None
        for f in os.listdir(theme_dir):
            if f.lower() == f"{p}.png":
                matched_path = os.path.join(theme_dir, f)
                break
        if not matched_path:
            continue
        
        img = cv2.imread(matched_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
            
        img = cv2.resize(img, (config.PIECE_SIZE, config.PIECE_SIZE))
        
        if len(img.shape) == 3 and img.shape[2] == 4:
            alpha = img[:, :, 3] / 255.0
            bgr = img[:, :, :3]
            gray_bg = np.full_like(bgr, 128)
            for i in range(3):
                gray_bg[:, :, i] = bgr[:, :, i] * alpha + 128 * (1.0 - alpha)
            templates[p] = gray_bg.astype(np.uint8)
        else:
            templates[p] = img
    
    # Pre-compute fast grayscale templates at reduced size
    for p_code, tmpl in templates.items():
        t = tmpl[:, :, :3] if len(tmpl.shape) == 3 and tmpl.shape[2] >= 3 else tmpl
        small = cv2.resize(t, (_FAST_SIZE, _FAST_SIZE))
        _gray_templates[p_code] = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        
    return templates


def _neutralize_background_fast(square_bgr: np.ndarray) -> np.ndarray:
    """Neutralize chess board background colors — operates on already-resized small square."""
    hsv = cv2.cvtColor(square_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([15, 15, 100]), np.array([65, 230, 255]))
    res = square_bgr.copy()
    res[mask > 0] = (128, 128, 128)
    return res


def _compute_square_hash(square_pixels: np.ndarray) -> int:
    """Noise-tolerant perceptual hash. Quantize a 4x4 downsample to 16-level bins
    so minor anti-aliasing / sub-pixel rendering differences don't break the cache."""
    tiny = cv2.resize(square_pixels, (4, 4), interpolation=cv2.INTER_AREA)
    quantized = (tiny >> 4).astype(np.uint8)  # 16 levels per channel
    return hash(quantized.tobytes())


def get_board_orientation(current_grid: list) -> tuple[bool, str]:
    """
    3-tier orientation detection per UPDATE.md Part 3.
    Returns (is_flipped, orientation_source).
    
    Tier 1: Manual override via QSettings
    Tier 2: Center-of-Mass with confidence check (>=6 pieces, >0.5 sq diff)
    Tier 3: Fallback to last valid orientation (default: Standard)
    """
    global _last_valid_orientation
    
    # --- Tier 1: Manual Override ---
    manual_flip = _settings.value("manual_flip", False, type=bool)
    if manual_flip:
        _last_valid_orientation = True
        return True, "MANUAL"
    
    # --- Tier 2: Center-of-Mass with Confidence ---
    white_y_sum = 0
    white_count = 0
    black_y_sum = 0
    black_count = 0
    
    for i, p in enumerate(current_grid):
        if p == '.':
            continue
        y = i // 8  # row index (0=top of captured image, 7=bottom)
        if p.startswith('w'):
            white_y_sum += y
            white_count += 1
        elif p.startswith('b'):
            black_y_sum += y
            black_count += 1

    total_pieces = white_count + black_count
    
    if total_pieces >= 6 and white_count > 0 and black_count > 0:
        white_avg = white_y_sum / white_count
        black_avg = black_y_sum / black_count
        
        # 0.5 squares of separation required for confidence
        if white_avg > black_avg + 0.5:
            # White pieces are lower on screen → Standard orientation
            _last_valid_orientation = False
            return False, "AUTO-COM"
        elif black_avg > white_avg + 0.5:
            # Black pieces are lower on screen → Flipped orientation
            _last_valid_orientation = True
            return True, "AUTO-COM"
    
    # --- Tier 3: Fallback to last valid orientation ---
    return _last_valid_orientation, "FALLBACK"


def build_fen(board_img: np.ndarray, templates: dict, prev_fen: str | None, prev_active_fallback: str = 'w') -> tuple[str | None, list, bool, str, str, int, bool]:
    """
    Returns (fen_string, current_grid, is_flipped, active_color, orientation_source, piece_count, matched_legal_move).
    Uses 1-ply python-chess legal move generation to perfectly sync sequence of play.
    
    Performance optimizations:
    - Squares are matched at 64x64 grayscale (not 150x150 BGR)
    - Unchanged squares (pixel-hash match) reuse the previous grid result
    """
    global _prev_square_hashes, _prev_grid_cache
    
    board_h, board_w = board_img.shape[:2]
    sq_w, sq_h = board_w // 8, board_h // 8
    
    current_grid = []
    new_hashes = []
    
    for row in range(8):
        for col in range(8):
            idx = row * 8 + col
            square_raw = board_img[row*sq_h:(row+1)*sq_h, col*sq_w:(col+1)*sq_w]
            
            # --- Fast change detection: skip unchanged squares ---
            sq_hash = _compute_square_hash(square_raw)
            new_hashes.append(sq_hash)
            
            if (_prev_square_hashes is not None and 
                _prev_grid_cache is not None and
                idx < len(_prev_square_hashes) and
                sq_hash == _prev_square_hashes[idx]):
                # Square hasn't changed visually — reuse cached result
                current_grid.append(_prev_grid_cache[idx])
                continue
            
            # --- Resize to fast size, neutralize, convert to grayscale ---
            square_small = cv2.resize(square_raw, (_FAST_SIZE, _FAST_SIZE))
            neutral = _neutralize_background_fast(square_small)
            gray_sq = cv2.cvtColor(neutral, cv2.COLOR_BGR2GRAY)
            
            best_score = -1
            best_piece_candidate = '.'
            for p_code, tmpl_gray in _gray_templates.items():
                res = cv2.matchTemplate(gray_sq, tmpl_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val > best_score:
                    best_score = max_val
                    best_piece_candidate = p_code
            
            if best_score >= config.MATCH_THRESHOLD:
                current_grid.append(best_piece_candidate)
            else:
                current_grid.append('.')
    
    # Update caches
    _prev_square_hashes = new_hashes
    _prev_grid_cache = current_grid[:]
                
    # --- Orientation Detection (3-tier) ---
    is_flipped, orientation_source = get_board_orientation(current_grid)
    
    piece_count = sum(1 for p in current_grid if p != '.')
    
    ordered_grid = current_grid[::-1] if is_flipped else current_grid
    
    fen_map = {'wk':'K', 'wq':'Q', 'wr':'R', 'wb':'B', 'wn':'N', 'wp':'P', 'bk':'k', 'bq':'q', 'br':'r', 'bb':'b', 'bn':'n', 'bp':'p', '.':'.'}
    placement_rows = []
    for r in range(8):
        row_str = ""
        empty_count = 0
        for c in range(8):
            idx = r * 8 + c
            piece = ordered_grid[idx]
            if piece == '.':
                empty_count += 1
            else:
                if empty_count > 0:
                    row_str += str(empty_count)
                    empty_count = 0
                row_str += fen_map[piece]
        if empty_count > 0:
            row_str += str(empty_count)
        placement_rows.append(row_str)
        
    placement = "/".join(placement_rows)
    
    matched_legal_move = False
    new_active_color = prev_active_fallback
    
    if prev_fen:
        try:
            board = chess.Board(prev_fen)
            # Standardize placement strings to eliminate halfmove/fullmove artifacts for comparison
            if board.board_fen() == placement:
                # No board change
                return prev_fen, current_grid, is_flipped, 'w' if board.turn else 'b', orientation_source, piece_count, True
            
            # 1-Ply Sync
            for move in board.legal_moves:
                board.push(move)
                if board.board_fen() == placement:
                    matched_legal_move = True
                    new_fen = board.fen()
                    new_active_color = 'w' if board.turn else 'b'
                    print(f"  Legal move matched: {board.peek().uci()}")
                    return new_fen, current_grid, is_flipped, new_active_color, orientation_source, piece_count, True
                board.pop()
                
        except Exception as e:
            print(f"Error parsing prev_fen: {e}")
            
    # Fallback / Resync Path
    # If no legal move matches or we have no prev_fen, we build a fresh FEN from the visual grid using the fallback turn.
    fen_string = f"{placement} {new_active_color} - - 0 1"
    print(f"Building/Resyncing FEN: {fen_string} [orient={orientation_source}, pieces={piece_count}]")
    
    # If prev_fen was empty, we consider it "matched" so it doesn't trigger fail counters
    is_initial_sync = not bool(prev_fen)
    return fen_string, current_grid, is_flipped, new_active_color, orientation_source, piece_count, is_initial_sync or matched_legal_move
