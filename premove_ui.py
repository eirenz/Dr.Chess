import sys
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal

class PremoveDialog(QWidget):
    # Signal emitted when toggle is clicked (sends boolean state)
    toggled = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        # Tool window (no taskbar entry), stays on top, does not steal focus
        self.setWindowFlags(
            Qt.WindowType.Tool | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowTitle("Premove Sequence")
        
        # Make the window semi-transparent and styled
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(30, 30, 30, 240);
                color: white;
                border-radius: 10px;
                font-family: 'Segoe UI', Arial;
            }
            QLabel#title {
                font-size: 16px;
                font-weight: bold;
                color: #ff3333;
            }
            QLabel#sequence {
                font-size: 12px;
                color: #aaaaaa;
                padding: 5px;
            }
            QLabel#safe_sequence {
                font-size: 14px;
                color: #ffd700;
                font-weight: bold;
                padding: 10px;
                background: rgba(0,0,0,100);
                border-radius: 5px;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px;
                font-weight: bold;
            }
            QPushButton:checked {
                background-color: #f44336;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        
        self.lbl_title = QLabel("Mate Detected!")
        self.lbl_title.setObjectName("title")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.lbl_safe_sequence = QLabel("...")
        self.lbl_safe_sequence.setObjectName("safe_sequence")
        self.lbl_safe_sequence.setWordWrap(True)
        self.lbl_safe_sequence.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        self.lbl_sequence = QLabel("...")
        self.lbl_sequence.setObjectName("sequence")
        self.lbl_sequence.setWordWrap(True)
        self.lbl_sequence.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        self.toggle_btn = QPushButton("Show Premove Arrows: OFF")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self._on_toggle)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.lbl_title)
        layout.addWidget(QLabel("Safe Premoves:"))
        layout.addWidget(self.lbl_safe_sequence)
        layout.addWidget(QLabel("Full Sequence:"))
        layout.addWidget(self.lbl_sequence)
        layout.addWidget(self.toggle_btn)
        
        self.setLayout(layout)
        self.resize(250, 200)
        
        self.is_enabled = False
        self.current_mate = None

    def _on_toggle(self, checked):
        self.is_enabled = checked
        if checked:
            self.toggle_btn.setText("Hide Premove Arrows")
            self.toggle_btn.setStyleSheet("background-color: #f44336;")
        else:
            self.toggle_btn.setText("Show Premove Arrows: OFF")
            self.toggle_btn.setStyleSheet("background-color: #4CAF50;")
        self.toggled.emit(checked)

    def update_mate(self, mate_in, san_sequence, safe_san_sequence, board_rect):
        """
        board_rect is (x, y, w, h) of the chessboard
        """
        if mate_in is not None and mate_in > 0:
            if self.current_mate != mate_in:
                self.current_mate = mate_in
                
                # If the entire sequence is safe, the safe_san_sequence will equal san_sequence
                if safe_san_sequence and safe_san_sequence == san_sequence:
                    self.lbl_title.setText(f"Forced Mate in {mate_in}! (100% SAFE)")
                    self.lbl_title.setStyleSheet("color: #4CAF50;")
                    self.lbl_safe_sequence.setText(safe_san_sequence)
                    self.lbl_sequence.setText("All moves are strictly forced.")
                else:
                    self.lbl_title.setText(f"Forced Mate in {mate_in}!")
                    self.lbl_title.setStyleSheet("color: #ff3333;")
                    self.lbl_safe_sequence.setText(safe_san_sequence if safe_san_sequence else "None. Play normally.")
                    self.lbl_sequence.setText(san_sequence)
                
            if self.isHidden():
                # Position it slightly to the right of the board
                x, y, w, h = board_rect
                self.move(x + w + 20, y + 50)
                # Show without stealing focus
                self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
                self.show()
        else:
            self.current_mate = None
            if not self.isHidden():
                self.hide()
