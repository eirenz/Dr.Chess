import sys
import time
import queue
import threading

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtCore import QSettings, QObject, pyqtSignal

import capture
import fen_builder
from analyzer import Analyzer
from overlay import ChessOverlay
import config
import sounds

# --- Inter-thread Queues ---
command_queue = queue.Queue()  # UI -> Capture Thread commands
fen_queue = queue.Queue(maxsize=1)
result_queue = queue.Queue(maxsize=1)


# --- Thread-safe signal bridge for global hotkey ---
class HotkeyBridge(QObject):
    toggle_signal = pyqtSignal()
    toggle_turn_signal = pyqtSignal()


def capture_thread_func():
    templates = fen_builder.load_templates()
    
    # "Confirmed" state — only updated when a move is actually accepted
    confirmed_grid = None
    confirmed_fen = ""
    confirmed_active_color = 'w'
    
    no_board_count = 0
    unmatched_frames_count = 0
    last_capture_time = time.time()
    
    while True:
        time.sleep(1.0 / config.CAPTURE_FPS)
        
        # Check command queue for manual overrides
        while not command_queue.empty():
            try:
                cmd = command_queue.get_nowait()
                if cmd == "TOGGLE_TURN":
                    confirmed_active_color = 'b' if confirmed_active_color == 'w' else 'w'
                    confirmed_fen = ""  # Force rebuild so it pushes new FEN immediately
                    print(f"MANUAL OVERRIDE: Turn set to {'White' if confirmed_active_color == 'w' else 'Black'}")
            except:
                pass
        
        try:
            screen_img = capture.capture_screen()
            board_rect = capture.get_board_region(screen_img)
        except Exception as e:
            print(f"Capture error: {e}")
            no_board_count += 1
            if no_board_count >= 3:
                capture.clear_cache()
                while not result_queue.empty():
                    try: result_queue.get_nowait()
                    except: pass
                result_queue.put("HIDE")
            continue
        
        if board_rect is None:
            no_board_count += 1
            if no_board_count >= 3:
                capture.clear_cache()
                while not result_queue.empty():
                    try: result_queue.get_nowait()
                    except: pass
                result_queue.put("HIDE")
            continue
            
        no_board_count = 0
        
        # Use local coordinates for image slicing
        local_rect = capture.get_local_board_rect(screen_img, board_rect)
        if local_rect is None:
            continue
        lx, ly, lw, lh = local_rect
        board_img = screen_img[ly:ly+lh, lx:lx+lw]
        
        if board_img.size == 0:
            continue
        
        # Build FEN using the last CONFIRMED FEN state as reference
        try:
            fen_str, current_grid, is_flipped, returned_active, orient_source, piece_count, matched = fen_builder.build_fen(
                board_img, templates, confirmed_fen, confirmed_active_color
            )
        except Exception as e:
            print(f"FEN build error: {e}")
            continue
        
        if fen_str is None:
            continue
        
        # Only process if something changed from the last confirmed FEN
        if fen_str == confirmed_fen:
            unmatched_frames_count = 0
            continue
            
        if not matched and confirmed_fen:
            unmatched_frames_count += 1
            if unmatched_frames_count < 3:
                continue
            else:
                print("3 consecutive unmatched frames. Resyncing board state visually!")
                unmatched_frames_count = 0
                forced_resync = True
        else:
            unmatched_frames_count = 0
            forced_resync = False
        
        # --- FAST PATH: If the first capture already matched a legal move, accept immediately ---
        if matched and not forced_resync:
            # Clean, legal-move-validated capture — no need to wait for animation
            now = time.time()
            fps = 1.0 / max(0.001, now - last_capture_time)
            last_capture_time = now
            
            while not fen_queue.empty():
                try: fen_queue.get_nowait()
                except: pass
                
            fen_queue.put({
                "fen": fen_str,
                "is_flipped": is_flipped,
                "board_rect": board_rect,
                "debug": {
                    "fps": fps,
                    "confidence": piece_count,
                    "orientation_source": orient_source,
                    "last_error": "None",
                }
            })
            
            confirmed_fen = fen_str
            confirmed_grid = current_grid
            confirmed_active_color = returned_active
            continue
        
        # --- SLOW PATH: Ambiguous change — wait for animation to settle, then re-capture ---
        time.sleep(config.MOVE_ANIM_DELAY_MS / 1000.0)
        
        try:
            screen_img2 = capture.capture_screen()
            board_rect2 = capture.get_board_region(screen_img2)
        except Exception:
            continue
        
        if board_rect2 is None:
            continue
        
        local_rect2 = capture.get_local_board_rect(screen_img2, board_rect2)
        if local_rect2 is None:
            continue
        lx2, ly2, lw2, lh2 = local_rect2
        board_img2 = screen_img2[ly2:ly2+lh2, lx2:lx2+lw2]
        
        if board_img2.size == 0:
            continue
        
        try:
            fen_str, current_grid, is_flipped, returned_active, orient_source, piece_count, matched2 = fen_builder.build_fen(
                board_img2, templates, confirmed_fen, confirmed_active_color
            )
        except Exception as e:
            print(f"FEN re-build error: {e}")
            continue
        
        if fen_str is None or fen_str == confirmed_fen:
            continue
            
        if not matched2 and not forced_resync and confirmed_fen:
            continue
        
        now = time.time()
        fps = 1.0 / max(0.001, now - last_capture_time)
        last_capture_time = now
        
        while not fen_queue.empty():
            try: fen_queue.get_nowait()
            except: pass
            
        fen_queue.put({
            "fen": fen_str,
            "is_flipped": is_flipped,
            "board_rect": board_rect2,
            "debug": {
                "fps": fps,
                "confidence": piece_count,
                "orientation_source": orient_source,
                "last_error": "None",
            }
        })
        
        confirmed_fen = fen_str
        confirmed_grid = current_grid
        confirmed_active_color = returned_active

