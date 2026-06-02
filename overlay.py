import sys
import time
import math
import queue

from PyQt6.QtCore import Qt, QTimer, QPoint, QPointF, QPropertyAnimation, QVariantAnimation
from PyQt6.QtWidgets import QMainWindow, QLabel, QGraphicsOpacityEffect, QSystemTrayIcon, QStyle, QMenu, QApplication
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QPixmap, QLinearGradient

import config
from classifier import classify_move
import sounds
from premove_ui import PremoveDialog

# Win32 z-order enforcement
if sys.platform == 'win32':
    import win32gui
    import win32con


class ChessOverlay(QMainWindow):
    def __init__(self, result_queue):
        super().__init__()
        self.result_queue = result_queue
        self.is_flipped = False
        self.should_be_visible = True
        
        self.premove_dialog = PremoveDialog()
        self.premove_dialog.toggled.connect(self.update)
        
        # --- Part 1: Indestructible Window Flags ---
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        if sys.platform == 'win32':
            import ctypes
            try:
                # Hide the overlay from screen captures (like mss) so it doesn't break OpenCV
                hwnd = int(self.winId())
                ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x0011) # WDA_EXCLUDEFROMCAPTURE
            except Exception as e:
                print(f"Could not set window display affinity: {e}")
        
        # Eval bar animation
        self.split_val = 100
        self.cp_text = "0.0"
        
        self.top_moves = []
        
        self.anim_split = QVariantAnimation(self)
        self.anim_split.setDuration(300)
        self.anim_split.valueChanged.connect(self._on_split_change)
        
        # Move rating badge
        self.badge = QLabel(self)
        self.badge.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.hide()
        
        self.effect = QGraphicsOpacityEffect(self.badge)
        self.badge.setGraphicsEffect(self.effect)
        self.anim_opacity = QPropertyAnimation(self.effect, b"opacity")
        self.anim_opacity.setDuration(200)
        self.anim_opacity.setStartValue(0.0)
        self.anim_opacity.setEndValue(1.0)
        
        # Forced Mate badge
        self.mate_badge = QLabel(self)
        self.mate_badge.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.mate_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mate_badge.hide()
        
        self.mate_effect = QGraphicsOpacityEffect(self.mate_badge)
        self.mate_badge.setGraphicsEffect(self.mate_effect)
        self.mate_anim = QPropertyAnimation(self.mate_effect, b"opacity")
        self.mate_anim.setDuration(200)
        self.mate_anim.setStartValue(0.0)
        self.mate_anim.setEndValue(1.0)
        
        # --- Part 1: Partial update gating ---
        self.last_fen = ""
        self.last_cp = 0
        
        # --- Part 5: Debug mode state ---
        self.debug_mode = config.DEBUG_MODE_DEFAULT
        self.debug_info = {
            "fps": 0.0,
            "confidence": 0,
            "orientation_source": "N/A",
            "last_error": "None",
        }
        self._detection_fail_start = None  # Track consecutive detection failures
        self._board_lost = False
        
        # --- Sound alerts ---
        self.sound_enabled = config.SOUND_ALERTS_ENABLED
        self._sound_blunder = None
        self._sound_brilliant = None
        self._init_sounds()
        
        # --- Result queue polling timer ---
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_result_queue)
        self.timer.start(200)
        
        # --- Part 1: Win32 Watchdog Timer (500ms) ---
        self.watchdog_timer = QTimer()
        self.watchdog_timer.timeout.connect(self._enforce_topmost)
        self.watchdog_timer.start(500)
        
        # System tray (basic — full tray setup happens in main.py)
        self.is_hidden = False

    def _init_sounds(self):
        """Initialize QSoundEffect objects for alert tones."""
        try:
            from PyQt6.QtMultimedia import QSoundEffect
            from PyQt6.QtCore import QUrl
            
            blunder_path = sounds.get_blunder_path()
            brilliant_path = sounds.get_brilliant_path()
            
            if blunder_path:
                self._sound_blunder = QSoundEffect(self)
                self._sound_blunder.setSource(QUrl.fromLocalFile(blunder_path))
                self._sound_blunder.setVolume(0.7)
            
            if brilliant_path:
                self._sound_brilliant = QSoundEffect(self)
                self._sound_brilliant.setSource(QUrl.fromLocalFile(brilliant_path))
                self._sound_brilliant.setVolume(0.7)
            
            print("Sound effects loaded")
        except ImportError:
            print("Warning: PyQt6.QtMultimedia not available — sound alerts disabled")
        except Exception as e:
            print(f"Warning: Could not initialize sounds: {e}")

    def _play_alert_sound(self, rating_label: str):
        """Play an alert sound based on the move rating."""
        if not self.sound_enabled:
            return
        try:
            if rating_label == "Blunder" and self._sound_blunder:
                self._sound_blunder.play()
            elif rating_label == "Brilliant" and self._sound_brilliant:
                self._sound_brilliant.play()
        except Exception:
            pass

    def _enforce_topmost(self):
        """Win32 watchdog: force HWND_TOPMOST every 500ms."""
        if not self.should_be_visible:
            return
            
        if sys.platform == 'win32':
            try:
                hwnd = int(self.winId())
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                )
            except Exception:
                pass
        
        # Recovery: if should be visible but isn't
        if not self.isVisible() and self.should_be_visible and not self.is_hidden:
            self.show()
            self.raise_()

    def toggle_overlay(self):
        self.is_hidden = not self.is_hidden
        if self.is_hidden:
            self.should_be_visible = False
            self.hide()
            self.badge.hide()
        else:
            self.should_be_visible = True
            self.show()
            self.raise_()

    def _on_split_change(self, val):
        self.split_val = float(val)
        self.update()

    def check_result_queue(self):
        try:
            msg = None
            while not self.result_queue.empty():
                msg = self.result_queue.get_nowait()
            
            if msg is None:
                return
                
            if msg == "HIDE":
                # Board lost — track for debug error display
                if self._detection_fail_start is None:
                    self._detection_fail_start = time.time()
                if self._detection_fail_start and (time.time() - self._detection_fail_start) > 3.0:
                    self._board_lost = True
                    self.debug_info["last_error"] = "Board Lost"
                    self.update()  # Repaint to show red border
                self.hide()
                return
            
            # Board found — reset failure tracking
            self._detection_fail_start = None
            self._board_lost = False
                
            res = msg["result"]
            self.is_flipped = msg["is_flipped"]
            bx, by, bw, bh = msg["board_rect"]
            
            # Update debug info
            if "debug" in msg:
                self.debug_info.update(msg["debug"])
            
            # --- Part 1: Partial update gating ---
            current_fen = msg.get("fen", "")
            current_cp = res.best_cp
            fen_changed = current_fen != self.last_fen
            cp_changed = abs(current_cp - self.last_cp) > 5
            
            self.last_fen = current_fen
            self.last_cp = current_cp
            
            # Give the eval bar 20px of space outside the true board
            bar_w = 20
            win_x = bx - bar_w
            win_y = by
            win_w = bw + bar_w
            win_h = bh
            
            geom_changed = self.geometry().getRect() != (win_x, win_y, win_w, win_h)
            if geom_changed:
                self.split_val = win_h / 2.0
            
            self.setGeometry(win_x, win_y, win_w, win_h)
            
            if not self.is_hidden:
                self.should_be_visible = True
                self.show()
                self.raise_()
            
            # Only repaint if something meaningful changed
            if fen_changed or cp_changed or geom_changed:
                self.update()
            
            self.top_moves = res.top_moves
            
            h = self.height()
            score = res.best_cp
            factor = score / 2000.0
            target = int(h * (0.5 - factor))
            target = max(5, min(h - 5, target))
            
            self.anim_split.stop()
            self.anim_split.setStartValue(float(self.split_val))
            self.anim_split.setEndValue(float(target))
            self.anim_split.start()
            
            if self.top_moves and self.top_moves[0].mate_in is not None:
                mate_in = self.top_moves[0].mate_in
                
                # Update premove dialog with full sequence
                self.premove_dialog.update_mate(
                    mate_in, 
                    self.top_moves[0].san_sequence, 
                    self.top_moves[0].safe_san_sequence,
                    (win_x, win_y, win_w, win_h)
                )
                
                if mate_in > 0:
                    self.cp_text = f"M{mate_in}"
                    if not self.is_hidden:
                        self.mate_badge.setText(f"MATE IN {mate_in}")
                        self.mate_badge.setStyleSheet("background-color: rgba(30, 215, 96, 220); color: white; border-radius: 8px;")
                        self.mate_badge.setGeometry(bar_w + 10, 10, 160, 40)
                        self.mate_badge.show()
                else:
                    self.cp_text = f"-M{abs(mate_in)}"
                    if not self.is_hidden:
                        self.mate_badge.setText(f"MATE IN {abs(mate_in)}")
                        self.mate_badge.setStyleSheet("background-color: rgba(255, 30, 30, 220); color: white; border-radius: 8px;")
                        self.mate_badge.setGeometry(bar_w + 10, 10, 160, 40)
                        self.mate_badge.show()
            else:
                self.cp_text = f"{score/100:.1f}"
                self.mate_badge.hide()
                self.premove_dialog.update_mate(None, "", "", (0,0,0,0))
                
            if res.cp_loss is not None and not self.is_hidden:
                rating = classify_move(res.cp_loss)
                self.badge.setText(f"{rating.symbol}  {rating.label}")
                self.badge.setStyleSheet(f"background-color: {rating.color}; color: white; border-radius: 5px;")
                self.badge.setGeometry(self.width() - 150, 10, 140, 30)
                
                self.anim_opacity.setDirection(QPropertyAnimation.Direction.Forward)
                self.badge.show()
                self.anim_opacity.start()
                
                # Play sound alert for blunders and brilliants
                self._play_alert_sound(rating.label)
                
                QTimer.singleShot(4000, self._hide_badge_anim)
            else:
                self.badge.hide()
                
        except queue.Empty:
            pass

    def _hide_badge_anim(self):
        self.anim_opacity.setDirection(QPropertyAnimation.Direction.Backward)
        self.anim_opacity.start()

    def paintEvent(self, event):
        # --- Part 1: Double-buffered rendering ---
        w = self.width()
        h = self.height()
        
        if w <= 0 or h <= 0:
            return
        
        buffer = QPixmap(w, h)
        buffer.fill(QColor(0, 0, 0, 0))  # Transparent
        
        painter = QPainter(buffer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        bar_w = 20
        
        # --- Eval bar ---
        painter.fillRect(0, 0, bar_w, h, QColor("#2b2b2b"))
        painter.fillRect(0, int(self.split_val), bar_w, h - int(self.split_val), QColor("#ffffff"))
        
        painter.setPen(QPen(QColor("#000000") if self.split_val < h/2 else QColor("#ffffff")))
        font = painter.font()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(0, int(self.split_val - 10), bar_w, 20, Qt.AlignmentFlag.AlignCenter, self.cp_text)
        
        # --- Modern Comet Arrows ---
        sq = (w - bar_w) // 8
        
        # New vibrant gradient colors:
        # 1. Electric Cyan
        # 2. Vivid Purple
        # 3. Bright Amber
        color_stops = [
            "#00f2fe",
            "#ff0844",
            "#f6d365"
        ]
        
        widths = [10, 7, 7] # Slightly thicker main body
        glow_widths = [18, 12, 12] # Underlying thicker glow
        
        for i, move in enumerate(self.top_moves):
            if i >= 3: break
            if i == 1 and not config.SHOW_SECOND_BEST: continue
            if i == 2 and not config.SHOW_FAIR_MOVE: continue
            
            if not move.uci or len(move.uci) < 4: continue
            
            ucis_to_draw = [move.uci]
            is_premove = False
            
            if i == 0 and move.mate_in is not None and getattr(self, 'premove_dialog', None) and self.premove_dialog.is_enabled:
                if getattr(move, 'safe_pv_sequence', None):
                    ucis_to_draw = move.safe_pv_sequence
                    is_premove = True
            
            for j, uci_str in enumerate(ucis_to_draw):
                if len(uci_str) < 4: continue
                
                scol = ord(uci_str[0]) - ord('a')
                srow = 8 - int(uci_str[1])
                tcol = ord(uci_str[2]) - ord('a')
                trow = 8 - int(uci_str[3])
                
                if self.is_flipped:
                    scol, srow = 7 - scol, 7 - srow
                    tcol, trow = 7 - tcol, 7 - trow
                    
                x1 = bar_w + scol * sq + sq / 2
                y1 = srow * sq + sq / 2
                x2 = bar_w + tcol * sq + sq / 2
                y2 = trow * sq + sq / 2
                
                if x1 == x2 and y1 == y2: continue
                
                if is_premove:
                    base_opacity = max(0.2, config.OVERLAY_OPACITY - (j * 0.15))
                    base_color = QColor("#ffd700") # Safe Gold
                    arrow_w = max(4, widths[0] - j)
                    glow_w = max(8, glow_widths[0] - j)
                else:
                    base_color = QColor(color_stops[i])
                    base_opacity = config.OVERLAY_OPACITY
                    arrow_w = widths[i]
                    glow_w = glow_widths[i]
                
                color_target = QColor(base_color)
                color_target.setAlphaF(base_opacity)
                
                color_source = QColor(base_color)
                color_source.setAlphaF(0.0) # Fade to transparent at source

                # Create body gradient
                gradient = QLinearGradient(QPointF(x1, y1), QPointF(x2, y2))
                gradient.setColorAt(0.0, color_source)
                gradient.setColorAt(1.0, color_target)

                # Create glow gradient (more transparent, wider)
                glow_grad = QLinearGradient(QPointF(x1, y1), QPointF(x2, y2))
                glow_color = QColor(base_color)
                glow_color.setAlphaF(0.0)
                glow_grad.setColorAt(0.0, glow_color)
                glow_color.setAlphaF(base_opacity * 0.4)
                glow_grad.setColorAt(1.0, glow_color)
                
                # --- Draw Glow ---
                glow_pen = QPen(QBrush(glow_grad), glow_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.setPen(glow_pen)
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))
                
                # --- Draw Main Body ---
                main_pen = QPen(QBrush(gradient), arrow_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                painter.setPen(main_pen)
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))
                
                # --- Draw Arrow Head ---
                angle = math.atan2(y2 - y1, x2 - x1)
                arrow_len = arrow_w * 3
                
                p1 = QPoint(int(x2 - arrow_len * math.cos(angle - math.pi / 6)),
                            int(y2 - arrow_len * math.sin(angle - math.pi / 6)))
                p2 = QPoint(int(x2 - arrow_len * math.cos(angle + math.pi / 6)),
                            int(y2 - arrow_len * math.sin(angle + math.pi / 6)))
                
                painter.setBrush(QBrush(color_target))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPolygon([QPoint(int(x2), int(y2)), p1, p2])
                
                # --- Draw Sequence Number Badge (if premove) ---
                if is_premove:
                    mid_x = (x1 + x2) / 2
                    mid_y = (y1 + y2) / 2
                    
                    badge_radius = 12
                    
                    # Draw background circle
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(30, 30, 30, 220)) # Dark transparent bg
                    painter.drawEllipse(QPoint(int(mid_x), int(mid_y)), badge_radius, badge_radius)
                    
                    # Draw border
                    border_color = QColor(base_color)
                    border_color.setAlphaF(1.0)
                    painter.setPen(QPen(border_color, 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPoint(int(mid_x), int(mid_y)), badge_radius, badge_radius)
                    
                    # Draw number text
                    badge_font = painter.font()
                    badge_font.setPixelSize(13)
                    badge_font.setBold(True)
                    painter.setFont(badge_font)
                    painter.setPen(QColor(255, 255, 255)) # White text
                    painter.drawText(
                        int(mid_x) - badge_radius, 
                        int(mid_y) - badge_radius, 
                        badge_radius * 2, 
                        badge_radius * 2, 
                        Qt.AlignmentFlag.AlignCenter, 
                        str(j + 1)
                    )
                
                # --- Draw Mate Text on Arrow ---
                if move.mate_in is not None and j == 0:
                    # Draw text with a small dark outline for readability
                    mate_str = f"M{abs(move.mate_in)}"
                    text_x = x2 - arrow_len * 2.0 * math.cos(angle)
                    text_y = y2 - arrow_len * 2.0 * math.sin(angle)
                    
                    mate_font = painter.font()
                    mate_font.setPixelSize(16 if i == 0 else 12) # Bigger for top move
                    mate_font.setBold(True)
                    painter.setFont(mate_font)
                    
                    rect_x, rect_y = int(text_x) - 20, int(text_y) - 10
                    
                    # Outline
                    painter.setPen(QPen(QColor("#000000"), 3))
                    painter.drawText(rect_x, rect_y, 40, 20, Qt.AlignmentFlag.AlignCenter, mate_str)
                    # Fill
                    painter.setPen(QPen(QColor("#ffffff")))
                    painter.drawText(rect_x, rect_y, 40, 20, Qt.AlignmentFlag.AlignCenter, mate_str)

        # --- Part 5: Red border when board is lost ---
        if self._board_lost:
            border_pen = QPen(QColor(255, 0, 0, 150), 4)
            painter.setPen(border_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(bar_w, 0, w - bar_w, h)

        # --- Part 5: Debug overlay panel ---
        if self.debug_mode:
            self._paint_debug_panel(painter, bar_w)
        
        painter.end()
        
        # Blit buffer to screen in one shot
        screen_painter = QPainter(self)
        screen_painter.drawPixmap(0, 0, buffer)
        screen_painter.end()

    def _paint_debug_panel(self, painter, bar_w):
        """Render debug info panel in the top-left corner of the board area."""
        panel_w = 240
        panel_h = 126
        panel_x = bar_w + 5
        panel_y = 5
        
        # Semi-transparent background
        painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(panel_x, panel_y, panel_w, panel_h, 6, 6)
        
        font = painter.font()
        font.setPixelSize(12)
        font.setBold(False)
        font.setFamily("Consolas")
        painter.setFont(font)
        
        fps = self.debug_info.get("fps", 0)
        fps_color = QColor("#4caf50") if fps >= 1.5 else QColor("#f44336")
        
        # Get theme info
        try:
            import fen_builder
            theme_name = fen_builder.get_active_theme_name()
            auto_tag = " (auto)" if fen_builder.is_theme_auto_detected() else ""
        except Exception:
            theme_name = "N/A"
            auto_tag = ""
        
        # Turn indicator
        active_turn = self.debug_info.get("active_turn", "w")
        turn_str = "White" if active_turn == "w" else "Black"
        turn_color = QColor("#e8f5e9") if active_turn == "w" else QColor("#ef9a9a")
        
        lines = [
            (f"FPS: {fps:.1f}", fps_color),
            (f"Confidence: {self.debug_info.get('confidence', 0)}/32 pieces", QColor("#ffffff")),
            (f"Orient: {self.debug_info.get('orientation_source', 'N/A')}", QColor("#2196f3")),
            (f"Theme: {theme_name}{auto_tag}", QColor("#ce93d8")),
            (f"Turn: {turn_str}", turn_color),
            (f"Error: {self.debug_info.get('last_error', 'None')}", QColor("#ffc107")),
        ]
        
        y = panel_y + 15
        for text, color in lines:
            painter.setPen(QPen(color))
            painter.drawText(panel_x + 8, y, text)
            y += 18

