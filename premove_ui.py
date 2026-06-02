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
                font-size: 14px;
                color: #00f2fe;
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
        
        self.lbl_sequence = QLabel("...")
        self.lbl_sequence.setObjectName("sequence")
        self.lbl_sequence.setWordWrap(True)
        self.lbl_sequence.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        self.toggle_btn = QPushButton("Show Premove Arrows: OFF")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self._on_toggle)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_sequence)
        layout.addWidget(self.toggle_btn)
        
        self.setLayout(layout)
        self.resize(250, 150)
        
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

    def update_mate(self, mate_in, san_sequence, board_rect):
        """
        board_rect is (x, y, w, h) of the chessboard
        """
        if mate_in is not None and mate_in > 0:
            if self.current_mate != mate_in:
                self.current_mate = mate_in
                self.lbl_title.setText(f"Forced Mate in {mate_in}!")
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
