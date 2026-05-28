Project: Chess.com Live Analysis Overlay
Build a Python 3.10+ desktop overlay application that reads a live chess.com game from the screen using OpenCV template matching, analyzes positions with a locally installed Stockfish engine, and renders a transparent overlay window showing: an evaluation bar, colored move arrows (best/2nd best/fair move), and a move rating badge.
The project folder is D:\ChessOverlay\. All modules go in this root folder.

config.py
pythonSTOCKFISH_PATH = r"D:\ChessOverlay\stockfish\stockfish.exe"  # update this path
ANALYSIS_DEPTH = 18
CAPTURE_FPS = 2
PIECE_THEME = "neo"
PIECE_SIZE = 150
PIECES_DIR = r"D:\ChessOverlay\pieces"
MATCH_THRESHOLD = 0.72
MOVE_ANIM_DELAY_MS = 400
OVERLAY_OPACITY = 0.85
SHOW_SECOND_BEST = True
SHOW_FAIR_MOVE = True

capture.py

Use mss to take a full screenshot of the primary monitor.
Convert to a numpy array in BGR format for OpenCV.
Use cv2.Canny + cv2.findContours to detect the chessboard: find the largest contour that is approximately square (aspect ratio between 0.9 and 1.1) and large enough to be a board (min 300px side). Return its bounding box as (x, y, w, h).
Validate by checking that the detected region contains an 8×8 grid of evenly sized squares (divide width/height by 8 and check internal line consistency).
If no valid board is found, return None.
Expose: capture_screen() -> np.ndarray and get_board_region(screen_img: np.ndarray) -> tuple | None.


fen_builder.py
Template loading:

Load all 12 piece PNGs from {PIECES_DIR}/{PIECE_THEME}/. Filenames are all lowercase two-letter codes: wk.png, wq.png, wr.png, wb.png, wn.png, wp.png, bk.png, bq.png, br.png, bb.png, bn.png, bp.png.
Load each with cv2.imread(..., cv2.IMREAD_UNCHANGED) to preserve alpha channel if present.
Resize all templates to PIECE_SIZE × PIECE_SIZE.
Store as a dict: {"wk": img_array, "wq": img_array, ...}.
Expose load_templates() -> dict — call this once at startup.

Square extraction and normalization:

Divide the board image into 64 squares (8 rows × 8 cols). Square size = board_w // 8.
Resize each square to PIECE_SIZE × PIECE_SIZE.
Apply background neutralization before matching: convert to HSV, detect the square's background tone (chess.com light square ≈ #EEEED2, dark square ≈ #769656, highlight yellow ≈ #F6F669, highlight green ≈ #CDD26A). Use cv2.inRange to mask the background pixels and replace them with neutral gray (128, 128, 128). This prevents chess.com's last-move highlights from breaking template matching.

Matching:

For each normalized square, run cv2.matchTemplate(square, template, cv2.TM_CCOEFF_NORMED) for all 12 templates.
The piece with the highest score above MATCH_THRESHOLD is placed on that square. Below threshold = empty square (".").
Detect mid-animation frames by checking if the square's pixel variance exceeds 2000 — if so, skip this frame and return the previous board state unchanged.

FEN assembly:

Map piece codes to FEN characters: wk=K, wq=Q, wr=R, wb=B, wn=N, wp=P, bk=k, bq=q, br=r, bb=b, bn=n, bp=p.
Build the FEN placement string row by row, replacing consecutive empty squares with a digit.
For the active color: compare the current 8×8 grid to the previous one. If white pieces moved, active color = b. If black pieces moved, active color = w. Default to w on first frame.
Return simplified FEN: "{placement} {active_color} - - 0 1".
Expose: build_fen(board_img: np.ndarray, templates: dict, prev_grid: list | None) -> tuple[str, list] returning (fen_string, current_grid).


analyzer.py

Use chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) to start Stockfish once at startup.
For each FEN, call engine.analyse(board, chess.engine.Limit(depth=ANALYSIS_DEPTH), multipv=3).
Parse the result into a list of MoveResult dataclass objects with fields: uci: str, cp_score: int | None, mate_in: int | None, rank: int (1, 2, or 3).
For mate scores, convert to a large cp value: cp_score = 10000 if mate_in > 0 else -10000.
Track the previous best move's cp score. On each new analysis, compute cp_loss = prev_best_cp - current_best_cp to rate the move just played.
Return an AnalysisResult dataclass with fields: top_moves: list[MoveResult], cp_loss: int | None, best_cp: int.
Expose: start_engine(), stop_engine(), analyze(fen: str) -> AnalysisResult.
Use a persistent engine instance — never restart Stockfish between moves.


