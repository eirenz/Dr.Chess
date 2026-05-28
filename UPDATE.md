## Unified Improvement Prompt: Chess.com Live Overlay - Reliability & Orientation Fix

**Objective:** Refactor the PyQt5 overlay to be indestructible (always on top, no flicker) and implement a robust board orientation system that combines automatic detection with a reliable manual override.

**Context:**
- **Current State:** The overlay uses `mss` for capture, OpenCV for detection, and PyQt5 for rendering. It suffers from intermittent disappearance, focus conflicts, and unreliable board flipping when launched in endgames.
- **Goal:** The overlay must feel like a native part of the screen. It should *never* get hidden behind the browser. Orientation should be correct 99% of the time automatically, with a 1-click manual fix for edge cases.

---

### Part 1: Overlay Visibility & Window Management (Critical Priority)

**Problem:** The overlay window gets buried behind the browser or taskbar, flickers, or fails to appear after toggling.

**Implementation Requirements:**

1.  **Indestructible Window Flags:**
    ```python
    # Combine these exact flags for maximum z-order priority
    self.setWindowFlags(
        Qt.FramelessWindowHint |
        Qt.WindowStaysOnTopHint |
        Qt.Tool |
        Qt.WindowTransparentForInput |  # Clicks pass through to Chess.com
        Qt.WindowDoesNotAcceptFocus |   # Prevents stealing keyboard focus
        Qt.NoDropShadowWindowHint
    )
    self.setAttribute(Qt.WA_TranslucentBackground)
    self.setAttribute(Qt.WA_ShowWithoutActivating)
Windows-Specific Z-Order Enforcement (Watchdog):

Create a QTimer that fires every 500ms.

Inside the timer, use ctypes or win32gui to force the window handle (hwnd) to HWND_TOPMOST.

Crucial: If isVisible() returns False but self.should_be_visible is True, call show() and raise_() immediately.

python
# Pseudo-implementation for watchdog
if sys.platform == 'win32':
    import win32gui
    import win32con
    hwnd = int(self.winId())
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
Flicker-Free Rendering:

Implement Double Buffering: Paint all elements (eval bar, arrows, text) to a QPixmap buffer first, then draw the buffer to the screen in a single paintEvent.

Partial Updates: Only call update() when the board FEN changes or evaluation changes significantly (>5 centipawns). Do not repaint on every frame capture.

Part 2: Board Detection & Orientation Algorithm
Problem: The overlay needs to know if the user is playing White (bottom) or Black (top). Scraping UI elements (profile pictures) is banned due to layout shifts. We must use the pieces themselves.

Implementation Strategy:

The Center-of-Mass (COM) Heuristic (Automatic):

Logic: Calculate the average Y-coordinate of all detected White pieces and all detected Black pieces.

Rule: If avg_y_white > avg_y_black, the board is Standard (White at bottom). Else, Flipped (Black at bottom).

Confidence Check: Only apply COM auto-flip if:

At least 6 pieces are detected total.

The difference between the two averages is > 0.5 squares (to avoid noise from kings only).

Fallback for Mid-Game Launch (Endgame Edge Case):

Problem: If launched on move 45 with only a few pieces left, COM might be wrong or undefined.

Solution: If confidence is low (<6 pieces detected OR avg difference < 0.5 squares), do not auto-flip. Instead, default to Standard Orientation (White bottom) and rely on the user manual override.

Manual Override (The Permanent Fix):

System Tray Integration: Add a checkable menu item: "Flip Board Manually".

Behavior: When checked, it overrides the automatic COM detection completely.

Persistence: This setting should be stored in QSettings and remembered across app restarts.

Reset: Unchecking the item should revert to the automatic COM logic.

Part 3: The "Foolproof" Orientation Workflow
Implement the following logic flow in board_detector.py or orientation_manager.py:

python
def get_board_orientation(self, board_image):
    # 1. Check Manual Override First
    if self.settings.value("manual_flip", False, type=bool):
        return Orientation.FLIPPED
        
    # 2. Attempt Automatic Center-of-Mass Detection
    white_pieces, black_pieces = self.detect_pieces(board_image)
    
    if len(white_pieces) + len(black_pieces) >= 6:
        avg_y_w = np.mean([p.y for p in white_pieces]) if white_pieces else 0
        avg_y_b = np.mean([p.y for p in black_pieces]) if black_pieces else 0
        
        # If white pieces are lower on the screen (higher Y), it's White's perspective
        if avg_y_w > avg_y_b + 0.5: 
            return Orientation.STANDARD
        elif avg_y_b > avg_y_w + 0.5:
            return Orientation.FLIPPED
            
    # 3. Fallback: Default to Standard (or last known state)
    return self.last_valid_orientation
Part 4: Multi-Monitor & Dynamic Repositioning
Requirement: The overlay must follow the Chess.com window if the user drags it to another monitor.

Window Detection: Use pygetwindow to find the window titled "Chess.com" (works across Chrome, Edge, Firefox).

Coordinate Mapping: Translate the local board coordinates (detected via OpenCV) into global screen coordinates.

python
global_x = browser_window.left + board_local_x
global_y = browser_window.top + board_local_y
Re-acquisition Timer: Every 1 second, check if the browser window has moved or resized. If yes, seamlessly move the overlay to the new position without flickering (use self.move(x, y)).

Part 5: Debugging & Error Recovery
To prevent silent failures, add a Debug Mode toggle (activated by Ctrl+Shift+D).

Debug Overlay Display (Top-Left Corner):

Detection FPS: [Green if >20, Red if <10]

Board Confidence: [Score 0-100% based on pieces found]

Orientation Source: [AUTO-COM / MANUAL / FALLBACK]

Last Error: [None / Capture Failed / Engine Timeout]

Error Recovery:

If OpenCV detection fails for >3 seconds, display a semi-transparent red border around the overlay to alert the user that the board is lost. Do not crash the app.

