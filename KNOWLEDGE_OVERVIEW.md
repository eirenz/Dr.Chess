# Dr.Chess Overlay — Master Knowledge Document
**Project:** Dr.Chess — A real-time Chess.com analysis overlay powered by Stockfish  
**Workspace:** `d:\ChessOverlay NEWWWWWWWWWWWWW - Copy`  
**Last Updated:** 2026-06-22  

---

## 1. Project Philosophy

Dr.Chess is a **non-intrusive, fully visual** chess assistant. It:
- **Never touches the browser or Chess.com** — no browser extensions, no injected scripts.
- Reads the game state entirely via **computer vision** on the screen.
- Feeds that state to **Stockfish** for analysis.
- Draws move suggestions as transparent arrows over the board using a **PyQt6 overlay window**.

The chain of decisions made during this project consistently prioritized **accuracy over speed** — a wrong move suggestion is worse than a slow one.

---

## 2. The Central Bug: Why the Overlay Hallucinated

### The Symptom
The overlay suggested moves like **Qxf6** (black queen takes knight on f6) when that was completely wrong. Stockfish was receiving an incorrect board state (FEN) and computing optimal moves for the wrong position.

### The Chain of Failures
```
User plays move
    ↓
Evaluation bar included in board bounding box
    ↓
Board image is 656×648 (NOT square) instead of 648×648
    ↓
8x8 grid sliced from a non-square image
    ↓
All columns shifted ~1 pixel right
    ↓
White King on e1 now falls outside template crop window
    ↓
White King not detected → board state has 0 white kings
    ↓
FEN validation fails → overlay falls back to previous FEN
    ↓
Wrong FEN sent to Stockfish → bad move suggested
```

### The Fix
Force the captured board to be a perfect square by trimming off any excess width from the left (where the Chess.com evaluation bar sits).

---

## 3. The Central Performance Bug: Why Moves Were Slow to Suggest

### The Symptom
After making a move (especially a piece drag), the overlay would freeze for ~5 seconds before suggesting the next move.

### The Chain of Failures
```
User drags piece (piece lifted off board)
    ↓
King disappears from image mid-drag (~20 frames)
    ↓
build_fen() fails 1-ply and 2-ply legal move validation
    ↓
Resync fallback triggers detect_best_theme()
    ↓
detect_best_theme() scans board against ALL 35 themes
    ↓
This takes ~5 seconds
    ↓
User has already dropped piece but overlay is frozen
    ↓
After freeze, resync detects same theme → wasted effort
```

### The Fix
Remove `detect_best_theme()` from the resync loop entirely. Theme is detected once on launch, stored, and never changed until restart.

---

## 4. Critical Design Decisions

### 4.1 Background Neutralization — Median, Not Mean
When neutralizing the board color behind each piece, the code samples a ring of border pixels and takes the **median** color.

**Why not mean?**  
If a large piece (like a rook or queen) extends to the border of the square, those colored pixels would pollute the mean and produce an incorrect background estimate. The median rejects outliers — piece pixels that overlap the ring sample zone.

### 4.2 Template Size — 64px, Not 48px
Template matching is done at 64×64 pixels, not the smaller 48×48 that was tested.

**Why not 48?**  
On static test images, 48×48 worked fine. But real Chess.com in a browser applies sub-pixel anti-aliasing to piece images. At 48×48, this blurring pushes edge pieces (especially the King on e1/e8, and edge pawns) below the `0.6` template correlation threshold. The King effectively disappears to the algorithm.

### 4.3 Orientation Lock After 5 Confident Frames
The overlay determines if the player is White or Black by computing the **Center of Mass** of all detected pieces. If the heavy pieces are in the bottom half, the player is White.

This runs every frame until it gets 5 consecutive consistent readings — then it **locks**. After locking, it never recalculates (preventing jitter during piece captures where the center of mass temporarily shifts).

### 4.4 Legal Move Validation Before Accepting Any FEN
The overlay never sends a FEN to Stockfish just because computer vision computed it. It must pass three layers:
1. **1-ply match:** Is the new board state reachable in exactly 1 legal move from the previous confirmed state?
2. **2-ply match:** Is it reachable in 2 half-moves? (Catches frames that were missed during animation.)
3. **Plausibility:** Does the board have exactly 1 White king and 1 Black king? Are piece counts reasonable?

This is why the overlay is resistant to "vision glitches" — a blurred animation frame will never produce a false move suggestion.

### 4.5 Stockfish with Retry Loop
Stockfish is initialized in a retry loop (3 attempts, 500ms sleep between) because Windows Defender sometimes performs a real-time scan of the newly launched Stockfish process at the exact moment Python tries to open its I/O pipes — causing a 0xC0000005 access violation.

---

## 5. Computer Vision Pipeline (Per Frame)

```
Screen Captured
    ↓
Window-localized ROI (±50px around last known board position)
    ↓
Canny edge detection → find largest square contour
    ↓
Aspect ratio enforcement (trim eval bar → perfect square)
    ↓
Scaled to 800×800
    ↓
Sliced into 64 individual squares (each ~100×100)
    ↓
Each square → scale to 64×64
    ↓
Ring-sample border pixels → compute median background color
    ↓
Subtract background → neutralized 64×64 square
    ↓
Template matching vs 12 templates (6 pieces × 2 colors)
    ↓
Best match above threshold → piece label
    ↓
64 labels assembled into 8×8 grid
    ↓
Grid → FEN string (rank notation)
    ↓
1-ply / 2-ply legal validation
    ↓
If valid: push to Stockfish analysis queue
```

