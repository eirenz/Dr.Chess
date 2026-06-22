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

# --- User Color State ---
# "white" = user plays White (pieces at bottom, is_flipped=False)
# "black" = user plays Black (pieces at bottom, is_flipped=True)  
# "auto"  = auto-detect via COM (legacy behavior)
_user_color = "auto"

# --- Performance constants ---
_FAST_SIZE = 64  # Restored to 64 for 100% accuracy on live browser scaling
_TMPL_SIZE = 56  # Restored to 56 to match _FAST_SIZE margin

_THEME_DETECT_SIZE = 128 # Higher resolution for one-time theme detection


# Cached color templates (built once)
_color_templates = {}
_prev_square_hashes = None  # 64-element array of per-square pixel hashes for change detection
_prev_grid_cache = None     # Last computed grid, reused for unchanged squares
_cached_adaptive_threshold = None  # Calibrated per-frame threshold, recomputed on board change

# --- Layer 4: Multi-theme state ---
_all_theme_templates = {}   # {theme_name: {piece_code: gray_template_array}}
_active_theme_name = None   # Currently active theme after auto-detection
_theme_auto_detected = False

# --- Turn tracking state ---
_last_emitted_turn = None   # 'w' or 'b' — last turn returned from build_fen when board changed
_last_emitted_placement = None  # Last board placement string returned


def load_templates(theme_name: str = None) -> dict:
    """Load piece templates and pre-compute fast grayscale versions.
    
    Args:
        theme_name: Specific theme to load. If None, uses config.PIECE_THEME.
    
    Returns:
        dict of full-size BGR templates for the specified theme.
    """
    global _color_templates, _active_theme_name, _cached_adaptive_threshold
    
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
    
    # Pre-compute fast color templates at reduced size
    # Center-crop to _TMPL_SIZE so matchTemplate can slide (vital for textured boards)
    _color_templates.clear()
    margin = (_FAST_SIZE - _TMPL_SIZE) // 2
    for p_code, tmpl in templates.items():
        t = tmpl[:, :, :3] if len(tmpl.shape) == 3 and tmpl.shape[2] >= 3 else tmpl
        if len(t.shape) == 2:  # If grayscale, convert to BGR so it matches 3-channel board squares
            t = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
        full = cv2.resize(t, (_FAST_SIZE, _FAST_SIZE))
        cropped = full[margin:margin+_TMPL_SIZE, margin:margin+_TMPL_SIZE]
        _color_templates[p_code] = cropped
    
    _cached_adaptive_threshold = None  # Force recalibration on next build_fen call
    _active_theme_name = theme_name
    print(f"[FEN] Templates loaded for theme: {theme_name} ({len(templates)} pieces)")
    return templates


def _load_theme_color_templates_large(theme_name: str) -> dict:
    """Load high-res color templates (112x112) for accurate theme detection.
    
    Returns:
        dict of {piece_code: bgr_112x112_array} or empty dict if theme not found.
    """
    pieces = ["wk", "wq", "wr", "wb", "wn", "wp", "bk", "bq", "br", "bb", "bn", "bp"]
    theme_dir = os.path.join(config.PIECES_DIR, theme_name)
    
    if not os.path.isdir(theme_dir):
        return {}
    
    color_tmpls = {}
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
        if len(t.shape) == 2:
            t = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
            
        # Resize piece template to slightly smaller than the board square
        tmpl_size = _THEME_DETECT_SIZE - 16  # 112x112
        small = cv2.resize(t, (tmpl_size, tmpl_size))
        
        color_tmpls[p] = small
    
    return color_tmpls


