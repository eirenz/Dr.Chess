import cv2
import numpy as np
import os
import config

def generate_board():
    sq = config.PIECE_SIZE
    board = np.zeros((sq*8, sq*8, 3), dtype=np.uint8)
    
    light = (210, 238, 238)
    dark = (86, 150, 118)
    
    for r in range(8):
        for c in range(8):
            color = light if (r + c) % 2 == 0 else dark
            board[r*sq:(r+1)*sq, c*sq:(c+1)*sq] = color

    standard_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
    pieces = {
        'r': 'br', 'n': 'bn', 'b': 'bb', 'q': 'bq', 'k': 'bk', 'p': 'bp',
        'R': 'wr', 'N': 'wn', 'B': 'wb', 'Q': 'wq', 'K': 'wk', 'P': 'wp'
    }
    
    fen_parts = standard_fen.split('/')
    
    templates = {}
    theme_dir = os.path.join(config.PIECES_DIR, config.PIECE_THEME)
    for p in pieces.values():
        img = cv2.imread(os.path.join(theme_dir, f"{p}.png"), cv2.IMREAD_UNCHANGED)
        if img is not None:
            templates[p] = cv2.resize(img, (sq, sq))
            
    for r, row_str in enumerate(fen_parts):
        c = 0
        for char in row_str:
            if char.isdigit():
                c += int(char)
            else:
                p = pieces[char]
                if p in templates:
                    tmpl = templates[p]
                    if len(tmpl.shape) == 3 and tmpl.shape[2] == 4:
                        alpha = tmpl[:, :, 3] / 255.0
                        for i in range(3):
                            board[r*sq:(r+1)*sq, c*sq:(c+1)*sq, i] = \
                                (1.0 - alpha) * board[r*sq:(r+1)*sq, c*sq:(c+1)*sq, i] + \
                                alpha * tmpl[:, :, i]
                    else:
                        board[r*sq:(r+1)*sq, c*sq:(c+1)*sq] = tmpl
                c += 1
                
    cv2.imwrite("test_board.png", board)
    print("Mock board generated: test_board.png")

if __name__ == "__main__":
    generate_board()
