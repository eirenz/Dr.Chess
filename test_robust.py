import cv2
import numpy as np

def generate_test_image():
    # board is 800x800. margins are 25px bottom and left.
    board_size = 800
    sq = board_size // 8
    img = np.zeros((board_size + 25, board_size + 25, 3), dtype=np.uint8)
    img[:, :] = (50, 50, 50) # background
    
    # Draw true board from x=25, y=0 to w=800, h=800
    for r in range(8):
        for c in range(8):
            color = (200, 200, 200) if (r+c)%2==0 else (100, 100, 100)
            img[r*sq:(r+1)*sq, 25+c*sq:25+(c+1)*sq] = color

    cv2.imwrite('fake_capture.png', img)

def refine_board(rect, img):
    x, y, w, h = rect
    roi = img[y:y+h, x:x+w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    
    col_vars = np.var(gray, axis=0)
    row_vars = np.var(gray, axis=1)
    
    col_threshold = np.max(col_vars) * 0.2
    row_threshold = np.max(row_vars) * 0.2
    
    valid_cols = np.where(col_vars > col_threshold)[0]
    valid_rows = np.where(row_vars > row_threshold)[0]
    
    if len(valid_cols) == 0 or len(valid_rows) == 0:
        return rect
        
    true_x = x + valid_cols[0]
    true_y = y + valid_rows[0]
    true_w = valid_cols[-1] - valid_cols[0]
    true_h = valid_rows[-1] - valid_rows[0]
    
    return true_x, true_y, true_w, true_h

if __name__ == "__main__":
    generate_test_image()
    img = cv2.imread('fake_capture.png')
    res = refine_board((0, 0, 825, 825), img)
    print("Original: 0, 0, 825, 825")
    print("Refined:", res)
