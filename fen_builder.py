import cv2
import numpy as np
import os
import chess
from PyQt6.QtCore import QSettings
import config

# Persistent orientation state
_settings = QSettings("ChessOverlay", "Settings")
_last_valid_orientation = False  # False = Standard (white bottom), True = Flipped

# --- Layer 1: Orientation Lock State ---
_orientation_locked = False
_locked_orientation = False  # False = Standard, True = Flipped
_lock_confidence_count = 0   # Consecutive confident COM readings before locking
_lock_candidate = None       # Which orientation the consecutive readings are for
_LOCK_THRESHOLD = 5          # Require 5 consecutive confident readings to lock

# --- Performance: smaller template size for matching ---
_FAST_SIZE = 64  # Downscaled template size (was 150 — 5.5x fewer pixels)

# Cached grayscale templates (built once)
_gray_templates = {}
_prev_square_hashes = None  # 64-element array of per-square pixel hashes for change detection
_prev_grid_cache = None     # Last computed grid, reused for unchanged squares

# --- Layer 4: Multi-theme state ---
_all_theme_templates = {}   # {theme_name: {piece_code: gray_template_array}}
_active_theme_name = None   # Currently active theme after auto-detection
_theme_auto_detected = False


def load_templates(theme_name: str = None) -> dict:
    """Load piece templates and pre-compute fast grayscale versions.
    
    Args:
        theme_name: Specific theme to load. If None, uses config.PIECE_THEME.
    
    Returns:
        dict of full-size BGR templates for the specified theme.
    """
    global _gray_templates, _active_theme_name
    
    if theme_name is None:
        theme_name = config.PIECE_THEME
    
    templates = {}
    pieces = ["wk", "wq", "wr", "wb", "wn", "wp", "bk", "bq", "br", "bb", "bn", "bp"]
    theme_dir = os.path.join(config.PIECES_DIR, theme_name)
    
    if not os.path.isdir(theme_dir):
        print(f"[FEN] Theme directory not found: {theme_dir}")
        return templates
    
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
    _gray_templates.clear()
    for p_code, tmpl in templates.items():
        t = tmpl[:, :, :3] if len(tmpl.shape) == 3 and tmpl.shape[2] >= 3 else tmpl
        small = cv2.resize(t, (_FAST_SIZE, _FAST_SIZE))
        _gray_templates[p_code] = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    
    _active_theme_name = theme_name
    print(f"[FEN] Templates loaded for theme: {theme_name} ({len(templates)} pieces)")
    return templates


def _load_theme_gray_templates(theme_name: str) -> dict:
    """Load only fast grayscale templates for a theme (used during auto-detection).
    
    Returns:
        dict of {piece_code: gray_64x64_array} or empty dict if theme not found.
    """
    pieces = ["wk", "wq", "wr", "wb", "wn", "wp", "bk", "bq", "br", "bb", "bn", "bp"]
    theme_dir = os.path.join(config.PIECES_DIR, theme_name)
    
    if not os.path.isdir(theme_dir):
        return {}
    
    gray_tmpls = {}
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
        
        # Alpha composite onto neutral gray background
        if len(img.shape) == 3 and img.shape[2] == 4:
            alpha = img[:, :, 3] / 255.0
            bgr = img[:, :, :3]
            gray_bg = np.full_like(bgr, 128)
            for i in range(3):
                gray_bg[:, :, i] = bgr[:, :, i] * alpha + 128 * (1.0 - alpha)
            img = gray_bg.astype(np.uint8)
        
        t = img[:, :, :3] if len(img.shape) == 3 and img.shape[2] >= 3 else img
        small = cv2.resize(t, (_FAST_SIZE, _FAST_SIZE))
        gray_tmpls[p] = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    
    return gray_tmpls


