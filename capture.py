import cv2
import numpy as np
import mss
import time
import pygetwindow as gw

def refine_board(rect, img):
    x, y, w, h = rect
    roi = img[y:y+h, x:x+w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    
    col_vars = np.var(gray, axis=0)
    row_vars = np.var(gray, axis=1)
    
    col_threshold = np.median(col_vars) * 0.2
    row_threshold = np.median(row_vars) * 0.2
    
    valid_cols = np.where(col_vars > col_threshold)[0]
    valid_rows = np.where(row_vars > row_threshold)[0]
    
    if len(valid_cols) == 0 or len(valid_rows) == 0:
        return rect
        
    true_x = x + int(valid_cols[0])
    true_y = y + int(valid_rows[0])
    true_w = int(valid_cols[-1] - valid_cols[0]) + 1
    true_h = int(valid_rows[-1] - valid_rows[0]) + 1
    
    if true_w < 300 or true_h < 300:
        return int(x), int(y), int(w), int(h)
    
    return true_x, true_y, true_w, true_h

# --- Multi-monitor aware capture (Part 4) ---

_browser_offset = (0, 0)  # Global offset applied to board coords for multi-monitor

# --- Performance: cache window lookup ---
_cached_chess_window = None
_window_cache_time = 0
_WINDOW_CACHE_TTL = 1.0  # Re-lookup window position at most once per second

# --- Performance: persistent mss instance ---
_sct = None

def _get_sct():
    """Get or create persistent mss instance."""
    global _sct
    if _sct is None:
        _sct = mss.mss()
    return _sct

def _find_chess_window():
    """Find a browser window whose title contains 'Chess.com'. Cached for 1 second."""
    global _cached_chess_window, _window_cache_time
    
    now = time.monotonic()
    if now - _window_cache_time < _WINDOW_CACHE_TTL and _cached_chess_window is not None:
        # Refresh position from cached window handle (fast — no enumeration)
        try:
            win = _cached_chess_window
            if win.isMinimized:
                _cached_chess_window = None
                return None
            return win
        except Exception:
            _cached_chess_window = None
    
    try:
        windows = gw.getWindowsWithTitle("Chess.com")
        if windows:
            win = windows[0]
            if win.isMinimized:
                _cached_chess_window = None
                return None
            _cached_chess_window = win
            _window_cache_time = now
            return win
    except Exception:
        pass
    
    _cached_chess_window = None
    return None

def capture_screen() -> np.ndarray:
    """Capture the region containing the Chess.com window, or the full primary monitor."""
    global _browser_offset
    
    sct = _get_sct()
    chess_win = _find_chess_window()
    
    if chess_win is not None and chess_win.width > 100 and chess_win.height > 100:
        # Capture just the browser window region (works across monitors)
        monitor = {
            "left": chess_win.left,
            "top": chess_win.top,
            "width": chess_win.width,
            "height": chess_win.height,
        }
        _browser_offset = (chess_win.left, chess_win.top)
    else:
        # Fallback: full primary monitor
        monitor = sct.monitors[1]
        _browser_offset = (monitor["left"], monitor["top"])
    
    sct_img = sct.grab(monitor)
    img = np.array(sct_img)
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

cached_board_rect = None
_board_detect_count = 0
_SKIP_DETECT_FRAMES = 5  # Only run full Canny detection every N frames when board is stable

def clear_cache():
    global cached_board_rect, _board_detect_count
    cached_board_rect = None
    _board_detect_count = 0


def get_board_region(screen_img: np.ndarray) -> tuple | None:
    """Detect the chessboard and return its global screen coordinates."""
    global cached_board_rect, _board_detect_count
    
    # --- Performance: skip expensive detection if board is already cached and stable ---
    _board_detect_count += 1
    if cached_board_rect is not None and _board_detect_count % _SKIP_DETECT_FRAMES != 0:
        # Return cached result — board doesn't move between moves
        cx, cy, cw, ch = cached_board_rect
        gx = _browser_offset[0] + cx
        gy = _browser_offset[1] + cy
        return (gx, gy, cw, ch)
    
    gray = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)
    
    # --- Performance: Localized detection if we have a cached rect ---
    search_offset_x = 0
    search_offset_y = 0
    
    if cached_board_rect is not None:
        cx, cy, cw, ch = cached_board_rect
        margin = 50
        x1 = max(0, cx - margin)
        y1 = max(0, cy - margin)
        x2 = min(gray.shape[1], cx + cw + margin)
        y2 = min(gray.shape[0], cy + ch + margin)
        gray_roi = gray[y1:y2, x1:x2]
        search_offset_x = x1
        search_offset_y = y1
    else:
        gray_roi = gray
        
    edges = cv2.Canny(gray_roi, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    best_rect = None
    max_area = 0
    
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w >= 300 and h >= 300:
            aspect_ratio = w / float(h)
            if 0.95 <= aspect_ratio <= 1.05:
                area = w * h
                if area > max_area:
                    best_rect = (x, y, w, h)
                    max_area = area
                    
    if best_rect is None:
        if cached_board_rect is not None:
            # Fallback to full screen search if localized search fails (e.g. window moved aggressively)
            cached_board_rect = None
            return get_board_region(screen_img)
        return None
        
    x, y, w, h = best_rect
    x += search_offset_x
    y += search_offset_y
    
    # Dynamically crop out coordinate margins via column/row pixel variance
    x, y, w, h = refine_board((x, y, w, h), screen_img)
    
    # Suppress jitter feedback loop from overlay graphics changing contours
    # The overlay eval bar is 20px wide. If we capture our own overlay, the board 
    # might seem to expand by 20px. A threshold of 60 firmly ignores this feedback loop.
    if cached_board_rect is not None:
        cx, cy, cw, ch = cached_board_rect
        if abs(x - cx) < 60 and abs(y - cy) < 60 and abs(w - cw) < 60 and abs(h - ch) < 60:
            x, y, w, h = cx, cy, cw, ch
        else:
            cached_board_rect = (x, y, w, h)
    else:
        cached_board_rect = (x, y, w, h)

    # Enforce strict 1:1 aspect ratio to strip out any attached evaluation bars
    # Chess.com eval bar is typically attached to the left of the board.
    if w > h + 5:
        # Wider than tall: eval bar is likely on the left
        diff = w - h
        x += diff
        w = h
    elif h > w + 5:
        # Taller than wide: trim from the bottom/top (rare)
        diff = h - w
        y += diff // 2
        h = w
    
    # Absolute square guarantee
    w = min(w, h)
    h = w

    # Translate local capture coords to global screen coords (multi-monitor)
    gx = _browser_offset[0] + x
    gy = _browser_offset[1] + y
    
    return (gx, gy, w, h)

def get_local_board_rect(screen_img, board_rect):
    """Return the local (within-capture) coordinates for image slicing."""
    if board_rect is None:
        return None
    gx, gy, w, h = board_rect
    lx = gx - _browser_offset[0]
    ly = gy - _browser_offset[1]
    return (lx, ly, w, h)