def detect_best_theme(board_img: np.ndarray) -> str:
    """
    Auto-detects the active piece theme using DISCRIMINABILITY scoring.
    
    Instead of raw top-12 average (which fails for visually similar themes like
    classic/icy_sea or neo/alpha), we compute a relative score:
        discriminability = theme_score - median_score_of_all_themes
    
    This means a theme only wins if it scores DISTINCTIVELY BETTER than competitors,
    not just marginally higher. The theme with the highest discriminability wins.
    """
    global _theme_auto_detected, _all_theme_templates
    
    board_h, board_w = board_img.shape[:2]
    sq_w, sq_h = board_w // 8, board_h // 8
    
    # Extract and prepare all 64 squares
    sample_squares = []
    for row in range(8):
        for col in range(8):
            sq = board_img[row*sq_h:(row+1)*sq_h, col*sq_w:(col+1)*sq_w]
            sq_small = cv2.resize(sq, (_THEME_DETECT_SIZE, _THEME_DETECT_SIZE))
            neutral = _neutralize_background_fast(sq_small)
            sample_squares.append(neutral)
    
    # Step 1: Compute top-12 average score for EVERY theme
    theme_raw_scores = {}  # theme_name -> top12_avg
    
    for theme_name in config.AVAILABLE_THEMES:
        theme_dir = os.path.join(config.PIECES_DIR, theme_name)
        if not os.path.isdir(theme_dir):
            continue
        
        # Load large color templates for this theme
        if theme_name not in _all_theme_templates:
            _all_theme_templates[theme_name] = _load_theme_color_templates_large(theme_name)
        
        theme_tmpls = _all_theme_templates[theme_name]
        if len(theme_tmpls) < 12:
            continue
        
        square_scores = []
        for color_sq in sample_squares:
            best_score = -1.0
            for tmpl_color in theme_tmpls.values():
                res = cv2.matchTemplate(color_sq, tmpl_color, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val > best_score:
                    best_score = max_val
            square_scores.append(best_score)
        
        square_scores.sort(reverse=True)
        top_12_avg = sum(square_scores[:12]) / 12.0
        theme_raw_scores[theme_name] = top_12_avg
    
    if not theme_raw_scores:
        _theme_auto_detected = True
        _all_theme_templates.clear()
        print(f"[FEN] Theme auto-detected: {config.PIECE_THEME} (fallback — no themes scored)")
        return config.PIECE_THEME
    
    # Step 2: Sort themes by raw score
    theme_scores = list(theme_raw_scores.items())
    theme_scores.sort(key=lambda x: x[1], reverse=True)
    best_theme, best_raw = theme_scores[0]
    
    # Step 3: Color MSE Tiebreaker
    # TM_CCOEFF_NORMED ignores absolute color. If multiple themes have nearly identical
    # shapes (score within 0.03 of the winner), we use color MSE to break the tie.
    tie_candidates = [t for t, s in theme_scores if best_raw - s < 0.03]
    
    if len(tie_candidates) > 1:
        # We need the color squares (not neutralized) to check absolute color,
        # but the background throws it off. We use the template's non-gray mask.
        best_mse = float('inf')
        for candidate in tie_candidates:
            tmpls = _all_theme_templates[candidate]
            candidate_mse_list = []
            for color_sq in sample_squares:
                # Find the best template for this square using raw shape score
                best_t_score = -1
                best_t = None
                best_loc = None
                for t in tmpls.values():
                    res = cv2.matchTemplate(color_sq, t, cv2.TM_CCOEFF_NORMED)
                    _, mx, _, mx_loc = cv2.minMaxLoc(res)
                    if mx > best_t_score:
                        best_t_score = mx
                        best_t = t
                        best_loc = mx_loc
                
                if best_t is not None and best_loc is not None:
                    x, y = best_loc
                    th, tw = best_t.shape[:2]
                    sq_crop = color_sq[y:y+th, x:x+tw]
                    
                    # Compute color MSE only on piece pixels (where template is not exactly 128 gray)
                    diff = np.abs(best_t.astype(np.int32) - 128)
                    mask = np.max(diff, axis=2) > 10
                    if np.any(mask):
                        mse = np.mean((sq_crop[mask].astype(np.float32) - best_t[mask].astype(np.float32))**2)
                        candidate_mse_list.append(mse)
            
            if candidate_mse_list:
                avg_mse = sum(sorted(candidate_mse_list)[:12]) / 12.0
                if avg_mse < best_mse:
                    best_mse = avg_mse
                    best_theme = candidate
                    
        print(f"[FEN] Theme auto-detected: {best_theme} (resolved tiebreak among {len(tie_candidates)} candidates)")
    else:
        print(f"[FEN] Theme auto-detected: {best_theme} (raw={best_raw:.3f}, clear winner)")
        
    _theme_auto_detected = True
    _all_theme_templates.clear()
    return best_theme


def get_active_theme_name() -> str:
    """Return the currently active theme name for display in debug panel."""
    return _active_theme_name or config.PIECE_THEME


def is_theme_auto_detected() -> bool:
    """Return whether the current theme was auto-detected."""
    return _theme_auto_detected


_calibrated_light_bg = None
_calibrated_dark_bg = None

def calibrate_board_colors(board_img: np.ndarray):
    """Calibrate the expected background color for light and dark squares using the corner squares."""
    global _calibrated_light_bg, _calibrated_dark_bg
    h, w = board_img.shape[:2]
    sq_w, sq_h = w // 8, h // 8
    
    def get_ring_color(r, c):
        sq = board_img[r*sq_h:(r+1)*sq_h, c*sq_w:(c+1)*sq_w]
        inset_y, inset_x = max(4, int(sq_h * 0.12)), max(4, int(sq_w * 0.12))
        ring = np.concatenate([
            sq[inset_y:inset_y+4, inset_x:sq_w-inset_x].reshape(-1, 3),
            sq[sq_h-inset_y-4:sq_h-inset_y, inset_x:sq_w-inset_x].reshape(-1, 3),
            sq[inset_y:sq_h-inset_y, inset_x:inset_x+4].reshape(-1, 3),
            sq[inset_y:sq_h-inset_y, sq_w-inset_x-4:sq_w-inset_x].reshape(-1, 3)
        ])
        return np.median(ring, axis=0)

    # a8 (0,0)=light, h8 (0,7)=dark, a1 (7,0)=dark, h1 (7,7)=light
    a8_color = get_ring_color(0, 0)
    h1_color = get_ring_color(7, 7)
    _calibrated_light_bg = np.median([a8_color, h1_color], axis=0)
    
    h8_color = get_ring_color(0, 7)
    a1_color = get_ring_color(7, 0)
    _calibrated_dark_bg = np.median([h8_color, a1_color], axis=0)


def _neutralize_background_fast(square_bgr: np.ndarray, is_light_square: bool = None) -> np.ndarray:
    """Neutralize board background using calibrated colors or inset-ring fallback.
    
    By matching against the specific known background color of the board, we avoid 
    accidentally erasing piece pixels that happen to be brown (HSV overlap), and we 
    naturally preserve highlight colors (yellow/green) because they don't match the background.
    """
    global _calibrated_light_bg, _calibrated_dark_bg
    
    expected_bg = None
    if is_light_square is not None and _calibrated_light_bg is not None and _calibrated_dark_bg is not None:
        expected_bg = _calibrated_light_bg if is_light_square else _calibrated_dark_bg
        
    h, w = square_bgr.shape[:2]
    
    # Calculate inset-ring color
    inset_y = max(4, int(h * 0.12))
    inset_x = max(4, int(w * 0.12))
    ring_pixels = np.concatenate([
        square_bgr[inset_y:inset_y+4, inset_x:w-inset_x].reshape(-1, 3),
        square_bgr[h-inset_y-4:h-inset_y, inset_x:w-inset_x].reshape(-1, 3),
        square_bgr[inset_y:h-inset_y, inset_x:inset_x+4].reshape(-1, 3),
        square_bgr[inset_y:h-inset_y, w-inset_x-4:w-inset_x].reshape(-1, 3)
    ])
    ring_color = np.median(ring_pixels, axis=0)
    
    if expected_bg is not None:
        # Check if the square has a highlight (ring color differs significantly from expected board color)
        # We use a distance threshold of 60 to distinguish highlights from normal texture variance.
        if np.max(np.abs(ring_color - expected_bg)) > 60:
            # It's a highlighted square! Erase the highlight color instead of the board color.
            active_bg = ring_color
        else:
            # Normal square. Use the calibrated board color (prevents self-erasing pieces).
            active_bg = expected_bg
    else:
        active_bg = ring_color

    diff = np.abs(square_bgr.astype(np.int32) - active_bg.astype(np.int32))
    mask_bg = np.max(diff, axis=2) < 40

    res = square_bgr.copy()
    res[mask_bg] = (128, 128, 128)
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

def set_user_color(color: str):
    """Set the user's playing color. Locks orientation immediately.
    
    Args:
        color: 'white', 'black', or 'auto'
    """
    global _user_color, _orientation_locked, _locked_orientation
    _user_color = color.lower()
    
    if _user_color == "white":
        _orientation_locked = True
        _locked_orientation = False  # Standard = white at bottom
        print(f"[ORIENT] User color set to WHITE -> orientation LOCKED(Standard)")
    elif _user_color == "black":
        _orientation_locked = True
        _locked_orientation = True   # Flipped = black at bottom
        print(f"[ORIENT] User color set to BLACK -> orientation LOCKED(Flipped)")
    else:
        # Auto mode — reset lock so COM can re-evaluate
        _orientation_locked = False
        print(f"[ORIENT] User color set to AUTO -> orientation unlocked")


def get_user_color() -> str:
    """Return the current user color setting ('white', 'black', or 'auto')."""
    return _user_color


def is_orientation_locked() -> bool:
    """Return whether orientation is currently locked (for debug display)."""
    return _orientation_locked


def get_board_orientation(current_grid: list) -> tuple[bool, str]:
    """
    4-tier orientation detection.
    Returns (is_flipped, orientation_source).
    
    Tier 0: User color set (white/black) -> immediate lock
    Tier 1: If locked (from COM confidence), return locked value
    Tier 2: Manual override via QSettings
    Tier 3: Center-of-Mass with auto-lock on first confident reading
    Tier 4: Fallback to last valid orientation
    """
    global _last_valid_orientation
    global _orientation_locked, _locked_orientation, _lock_confidence_count, _lock_candidate
    
    # --- Tier 0: User Color Lock ---
    # When user explicitly sets their color, orientation is permanently locked
    if _user_color in ("white", "black") and _orientation_locked:
        orient_str = "Flipped" if _locked_orientation else "Standard"
        color_str = _user_color.capitalize()
        return _locked_orientation, f"USER({color_str})"
    
    # --- Tier 1: Locked Orientation (from COM confidence) ---
    if _orientation_locked:
        return _locked_orientation, f"LOCKED({'Flipped' if _locked_orientation else 'Standard'})"
    
    # --- Tier 2: Manual Override ---
    manual_flip = _settings.value("manual_flip", False, type=bool)
    if manual_flip:
        _last_valid_orientation = True
        _orientation_locked = True
        _locked_orientation = True
        return True, "MANUAL"
    
    # --- Tier 3: Center-of-Mass with Auto-Lock ---
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
            detected_flip = False
        elif black_avg > white_avg + 0.5:
            detected_flip = True
        
        if detected_flip is not None:
            _last_valid_orientation = detected_flip
            
            # In auto mode: lock on first confident reading (>=8 pieces, >=1.0 sq separation)
            if _user_color == "auto" and total_pieces >= 8 and separation >= 1.0:
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
    
    # --- Tier 4: Fallback to last valid orientation ---
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


def _infer_turn_from_diff(prev_grid: list, curr_grid: list) -> str | None:
    """Determine whose turn it is by comparing which color's pieces changed position.
    
    Logic:
    - Find squares where pieces departed (were on prev_grid but not on curr_grid)
    - If white pieces departed → White just played → it's Black's turn ('b')
    - If black pieces departed → Black just played → it's White's turn ('w')
    - If ambiguous or no change → return None
    """
    if prev_grid is None or len(prev_grid) != 64 or len(curr_grid) != 64:
        return None
    
    white_departed = 0  # Count of squares where a white piece left
    black_departed = 0  # Count of squares where a black piece left
    
    for i in range(64):
        prev_p = prev_grid[i]
        curr_p = curr_grid[i]
        
        if prev_p == curr_p:
            continue
        
        # A piece departed from this square
        if prev_p.startswith('w') and curr_p != prev_p:
            white_departed += 1
        elif prev_p.startswith('b') and curr_p != prev_p:
            black_departed += 1
    
    # No changes detected
    if white_departed == 0 and black_departed == 0:
        return None
    
    # Clear signal: only one color's pieces moved
    if white_departed > 0 and black_departed == 0:
        return 'b'  # White moved → now Black's turn
    if black_departed > 0 and white_departed == 0:
        return 'w'  # Black moved → now White's turn
    
    # Both colors changed (capture scenario): the color with more departures is the mover
    # In a normal move+capture: mover departs 1 square, captured piece also "departs" 1 square
    # But the mover also arrives at the capture square, so the mover has 1 net departure
    # and the captured side has 1 piece simply gone (not relocated)
    # Heuristic: count arrivals too
    white_arrived = 0
    black_arrived = 0
    for i in range(64):
        prev_p = prev_grid[i]
        curr_p = curr_grid[i]
        if prev_p == curr_p:
            continue
        if curr_p.startswith('w') and prev_p != curr_p:
            white_arrived += 1
        elif curr_p.startswith('b') and prev_p != curr_p:
            black_arrived += 1
    
    # The mover is the one who has arrivals (piece landed on a new square)
    if white_arrived > 0 and black_arrived == 0:
        return 'b'  # White piece arrived somewhere → White moved → Black's turn
    if black_arrived > 0 and white_arrived == 0:
        return 'w'  # Black piece arrived somewhere → Black moved → White's turn
    
    # Truly ambiguous — can't determine
    return None


def reset_turn_tracking():
    """Reset turn tracking state. Called on manual turn toggle or theme change."""
    global _last_emitted_turn, _last_emitted_placement
    _last_emitted_turn = None
    _last_emitted_placement = None


def build_fen(board_img: np.ndarray, templates: dict, prev_fen: str | None, prev_active_fallback: str = 'w', prev_grid: list = None) -> tuple[str | None, list, bool, str, str, int, bool]:
    """
    Returns (fen_string, current_grid, is_flipped, active_color, orientation_source, piece_count, matched_legal_move).
    Uses 1-ply and 2-ply python-chess legal move generation to sync sequence of play.
    
    Args:
        prev_grid: The previous confirmed grid (64-element list) for grid-diff turn inference.
    
    Safety layers:
    - Layer 1: Orientation lock (prevents flip in endgames)
    - Layer 2: FEN plausibility validation (rejects impossible positions)
    - Layer 3: 2-ply matching (recovers from missed frames)
    - Turn inference: Grid-diff analysis + parity enforcement
    """
    global _prev_square_hashes, _prev_grid_cache, _last_emitted_turn, _last_emitted_placement, _cached_adaptive_threshold
    
    board_h, board_w = board_img.shape[:2]
    sq_w, sq_h = board_w // 8, board_h // 8
    
    current_grid = []
    new_hashes = []
    
    # --- Adaptive threshold calibration ---
    # Only recompute when the board hasn't been seen before (first frame, or after a template reload).
    # In subsequent frames the hash-cache means most squares are skipped anyway, and the
    # board rendering characteristics don't change between frames.
    if _cached_adaptive_threshold is None or _prev_square_hashes is None:
        calibrate_board_colors(board_img)
        all_sample_scores = []
        for row in range(8):
            for col in range(8):
                is_light_square = (row + col) % 2 == 0
                sq_raw = board_img[row*sq_h:(row+1)*sq_h, col*sq_w:(col+1)*sq_w]
                sq_small = cv2.resize(sq_raw, (_FAST_SIZE, _FAST_SIZE))
                neutral = _neutralize_background_fast(sq_small, is_light_square)
                best = -1.0
                for tmpl_color in _color_templates.values():
                    res = cv2.matchTemplate(neutral, tmpl_color, cv2.TM_CCOEFF_NORMED)
                    _, mx, _, _ = cv2.minMaxLoc(res)
                    if mx > best:
                        best = mx
                all_sample_scores.append(best)
        # Set threshold at 40th-percentile of all square scores.
        # With 32 pieces + 32 empty squares the 40th percentile (~25th score)
        # sits right in the piece/empty transition zone.
        sorted_scores = sorted(all_sample_scores, reverse=True)
        p40_score = sorted_scores[int(len(sorted_scores) * 0.40)]
        _cached_adaptive_threshold = float(np.clip(p40_score * 0.85, 0.20, 0.60))
    
    adaptive_threshold = _cached_adaptive_threshold
    
    for row in range(8):
        for col in range(8):
            idx = row * 8 + col
            is_light_square = (row + col) % 2 == 0
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
            
            # --- Resize to fast size, neutralize ---
            square_small = cv2.resize(square_raw, (_FAST_SIZE, _FAST_SIZE))
            neutral = _neutralize_background_fast(square_small, is_light_square)
            
            best_score = -1
            second_score = -1
            best_piece_candidate = '.'
            second_piece_candidate = '.'
            
            for p_code, tmpl_color in _color_templates.items():
                res = cv2.matchTemplate(neutral, tmpl_color, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val > best_score:
                    second_score = best_score
                    second_piece_candidate = best_piece_candidate
                    best_score = max_val
                    best_piece_candidate = p_code
                elif max_val > second_score:
                    second_score = max_val
                    second_piece_candidate = p_code
            
            # --- Color-Aware Tiebreaker ---
            # If the top two match scores are very close (< 0.05 diff) and they are the same piece type but opposite color
            if best_piece_candidate != '.' and second_piece_candidate != '.':
                if best_piece_candidate[1] == second_piece_candidate[1] and best_piece_candidate[0] != second_piece_candidate[0]:
                    if (best_score - second_score) < 0.05:
                        # Extract raw brightness from piece region
                        global _calibrated_light_bg, _calibrated_dark_bg
                        expected_bg = _calibrated_light_bg if is_light_square else _calibrated_dark_bg
                        if expected_bg is not None:
                            diff = np.abs(square_small.astype(np.int32) - expected_bg.astype(np.int32))
                            mask_piece = np.max(diff, axis=2) >= 40
                            if np.any(mask_piece):
                                mean_brightness = np.mean(square_small[mask_piece])
                                predicted_white = mean_brightness > 110
                                candidate_is_white = best_piece_candidate[0] == 'w'
                                if predicted_white != candidate_is_white:
                                    # Overrule the shape score based on color brightness
                                    best_piece_candidate, second_piece_candidate = second_piece_candidate, best_piece_candidate
                                    best_score, second_score = second_score, best_score
            
            gap = best_score - second_score
            is_piece = False
            if best_score >= adaptive_threshold:
                is_piece = True  # Above calibrated threshold for this board/theme
            elif best_score >= adaptive_threshold * 0.75 and gap >= 0.04:
                is_piece = True  # Just below threshold but clear winner (no other close candidate)
                
            if is_piece:
                current_grid.append(best_piece_candidate)
            else:
                current_grid.append('.')
    
    # --- Contextual Frame Correction ---
    if prev_grid is not None and len(prev_grid) == 64 and bool(prev_fen):
        diff_count = sum(1 for i in range(64) if current_grid[i] != prev_grid[i])
        if diff_count > 4:
            print(f"[FEN] Frame rejected: {diff_count} squares changed (max 4). Likely vision glitch.")
            is_flipped, orientation_source = get_board_orientation(prev_grid)
            return prev_fen, prev_grid[:], is_flipped, prev_active_fallback, orientation_source, sum(1 for p in prev_grid if p != '.'), False

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
    # We relax validation for the VERY FIRST frame (prev_fen is None) so the overlay 
    # can at least lock onto the board and wrap it, even if the user's piece theme 
    # is highly unusual/3D and causes some pieces (like kings) to be misclassified.
    is_valid, validation_reason = validate_fen_plausibility(placement)
    if not is_valid and prev_fen is not None:
        cv2.imwrite(r"C:\Users\renze\.gemini\antigravity-ide\brain\fb620d04-0517-4692-9a4c-8dd287aad538\.tempmediaStorage\debug_failed_pieces.png", board_img)
        print(f"[FEN] Validation FAILED: {validation_reason} | Orient: {orientation_source} | Pieces: {piece_count}")
        return None, current_grid, is_flipped, prev_active_fallback, orientation_source, piece_count, False
    elif not is_valid and prev_fen is None:
        print(f"[FEN] Validation WARNING (Initial Sync): {validation_reason} | Proceeding anyway to allow board wrap.")
        is_valid = True
    
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
                    _last_emitted_turn = new_active_color
                    _last_emitted_placement = placement
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
                        _last_emitted_turn = new_active_color
                        _last_emitted_placement = placement
                        print(f"  [FEN] 2-ply matched: {move1.uci()} + {move2.uci()}")
                        return new_fen, current_grid, is_flipped, new_active_color, orientation_source, piece_count, True
                    board2.pop()
                board2.pop()
                
        except Exception as e:
            print(f"[FEN] Error parsing prev_fen: {e}")
            
    # Fallback / Resync Path
    
    # --- Fix 1: Resync Safety Net (Piece Count & Theme Redetection) ---
    if prev_fen is not None:
        try:
            prev_board = chess.Board(prev_fen)
            prev_piece_count = len(prev_board.piece_map())
            # If pieces suddenly jump by more than 2, it's definitely a vision glitch
            if piece_count > prev_piece_count + 2:
                print(f"[FEN] Frame rejected (Resync): Piece count jumped from {prev_piece_count} to {piece_count}. Likely vision glitch.")
                return prev_fen, prev_grid[:], is_flipped, prev_active_fallback, orientation_source, prev_piece_count, False
        except Exception:
            pass

        # --- Fix 2: Grid-diff turn inference for resync ---
    if prev_grid is not None:
        inferred_turn = _infer_turn_from_diff(prev_grid, ordered_grid)
        if inferred_turn is not None:
            new_active_color = inferred_turn
            print(f"[TURN] Inferred from grid-diff: {new_active_color}")
    
    # --- Fix 2: Turn parity enforcement ---
    board_changed = (_last_emitted_placement is not None and _last_emitted_placement != placement)
    
    if board_changed and _last_emitted_turn is not None and _last_emitted_turn == new_active_color:
        # Same color twice on a changed board → force flip
        new_active_color = 'b' if new_active_color == 'w' else 'w'
        print(f"[TURN] Parity enforced: flipped to {new_active_color}")
    
    def _get_safe_castling_rights(placement_str: str, desired_rights: str) -> str:
        if not desired_rights or desired_rights == "-":
            return "-"
        try:
            b = chess.Board(f"{placement_str} w - - 0 1")
        except Exception:
            return "-"
            
        safe = ""
        if "K" in desired_rights and b.piece_at(chess.E1) == chess.Piece.from_symbol('K') and b.piece_at(chess.H1) == chess.Piece.from_symbol('R'): safe += "K"
        if "Q" in desired_rights and b.piece_at(chess.E1) == chess.Piece.from_symbol('K') and b.piece_at(chess.A1) == chess.Piece.from_symbol('R'): safe += "Q"
        if "k" in desired_rights and b.piece_at(chess.E8) == chess.Piece.from_symbol('k') and b.piece_at(chess.H8) == chess.Piece.from_symbol('r'): safe += "k"
        if "q" in desired_rights and b.piece_at(chess.E8) == chess.Piece.from_symbol('k') and b.piece_at(chess.A8) == chess.Piece.from_symbol('r'): safe += "q"
        return safe if safe else "-"

    # Determine desired rights
    desired_rights = "KQkq"
    if prev_fen:
        try:
            desired_rights = chess.Board(prev_fen).castling_xfen()
        except:
            desired_rights = "-"

    safe_castling = _get_safe_castling_rights(placement, desired_rights)
    fen_string = f"{placement} {new_active_color} {safe_castling} - 0 1"
    
    # --- Layer 4: Strict python-chess validation ---
    try:
        board = chess.Board(fen_string)
        if not board.is_valid():
            # Try flipping the inferred turn
            alt_color = 'b' if new_active_color == 'w' else 'w'
            alt_fen = f"{placement} {alt_color} - - 0 1"
            alt_board = chess.Board(alt_fen)
            
            if alt_board.is_valid():
                new_active_color = alt_color
                fen_string = alt_fen
                print(f"[FEN] Flipped turn to {new_active_color} because original was invalid.")
            else:
                print(f"[FEN] Validation FAILED: Board is strictly invalid. Status: {board.status()}")
                return None, current_grid, is_flipped, prev_active_fallback, orientation_source, piece_count, False
    except ValueError as e:
        print(f"[FEN] Validation FAILED: {e}")
        return None, current_grid, is_flipped, prev_active_fallback, orientation_source, piece_count, False

    print(f"[FEN] Resync: {fen_string} [orient={orientation_source}, pieces={piece_count}]")
    
    _last_emitted_turn = new_active_color
    _last_emitted_placement = placement
    
    # If prev_fen was empty, we consider it "matched" so it doesn't trigger fail counters
    is_initial_sync = not bool(prev_fen)
    return fen_string, current_grid, is_flipped, new_active_color, orientation_source, piece_count, is_initial_sync or matched_legal_move
