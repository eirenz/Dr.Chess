# Project Progress: Chess.com Live Analysis Overlay

This document captures the current implementation status, known bugs, and a roadmap for upcoming features.

## 🟩 Fully Implemented & Functional

| Component | Feature | Note |
| :--- | :--- | :--- |
| **Capture Layer** | Screen Grabbing | Native `mss` performance is excellent (high FPS). |
| **Capture Layer** | Multi-Monitor Support | Dynamic browser window detection via `pygetwindow`. |
| **Analysis Layer** | Stockfish Engine | UCI integration with multi-PV support via Subprocess. |
| **Analysis Layer** | Validation | Board state validation for Chess.com compatibility. |
| **Analysis Layer** | Depth Submenu | Adjustable analysis depth (10/15/18/20) from system tray. |
| **FEN Generation** | HSV Normalization | Neutralizes board highlights and last-move arrows. |
| **FEN Generation** | Template Matching | All 12 pieces mapped to standard themes (Neo). |
| **FEN Generation** | 3-Tier Orientation | Manual → COM → Fallback orientation with QSettings persistence. |
| **UI Engine** | Evaluation Bar | Smooth vertical bar with centipawn split animations. |
| **UI Engine** | Tactical Arrows | Multi-move overlay using QPainter with opacity support. |
| **UI Engine** | Indestructible Window | Win32 watchdog, double-buffered rendering, focus-safe flags. |
| **UI Engine** | Debug Mode | Real-time FPS, confidence, orientation source, error display. |
| **Feedback UI** | Classification | Move quality badges (Brilliant, Best, Mistake, Blunder, etc.). |
| **Feedback UI** | Sound Alerts | Programmatic WAV tones for Blunder and Brilliant moves. |
| **Infrastructure** | Multi-threading | Decoupled Capture, Analysis, and UI event loops. |
| **Infrastructure** | Global Hotkey | `Ctrl+Shift+T` toggle overlay via `pynput`. |
| **Infrastructure** | System Tray | Full context menu with all controls and settings. |

## 🟨 In-Progress / Known Quirks

| Component | Issue | Action Item |
| :--- | :--- | :--- |
| **Board Detection** | Detection Misses | Tuning Canny thresholds to handle low-contrast boards. |
| **Move Quality** | Centipawn Loss | Fine-tuning classification thresholds via `classifier.py`. |

## 🟥 Not Yet Implemented

- [ ] **Full History**: Tracking full game notation (PGN) for better engine context.
- [ ] **Sound Alerts**: Additional sounds for Mistake, Inaccuracy (currently only Blunder/Brilliant).
- [ ] **Custom Themes**: User-selectable piece themes beyond Neo.

## Current Priority Checklist
1. [ ] Test end-to-end with a live Chess.com game.
2. [ ] Fine-tune detection thresholds for various board themes.
3. [ ] Consider PGN tracking for move history.
