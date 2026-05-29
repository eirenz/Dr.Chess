"""Tests for grid-diff turn inference and parity enforcement."""

from fen_builder import _infer_turn_from_diff, reset_turn_tracking


def test_white_pawn_move():
    """White pawn e2->e4: white piece departs e2, arrives e4."""
    prev = ['.'] * 64
    curr = ['.'] * 64
    
    # Standard board orientation: row 0 = rank 8, row 7 = rank 1
    # e2 = row 6, col 4 = index 52
    # e4 = row 4, col 4 = index 36
    prev[52] = 'wp'  # White pawn on e2
    curr[36] = 'wp'  # White pawn moved to e4
    
    result = _infer_turn_from_diff(prev, curr)
    assert result == 'b', f"White pawn moved, expected 'b', got '{result}'"
    print("  [OK] White pawn e2->e4 -> Black's turn")


def test_black_knight_move():
    """Black knight b8->c6: black piece departs b8, arrives c6."""
    prev = ['.'] * 64
    curr = ['.'] * 64
    
    # b8 = row 0, col 1 = index 1
    # c6 = row 2, col 2 = index 18
    prev[1] = 'bn'   # Black knight on b8
    curr[18] = 'bn'   # Black knight on c6
    
    result = _infer_turn_from_diff(prev, curr)
    assert result == 'w', f"Black knight moved, expected 'w', got '{result}'"
    print("  [OK] Black knight b8->c6 -> White's turn")


def test_white_captures_black():
    """White bishop captures black pawn: white departs + arrives, black disappears."""
    prev = ['.'] * 64
    curr = ['.'] * 64
    
    # White bishop on c1 (index 58), black pawn on f4 (index 37)
    prev[58] = 'wb'  # White bishop on c1
    prev[37] = 'bp'  # Black pawn on f4
    
    # After capture: bishop on f4, c1 empty
    curr[37] = 'wb'  # White bishop captured on f4
    
    result = _infer_turn_from_diff(prev, curr)
    assert result == 'b', f"White captured black, expected 'b', got '{result}'"
    print("  [OK] White captures black -> Black's turn")


def test_black_captures_white():
    """Black rook captures white knight."""
    prev = ['.'] * 64
    curr = ['.'] * 64
    
    # Black rook on a8 (index 0), white knight on a2 (index 48)
    prev[0] = 'br'   # Black rook on a8
    prev[48] = 'wn'  # White knight on a2
    
    # After capture: rook on a2, a8 empty
    curr[48] = 'br'  # Black rook captured knight on a2
    
    result = _infer_turn_from_diff(prev, curr)
    assert result == 'w', f"Black captured white, expected 'w', got '{result}'"
    print("  [OK] Black captures white -> White's turn")


def test_no_change():
    """Identical grids should return None."""
    grid = ['.'] * 64
    grid[0] = 'bk'
    grid[63] = 'wk'
    
    result = _infer_turn_from_diff(grid, grid[:])
    assert result is None, f"No change, expected None, got '{result}'"
    print("  [OK] No change -> None")


def test_castling():
    """White kingside castling: king e1->g1 and rook h1->f1 (2 white pieces move)."""
    prev = ['.'] * 64
    curr = ['.'] * 64
    
    # e1 = row 7, col 4 = index 60
    # g1 = row 7, col 6 = index 62
    # h1 = row 7, col 7 = index 63
    # f1 = row 7, col 5 = index 61
    prev[60] = 'wk'  # King on e1
    prev[63] = 'wr'  # Rook on h1
    
    curr[62] = 'wk'  # King on g1
    curr[61] = 'wr'  # Rook on f1
    
    result = _infer_turn_from_diff(prev, curr)
    assert result == 'b', f"White castled, expected 'b', got '{result}'"
    print("  [OK] White castling -> Black's turn")


def test_none_prev_grid():
    """None prev_grid should return None."""
    curr = ['.'] * 64
    result = _infer_turn_from_diff(None, curr)
    assert result is None, f"None prev, expected None, got '{result}'"
    print("  [OK] None prev_grid -> None")


def test_reset_turn_tracking():
    """reset_turn_tracking should clear state without errors."""
    reset_turn_tracking()
    print("  [OK] reset_turn_tracking runs without error")


if __name__ == "__main__":
    print("Running turn inference tests...\n")
    test_white_pawn_move()
    test_black_knight_move()
    test_white_captures_black()
    test_black_captures_white()
    test_no_change()
    test_castling()
    test_none_prev_grid()
    test_reset_turn_tracking()
    print("\nAll turn inference tests passed!")
