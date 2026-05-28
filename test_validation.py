"""Tests for FEN plausibility validation (Layer 2) and orientation lock (Layer 1)."""

from fen_builder import validate_fen_plausibility, reset_orientation_lock, get_board_orientation


def test_validation_valid_positions():
    """Test that valid positions pass validation."""
    # Starting position
    ok, reason = validate_fen_plausibility("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR")
    assert ok, f"Starting position should be valid: {reason}"
    
    # Endgame: K+P vs K
    ok, reason = validate_fen_plausibility("8/8/8/4k3/8/8/4P3/4K3")
    assert ok, f"K+P vs K should be valid: {reason}"
    
    # Endgame: K+R vs K
    ok, reason = validate_fen_plausibility("8/8/8/4k3/8/8/8/R3K3")
    assert ok, f"K+R vs K should be valid: {reason}"
    
    print("  [OK] Valid positions pass")


def test_validation_pawns_on_rank_1_or_8():
    """Test that pawns on impossible ranks are rejected."""
    # Pawn on rank 8 (row 0 in FEN)
    ok, reason = validate_fen_plausibility("P7/8/8/4k3/8/8/8/4K3")
    assert not ok, "Pawn on rank 8 should be rejected"
    assert "rank 1 or 8" in reason
    
    # Pawn on rank 1 (row 7 in FEN)
    ok, reason = validate_fen_plausibility("8/8/8/4k3/8/8/8/4K2p")
    assert not ok, "Pawn on rank 1 should be rejected"
    assert "rank 1 or 8" in reason
    
    print("  [OK] Pawns on rank 1/8 rejected")


def test_validation_missing_kings():
    """Test that missing or extra kings are rejected."""
    # No white king
    ok, reason = validate_fen_plausibility("8/8/8/4k3/8/8/8/8")
    assert not ok, "Missing white king should be rejected"
    
    # Two white kings
    ok, reason = validate_fen_plausibility("8/8/8/4k3/8/8/4K3/4K3")
    assert not ok, "Two white kings should be rejected"
    
    print("  [OK] Missing/extra kings rejected")


def test_validation_excess_pawns():
    """Test that more than 8 pawns per side is rejected."""
    # 9 white pawns
    ok, reason = validate_fen_plausibility("4k3/8/8/8/8/PPPPPPPPP/PPPPPPPP1/4K3")
    # Note: This FEN is malformed (9 chars in a rank), but let's test with a valid one
    ok, reason = validate_fen_plausibility("4k3/8/8/P7/8/PPPPPPPP/PPPPPPPP/4K3")
    # This has 9 white pawns across ranks 3-4
    # Actually let's be more careful with the FEN format
    # Row with 8 pawns + 1 pawn on another row = 9 total
    ok, reason = validate_fen_plausibility("4k3/8/P7/8/8/8/PPPPPPPP/4K3")
    # That's only 9 pawns - exactly at the boundary. Let me make 9:
    # Actually the valid FEN above has exactly 9 Ps: 1 on rank 6 + 8 on rank 2
    assert not ok, f"9 white pawns should be rejected: {reason}"
    
    print("  [OK] Excess pawns rejected")


def test_validation_excess_pieces():
    """Test that more than 16 pieces per side is rejected."""
    # This shouldn't happen in practice but validates the check
    ok, reason = validate_fen_plausibility("rnbqkbnr/pppppppp/pppppppp/8/8/8/PPPPPPPP/RNBQKBNR")
    assert not ok, f"24 black pieces should be rejected: {reason}"
    
    print("  [OK] Excess total pieces rejected")


def test_orientation_lock():
    """Test that orientation locks after consistent readings."""
    reset_orientation_lock()
    
    # Simulate a standard board with many pieces
    # White pieces on rows 6-7, black pieces on rows 0-1
    grid = ['.'] * 64
    # Place white pieces on bottom (rows 6-7) — standard orientation
    for i in range(48, 56):  # Row 6: white pawns
        grid[i] = 'wp'
    for i in range(56, 64):  # Row 7: white pieces
        grid[i] = 'wr'
    # Place black pieces on top (rows 0-1)
    for i in range(0, 8):  # Row 0: black pieces
        grid[i] = 'br'
    for i in range(8, 16):  # Row 1: black pawns
        grid[i] = 'bp'
    
    # Should not be locked initially
    from fen_builder import is_orientation_locked
    assert not is_orientation_locked(), "Should not be locked initially"
    
    # Run orientation detection 5 times (the lock threshold)
    for i in range(5):
        is_flipped, source = get_board_orientation(grid)
        assert not is_flipped, f"Should detect standard orientation on reading {i+1}"
    
    # After 5 confident readings, should be locked
    assert is_orientation_locked(), "Should be locked after 5 confident readings"
    
    # Now even with an ambiguous grid (few pieces), it should stay locked
    sparse_grid = ['.'] * 64
    sparse_grid[0] = 'bk'
    sparse_grid[63] = 'wk'
    is_flipped, source = get_board_orientation(sparse_grid)
    assert not is_flipped, "Should stay standard (locked) even with sparse grid"
    assert "LOCKED" in source, f"Source should say LOCKED, got: {source}"
    
    # Reset should unlock
    reset_orientation_lock()
    assert not is_orientation_locked(), "Should be unlocked after reset"
    
    print("  [OK] Orientation lock works correctly")


if __name__ == "__main__":
    print("Running validation and orientation lock tests...\n")
    test_validation_valid_positions()
    test_validation_pawns_on_rank_1_or_8()
    test_validation_missing_kings()
    test_validation_excess_pawns()
    test_validation_excess_pieces()
    test_orientation_lock()
    print("\nAll tests passed!")