classifier.py

Define a MoveRating dataclass with fields: label: str, color: str, symbol: str.
Classify by centipawn loss:

Brilliant: engine-best AND is_sacrifice=True → color #1baca6, symbol ✦
Best: cp_loss ≤ 10 → color #6dbb4f, symbol ★
Excellent: cp_loss ≤ 30 → color #96bc4b, symbol ✓
Good: cp_loss ≤ 60 → color #b0c44a, symbol ✓
Inaccuracy: cp_loss ≤ 100 → color #f0c55a, symbol ?
Mistake: cp_loss ≤ 200 → color #e07b38, symbol ?!
Blunder: cp_loss > 200 → color #cc3333, symbol ??


A sacrifice is detected when the piece moving to a square has lower value than the piece currently occupying it (use standard values: P=1, N=3, B=3, R=5, Q=9).
Expose: classify_move(cp_loss: int, is_sacrifice: bool) -> MoveRating.


overlay.py
Window setup (PyQt6 — use correct PyQt6 enum paths):
pythonfrom PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMainWindow, QApplication

window.setWindowFlags(
    Qt.WindowType.FramelessWindowHint |
    Qt.WindowType.WindowStaysOnTopHint |
    Qt.WindowType.Tool
)
window.setAttribute(Qt.ApplicationAttribute.WA_TranslucentBackground)
window.setAttribute(Qt.ApplicationAttribute.WA_TransparentForMouseEvents)

Position and resize the window to match the board bounding box exactly.

paintEvent draws three layers using QPainter:

Evaluation bar — vertical bar on the left edge of the board, full board height, 20px wide.

Split point formula: split = int(bar_height * (0.5 - cp_score / 2000.0)) clamped to [5, bar_height - 5].
Top portion = dark fill #2b2b2b, bottom = white fill #ffffff.
Draw cp value as small text at the split point.
Animate the split point using a QVariantAnimation that interpolates the previous and new split values over 300ms.


Move arrows — convert UCI square notation to pixel centers:
pythoncol = ord(uci[0]) - ord('a')   # 0–7
row = 8 - int(uci[1])          # 0–7 top to bottom
px = board_x + col * sq + sq // 2
py = board_y + row * sq + sq // 2

If board is flipped (Black on bottom), reverse: col = 7 - col, row = 7 - row.
Draw each arrow as a QPainterPath: a line from source to target center, with a filled triangle arrowhead at the target.
Colors/widths: best = #4caf50 8px, 2nd best = #2196f3 5px, fair = #ffc107 5px. All at 60% opacity.


Move rating badge — top-right corner of the board, 10px inset.

Rounded rectangle background using the rating's hex color.
White text: f"{rating.symbol}  {rating.label}", font size 13px bold.
Fade in using QGraphicsOpacityEffect + QPropertyAnimation on opacity from 0.0 to 1.0 over 200ms on each new move.



Refresh:

QTimer at 500ms polls a queue.Queue for new AnalysisResult. On result received, store it and call self.update() to trigger repaint.


main.py

Call load_templates() and start_engine() at startup.
Thread 1 (capture thread): runs at CAPTURE_FPS. Captures screen → detects board → builds FEN. On detecting a board state change, sleeps MOVE_ANIM_DELAY_MS / 1000 seconds before pushing FEN to fen_queue to avoid mid-animation frames.
Thread 2 (analysis thread): consumes fen_queue → calls analyze(fen) → calls classify_move() → pushes AnalysisResult to result_queue.
Main thread: starts QApplication and QTimer, runs app.exec().
On 3 consecutive frames with no board detected: hide overlay, show a system tray balloon message "Chess board not found — waiting...".
System tray icon with context menu: Pause/Resume, Depth submenu (10 / 15 / 18 / 20), Flip Board, Quit.
On app exit: call stop_engine() and join threads cleanly.


test_fen_builder.py

Load a static screenshot of a chess.com starting position.
Run get_board_region() → build_fen() pipeline.
Assert the output FEN piece placement equals rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR.

test_classifier.py

Assert classify_move(5, False).label == "Best"
Assert classify_move(150, False).label == "Mistake"
Assert classify_move(300, False).label == "Blunder"
Assert classify_move(0, True).label == "Brilliant"


requirements.txt
PyQt6
python-chess
opencv-python
mss
numpy
requests