def analysis_thread_func(analyzer):
    while True:
        msg = fen_queue.get()
        
        # Drain stale FENs — only analyze the most recent position
        while not fen_queue.empty():
            try:
                msg = fen_queue.get_nowait()
            except:
                break
        
        fen = msg["fen"]
        is_flipped = msg["is_flipped"]
        board_rect = msg["board_rect"]
        debug = msg.get("debug", {})
        
        res = analyzer.analyze(fen)
        
        # If a new FEN arrived during analysis, discard this stale result
        if not fen_queue.empty():
            continue
        
        if res is None:
            debug["last_error"] = "Engine Error"
            continue
        
        while not result_queue.empty():
            try: result_queue.get_nowait()
            except: pass
            
        result_queue.put({
            "result": res,
            "is_flipped": is_flipped,
            "board_rect": board_rect,
            "fen": fen,
            "debug": debug,
        })


def start_hotkey_listener(bridge: HotkeyBridge):
    try:
        from pynput import keyboard
        
        # Combine keys for toggle overlay
        curr_keys = set()
        COMBO_OVERLAY = {keyboard.Key.shift, keyboard.Key.ctrl, keyboard.KeyCode.from_char('T')}
        COMBO_OVERLAY2 = {keyboard.Key.shift, keyboard.Key.ctrl, keyboard.KeyCode.from_char('t')}
        
        # Combine keys for toggle turn
        COMBO_TURN = {keyboard.Key.shift, keyboard.Key.ctrl, keyboard.KeyCode.from_char('Y')}
        COMBO_TURN2 = {keyboard.Key.shift, keyboard.Key.ctrl, keyboard.KeyCode.from_char('y')}
        
        def on_press(key):
            curr_keys.add(key)
            if COMBO_OVERLAY.issubset(curr_keys) or COMBO_OVERLAY2.issubset(curr_keys):
                bridge.toggle_signal.emit()
            elif COMBO_TURN.issubset(curr_keys) or COMBO_TURN2.issubset(curr_keys):
                bridge.toggle_turn_signal.emit()
        
        def on_release(key):
            curr_keys.discard(key)
        
        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
        print("Global hotkeys: Ctrl+Shift+T (Toggle Overlay), Ctrl+Shift+Y (Toggle Turn)")
    except ImportError:
        print("Warning: pynput not installed — global hotkey disabled")
    except Exception as e:
        print(f"Warning: Could not start hotkey listener: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    settings = QSettings("ChessOverlay", "Settings")
    
    # Initialize sound alerts
    sounds.init_sounds()
    
    analyzer = Analyzer()
    analyzer.start_engine()
    
    t1 = threading.Thread(target=capture_thread_func, daemon=True)
    t2 = threading.Thread(target=analysis_thread_func, args=(analyzer,), daemon=True)
    
    t1.start()
    t2.start()
    
    overlay = ChessOverlay(result_queue)
    overlay.show()
    
    # --- Global Hotkey (Ctrl+Shift+T) ---
    hotkey_bridge = HotkeyBridge()
    hotkey_bridge.toggle_signal.connect(overlay.toggle_overlay)
    
    def on_toggle_turn():
        command_queue.put("TOGGLE_TURN")
        
    hotkey_bridge.toggle_turn_signal.connect(on_toggle_turn)
    start_hotkey_listener(hotkey_bridge)
    
    # --- System Tray with full menu ---
    tray = QSystemTrayIcon()
    icon = overlay.style().standardIcon(overlay.style().StandardPixmap.SP_ComputerIcon)
    tray.setIcon(icon)
    tray.setToolTip("Chess Overlay")
    
    menu = QMenu()
    
    # Toggle overlay visibility
    toggle_action = QAction("Toggle Overlay")
    toggle_action.triggered.connect(overlay.toggle_overlay)
    menu.addAction(toggle_action)
    
    # Toggle Turn actively
    turn_action = QAction("Switch Turn (White/Black)")
    turn_action.triggered.connect(lambda: command_queue.put("TOGGLE_TURN"))
    menu.addAction(turn_action)
    
    menu.addSeparator()
    
    # Flip Board Manually (checkable, persisted via QSettings)
    flip_action = QAction("Flip Board Manually")
    flip_action.setCheckable(True)
    flip_action.setChecked(settings.value("manual_flip", False, type=bool))
    
    def on_flip_toggled(checked):
        settings.setValue("manual_flip", checked)
        settings.sync()
        print(f"Manual flip {'enabled' if checked else 'disabled'} (persisted)")
    
    flip_action.toggled.connect(on_flip_toggled)
    menu.addAction(flip_action)
    
    menu.addSeparator()
    
    # --- Analysis Speed Submenu ---
    speed_menu = QMenu("Analysis Speed")
    speed_group = QActionGroup(speed_menu)
    speed_group.setExclusive(True)
    
    # Named presets
    preset_labels = {
        "Instant":  "Instant (d12 / 0.5s) — Bullet",
        "Fast":     "Fast (d16 / 1.0s) — Blitz",
        "Balanced": "Balanced (d18 / 1.5s) — Default",
        "Deep":     "Deep (d22 / 5.0s) — Classical",
        "Maximum":  "Maximum (d24 / No limit) — Full Power",
    }
    
    for preset_name, label in preset_labels.items():
        speed_action = QAction(label, speed_menu)
        speed_action.setCheckable(True)
        if preset_name == config.ACTIVE_SPEED_PRESET:
            speed_action.setChecked(True)
        
        def make_speed_handler(name):
            def handler(checked):
                if checked:
                    config.ACTIVE_SPEED_PRESET = name
                    d, t = config.SPEED_PRESETS[name]
                    print(f"Speed preset: {name} (depth={d}, time={'unlimited' if t == 0 else f'{t}s'})")
            return handler
        
        speed_action.toggled.connect(make_speed_handler(preset_name))
        speed_group.addAction(speed_action)
        speed_menu.addAction(speed_action)
    
    speed_menu.addSeparator()
    
    # Auto-Adaptive option
    auto_action = QAction("Auto-Adaptive (by piece count)", speed_menu)
    auto_action.setCheckable(True)
    if config.ACTIVE_SPEED_PRESET == "Auto":
        auto_action.setChecked(True)
    
    def on_auto_toggled(checked):
        if checked:
            config.ACTIVE_SPEED_PRESET = "Auto"
            print("Speed preset: Auto-Adaptive (adjusts depth/time by piece count)")
    
    auto_action.toggled.connect(on_auto_toggled)
    speed_group.addAction(auto_action)
    speed_menu.addAction(auto_action)
    
    menu.addMenu(speed_menu)
    
    # --- Engine ELO Submenu ---
    elo_menu = QMenu("Engine ELO (Strength)")
    elo_group = QActionGroup(elo_menu)
    elo_group.setExclusive(True)
    
    # 0 represents Max strength
    for elo_val, label in [(0, "Maximum"), (2500, "2500 (GM)"), (2000, "2000 (Expert)"), (1500, "1500 (Intermediate)"), (1000, "1000 (Beginner)")]:
        elo_action = QAction(label, elo_menu)
        elo_action.setCheckable(True)
        if elo_val == config.STOCKFISH_ELO:
            elo_action.setChecked(True)
        
        def make_elo_handler(e):
            def handler(checked):
                if checked:
                    config.STOCKFISH_ELO = e
                    print(f"Engine ELO changed to {e if e > 0 else 'Maximum'}")
            return handler
            
        elo_action.toggled.connect(make_elo_handler(elo_val))
        elo_group.addAction(elo_action)
        elo_menu.addAction(elo_action)
        
    menu.addMenu(elo_menu)
    
    menu.addSeparator()
    
    # --- Sound Alerts toggle ---
    sound_action = QAction("Sound Alerts")
    sound_action.setCheckable(True)
    sound_action.setChecked(config.SOUND_ALERTS_ENABLED)
    
    def on_sound_toggled(checked):
        config.SOUND_ALERTS_ENABLED = checked
        overlay.sound_enabled = checked
        print(f"Sound alerts {'ON' if checked else 'OFF'}")
    
    sound_action.toggled.connect(on_sound_toggled)
    menu.addAction(sound_action)
    
    menu.addSeparator()
    
    # Debug Mode toggle (Part 5 — via tray, not Ctrl+Shift+D)
    debug_action = QAction("Debug Mode")
    debug_action.setCheckable(True)
    debug_action.setChecked(config.DEBUG_MODE_DEFAULT)
    
    def on_debug_toggled(checked):
        overlay.debug_mode = checked
        overlay.update()
        print(f"Debug mode {'ON' if checked else 'OFF'}")
    
    debug_action.toggled.connect(on_debug_toggled)
    menu.addAction(debug_action)
    
    menu.addSeparator()
    
    # Exit
    exit_action = QAction("Exit")
    exit_action.triggered.connect(app.quit)
    menu.addAction(exit_action)
    
    tray.setContextMenu(menu)
    tray.show()
    
    app.exec()
    analyzer.stop_engine()