def detect_best_theme(board_img: np.ndarray) -> str:
    """Auto-detect the best matching piece theme by testing all available themes.
    
    Runs once on first board capture. Tests each theme's templates against
    sample squares and returns the theme with highest average confidence.
    
    Args:
        board_img: The captured board image (BGR).
    
    Returns:
        Theme name string (e.g., "neo_wood").
    """
    global _theme_auto_detected, _all_theme_templates
    
    board_h, board_w = board_img.shape[:2]
    sq_w, sq_h = board_w // 8, board_h // 8
    
    # Sample squares from known-occupied positions in a starting position
    # Rows 0,1 (black pieces) and rows 6,7 (white pieces) are most likely occupied
    sample_positions = [
        (0, 0), (0, 4), (0, 7),  # Top row (likely black pieces)
        (1, 2), (1, 5),          # Second row (likely black pawns)
        (6, 1), (6, 6),          # Seventh row (likely white pawns)
        (7, 0), (7, 4), (7, 7),  # Bottom row (likely white pieces)
    ]
    
    # Extract and prepare sample squares
    sample_squares = []
    for row, col in sample_positions:
        sq = board_img[row*sq_h:(row+1)*sq_h, col*sq_w:(col+1)*sq_w]
        sq_small = cv2.resize(sq, (_FAST_SIZE, _FAST_SIZE))
        neutral = _neutralize_background_fast(sq_small)
        gray_sq = cv2.cvtColor(neutral, cv2.COLOR_BGR2GRAY)
        sample_squares.append(gray_sq)
    
    best_theme = config.PIECE_THEME  # Default fallback
    best_avg_conf = -1.0
    
    # Test each available theme
    for theme_name in config.AVAILABLE_THEMES:
        theme_dir = os.path.join(config.PIECES_DIR, theme_name)
        if not os.path.isdir(theme_dir):
            continue
        
        # Load gray templates for this theme
        if theme_name not in _all_theme_templates:
            _all_theme_templates[theme_name] = _load_theme_gray_templates(theme_name)
        
        theme_tmpls = _all_theme_templates[theme_name]
        if len(theme_tmpls) < 12:
            continue
        
        # Score this theme against sample squares
        total_conf = 0.0
        for gray_sq in sample_squares:
            best_score = -1.0
            for tmpl_gray in theme_tmpls.values():
                res = cv2.matchTemplate(gray_sq, tmpl_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val > best_score:
                    best_score = max_val
            total_conf += best_score
        
        avg_conf = total_conf / len(sample_squares)
        
        if avg_conf > best_avg_conf:
            best_avg_conf = avg_conf
            best_theme = theme_name
    
    _theme_auto_detected = True
    
    # Clear cached theme templates to free memory (we only need the winner)
    _all_theme_templates.clear()
    
    print(f"[FEN] Theme auto-detected: {best_theme} (confidence: {best_avg_conf:.3f})")
    return best_theme


def get_active_theme_name() -> str:
    """Return the currently active theme name for display in debug panel."""
    return _active_theme_name or config.PIECE_THEME


def is_theme_auto_detected() -> bool:
    """Return whether the current theme was auto-detected."""
    return _theme_auto_detected


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


# --- Layer 1: Orientation Lock Functions ---

def reset_orientation_lock():
    """Reset the orientation lock. Called when user manually toggles turn or flip."""
    global _orientation_locked, _locked_orientation, _lock_confidence_count, _lock_candidate
    _orientation_locked = False
    _locked_orientation = False
    _lock_confidence_count = 0
    _lock_candidate = None
    print("[FEN] Orientation lock RESET")


def is_orientation_locked() -> bool:
    """Return whether orientation is currently locked (for debug display)."""
    return _orientation_locked


def get_board_orientation(current_grid: list) -> tuple[bool, str]:
    """
    3-tier orientation detection with orientation lock.
    Returns (is_flipped, orientation_source).
    
    Tier 0: If locked, return locked value immediately
    Tier 1: Manual override via QSettings
    Tier 2: Center-of-Mass with confidence check (>=6 pieces, >0.5 sq diff)
             + lock after 5 consecutive high-confidence readings
    Tier 3: Fallback to last valid orientation (default: Standard)
    """
    global _last_valid_orientation
    global _orientation_locked, _locked_orientation, _lock_confidence_count, _lock_candidate
    
    # --- Tier 0: Locked Orientation ---
    if _orientation_locked:
        return _locked_orientation, f"LOCKED({'Flipped' if _locked_orientation else 'Standard'})"
    
    # --- Tier 1: Manual Override ---
    manual_flip = _settings.value("manual_flip", False, type=bool)
    if manual_flip:
        _last_valid_orientation = True
        # Manual override also locks
        _orientation_locked = True
        _locked_orientation = True
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
        separation = abs(white_avg - black_avg)
        
        detected_flip = None
        if white_avg > black_avg + 0.5:
            # White pieces are lower on screen -> Standard orientation
            detected_flip = False
        elif black_avg > white_avg + 0.5:
            # Black pieces are lower on screen -> Flipped orientation
            detected_flip = True
        
        if detected_flip is not None:
            _last_valid_orientation = detected_flip
            
            # High-confidence lock check: >=10 pieces AND >=1.5 sq separation
            if total_pieces >= 10 and separation >= 1.5:
                if _lock_candidate == detected_flip:
                    _lock_confidence_count += 1
                else:
                    _lock_candidate = detected_flip
                    _lock_confidence_count = 1
                
                if _lock_confidence_count >= _LOCK_THRESHOLD:
                    _orientation_locked = True
                    _locked_orientation = detected_flip
                    orient_str = "Flipped" if detected_flip else "Standard"
                    print(f"[FEN] Orientation LOCKED to {orient_str} after {_LOCK_THRESHOLD} confident readings")
                    return detected_flip, f"LOCKED({orient_str})"
            
            return detected_flip, "AUTO-COM"
    
    # --- Tier 3: Fallback to last valid orientation ---
    return _last_valid_orientation, "FALLBACK"


# --- Layer 2: FEN Plausibility Validation ---

def validate_fen_plausibility(placement: str) -> tuple[bool, str]:
    """Validate that a FEN placement string represents a plausible chess position.
    
    Args:
        placement: FEN placement string (e.g., "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
    
    Returns:
        (is_valid, reason) — reason is empty string if valid, or error description if invalid.
    """
    rows = placement.split("/")
    if len(rows) != 8:
        return False, f"Expected 8 ranks, got {len(rows)}"
    
    # Expand the placement to a flat 64-character representation
    expanded = ""
    for row in rows:
        for ch in row:
            if ch.isdigit():
                expanded += "." * int(ch)
            else:
                expanded += ch
    
    if len(expanded) != 64:
        return False, f"Expected 64 squares, got {len(expanded)}"
    
    # Count pieces
    white_kings = expanded.count('K')
    black_kings = expanded.count('k')
    white_pawns = expanded.count('P')
    black_pawns = expanded.count('p')
    white_total = sum(1 for c in expanded if c.isupper())
    black_total = sum(1 for c in expanded if c.islower())
    
    # Rule 1: Exactly 1 king per side
    if white_kings != 1:
        return False, f"White kings: {white_kings} (expected 1)"
    if black_kings != 1:
        return False, f"Black kings: {black_kings} (expected 1)"
    
    # Rule 2: No pawns on rank 1 (row index 7) or rank 8 (row index 0)
    rank_8 = expanded[0:8]   # Top row = rank 8
    rank_1 = expanded[56:64] # Bottom row = rank 1
    for ch in rank_8 + rank_1:
        if ch in ('P', 'p'):
            return False, f"Pawn found on rank 1 or 8 (impossible position)"
    
    # Rule 3: Max 8 pawns per side
    if white_pawns > 8:
        return False, f"White pawns: {white_pawns} (max 8)"
    if black_pawns > 8:
        return False, f"Black pawns: {black_pawns} (max 8)"
    
    # Rule 4: Max 16 pieces per side
    if white_total > 16:
        return False, f"White pieces: {white_total} (max 16)"
    if black_total > 16:
        return False, f"Black pieces: {black_total} (max 16)"
    
    return True, ""


def build_fen(board_img: np.ndarray, templates: dict, prev_fen: str | None, prev_active_fallback: str = 'w') -> tuple[str | None, list, bool, str, str, int, bool]:
    """
    Returns (fen_string, current_grid, is_flipped, active_color, orientation_source, piece_count, matched_legal_move).
    Uses 1-ply and 2-ply python-chess legal move generation to sync sequence of play.
    
    Performance optimizations:
    - Squares are matched at 64x64 grayscale (not 150x150 BGR)
    - Unchanged squares (pixel-hash match) reuse the previous grid result
    
    Safety layers:
    - Layer 1: Orientation lock (prevents flip in endgames)
    - Layer 2: FEN plausibility validation (rejects impossible positions)
    - Layer 3: 2-ply matching (recovers from missed frames)
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
                
    # --- Orientation Detection (3-tier + lock) ---
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
    
    # --- Layer 2: Validate FEN plausibility ---
    is_valid, validation_reason = validate_fen_plausibility(placement)
    if not is_valid:
        print(f"[FEN] Validation FAILED: {validation_reason} | Orient: {orientation_source} | Pieces: {piece_count}")
        return None, current_grid, is_flipped, prev_active_fallback, orientation_source, piece_count, False
    
    matched_legal_move = False
    new_active_color = prev_active_fallback
    
    if prev_fen:
        try:
            board = chess.Board(prev_fen)
            # Standardize placement strings to eliminate halfmove/fullmove artifacts for comparison
            if board.board_fen() == placement:
                # No board change
                return prev_fen, current_grid, is_flipped, 'w' if board.turn else 'b', orientation_source, piece_count, True
            
            # --- Layer 3a: 1-Ply Sync ---
            for move in board.legal_moves:
                board.push(move)
                if board.board_fen() == placement:
                    matched_legal_move = True
                    new_fen = board.fen()
                    new_active_color = 'w' if board.turn else 'b'
                    print(f"  [FEN] 1-ply matched: {board.peek().uci()}")
                    return new_fen, current_grid, is_flipped, new_active_color, orientation_source, piece_count, True
                board.pop()
            
            # --- Layer 3b: 2-Ply Sync (recover from missed frame) ---
            board2 = chess.Board(prev_fen)
            for move1 in board2.legal_moves:
                board2.push(move1)
                for move2 in board2.legal_moves:
                    board2.push(move2)
                    if board2.board_fen() == placement:
                        matched_legal_move = True
                        new_fen = board2.fen()
                        new_active_color = 'w' if board2.turn else 'b'
                        print(f"  [FEN] 2-ply matched: {move1.uci()} + {move2.uci()}")
                        return new_fen, current_grid, is_flipped, new_active_color, orientation_source, piece_count, True
                    board2.pop()
                board2.pop()
                
        except Exception as e:
            print(f"[FEN] Error parsing prev_fen: {e}")
            
    # Fallback / Resync Path
    # If no legal move matches or we have no prev_fen, we build a fresh FEN from the visual grid using the fallback turn.
    fen_string = f"{placement} {new_active_color} - - 0 1"
    print(f"[FEN] Resync: {fen_string} [orient={orientation_source}, pieces={piece_count}]")
    
    # If prev_fen was empty, we consider it "matched" so it doesn't trigger fail counters
    is_initial_sync = not bool(prev_fen)
    return fen_string, current_grid, is_flipped, new_active_color, orientation_source, piece_count, is_initial_sync or matched_legal_move