---

## 6. Theme Detection Pipeline (Once on Launch)

```
Board image captured (first valid frame)
    ↓
Scaled to 128×128 (higher res for accuracy)
    ↓
For each of 35 known themes:
    - Load that theme's piece templates
    - Sample 5 "reference squares" (known occupied positions in starting position)
    - Neutralize each square
    - Run template match for expected piece
    - Score = sum of correlation values
    ↓
Theme with highest score wins
    ↓
Load winning theme's templates as permanent active templates
    ↓
Store as _theme_auto_detected (never changes until restart)
```

---

## 7. Stockfish Configuration

```python
engine.configure({
    "Hash": 128,    # 128MB hash table
    "Threads": 2,   # 2 CPU threads
})
```

Analysis presets (configurable in the tray menu):
| Preset | Depth | Time |
|--------|-------|------|
| Casual | 12 | 0.3s |
| Standard | 18 | 1.0s |
| Deep | 24 | 3.0s |

Stockfish path: `D:\Downloads\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe`

---

## 8. Known Piece Themes Supported

The overlay supports all Chess.com piece themes by automatically downloading piece images from the CDN:

| Theme | Notes |
|-------|-------|
| neo | Default Chess.com theme. Good accuracy. |
| classic | High accuracy (clean silhouettes). |
| alpha | High accuracy (simple flat design). |
| neo_wood | Wooden variant of neo. |
| icy_sea | Light blue tones. Color detection harder. |
| marble | Near-white pieces on marble. Hardest. |
| 3d_staunton | 3D perspective. Lowest accuracy. |
| newspaper | Black/white only. Moderate accuracy. |
| ... | 35 themes total |

---

## 9. Files Modified During This Conversation

| File | What Changed |
|------|-------------|
| `fen_builder.py` | Background neutralization, template sizing, theme detection, legal validation, resync logic, turn inference, removed mid-game theme redetection |
| `capture.py` | Localized ROI detection, window caching, persistent mss instance, eval bar square enforcement |
| `main.py` | Removed 150ms sleep bottleneck, non-blocking FEN queue, separated confirmed vs unconfirmed state |
| `analyzer.py` | Added retry loop for Stockfish initialization, Hash/Threads configuration |

---

## 10. Test Scripts Created

| Script | Purpose |
|--------|---------|
| `test_full_sweep.py` | Runs all 35 themes through all starting-position moves, reports accuracy |
| `test_full_game.py` | Simulates a full game with piece moves and verifies FEN at each step |
| `test_user_position.py` | Tests FEN detection on a user-supplied screenshot |
| `test_multiple_images.py` | Batch tests multiple board screenshots |
| `test_latest_image.py` | Quickly tests the most recently saved debug screenshot |
| `test_edge_match.py` | Tests template matching on edge-column squares only (where failures occur most) |
| `evaluate_detector.py` | Measures theme detection accuracy across a dataset |
| `test_validation.py` | Unit tests for the FEN plausibility validator |
| `generate_dataset.py` | Generates synthetic board images for test dataset |

---

## 11. Unresolved / Future Work

1. **Debug image dump in production:** `cv2.imwrite("debug_failed_pieces.png")` fires on every rejected frame. Should be gated behind a `DEBUG=True` flag.
2. **3D theme accuracy:** 3D Staunton and similar perspective themes remain the weakest link. A CNN-based piece classifier would outperform template matching for these.
3. **Mid-game theme switch:** If user changes Chess.com piece theme while the overlay is running, must restart overlay. No hot-reload.
4. **Castling rights and en passant:** FEN castling/en passant strings are currently approximated. For 100% Stockfish accuracy in edge cases, these need proper tracking across moves.
5. **Multi-monitor support:** The board offset tracking works for most setups but may drift on certain DPI scaling configurations.

---

## 12. The Chain of Thought — What We Learned

The most important lesson of this project was that **small geometric errors cascade into catastrophic logical failures**.

An 8-pixel shift in the board bounding box — caused by an evaluation bar nobody thought to exclude — resulted in the White King being completely invisible to the computer vision system. This led to every FEN being invalid, which led to the overlay spamming logs with validation failures and never suggesting any moves.

The second lesson was that **performance optimizations that seem safe on static tests can fail on live rendering**. The 48×48 downsampling worked perfectly on raw screenshot files. But live browser rendering uses sub-pixel anti-aliasing that blurs piece pixels just enough to cross the correlation threshold, making pieces disappear.

The third lesson was that **fallback code can be more dangerous than no fallback at all**. The mid-game theme re-detection was added as a "safety net" in case the theme changed. Instead, it became a 5-second freeze trigger that fired on every piece drag. The best fix was to remove it entirely.

---

*Preserved for continuity of the Dr.Chess development chain of thought.*
*Never lose the context. Never lose the reasoning.*
