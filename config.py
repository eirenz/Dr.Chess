STOCKFISH_PATH = r"D:\Downloads\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe"
STOCKFISH_ELO = 0  # 0 means Max/Unlimited
CAPTURE_FPS = 10
PIECE_THEME = "neo"
PIECE_SIZE = 150
PIECES_DIR = r"D:\ChessOverlay\pieces"
MATCH_THRESHOLD = 0.50
MOVE_ANIM_DELAY_MS = 150
OVERLAY_OPACITY = 0.85
SHOW_SECOND_BEST = True
SHOW_FAIR_MOVE = True
DEBUG_MODE_DEFAULT = False
SOUND_ALERTS_ENABLED = True

# ─── Speed Presets ───────────────────────────────────────────────
# Each preset is (depth, time_limit_seconds).
# time_limit=0 means unlimited (depth-only).
SPEED_PRESETS = {
    "Instant":   (12, 0.5),
    "Fast":      (16, 1.0),
    "Balanced":  (18, 1.5),
    "Deep":      (22, 5.0),
    "Maximum":   (24, 0),
}

# Active preset name. Set to "Auto" for adaptive mode.
ACTIVE_SPEED_PRESET = "Balanced"

# ─── Auto-Adaptive Thresholds ────────────────────────────────────
# When ACTIVE_SPEED_PRESET == "Auto", the system picks depth/time
# based on the number of pieces currently on the board.
# Format: (min_pieces, max_pieces, depth, time_limit)
AUTO_ADAPTIVE_TIERS = [
    (25, 32, 16, 1.0),   # Opening: many pieces, book-like — fast is fine
    (16, 24, 18, 1.5),   # Middlegame: need good tactical depth
    (8,  15, 20, 2.5),   # Late game: deeper search, still capped
    (0,   7, 22, 3.5),   # Endgame: maximum precision, generous time
]

# Legacy aliases (used if code references these directly)
ANALYSIS_DEPTH = 18
ANALYSIS_TIME_LIMIT = 1.5
