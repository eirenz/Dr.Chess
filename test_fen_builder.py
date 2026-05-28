import cv2
import config
from fen_builder import build_fen, load_templates

def test_fen():
    img = cv2.imread("test_board.png")
    if img is None:
        print("Mock image not found, skipping test")
        return
        
    templates = load_templates()
    fen_str, grid, is_flipped, active_color, orient_src, piece_count = build_fen(img, templates, None)
    
    expected = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
    
    assert fen_str is not None
    assert expected in fen_str, f"Expected {expected} in {fen_str}"
    assert is_flipped == False
    assert active_color == 'w'
    print("test_fen_builder passed")

if __name__ == "__main__":
    test_fen()
