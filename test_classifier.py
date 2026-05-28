from classifier import classify_move

def test_classifier():
    assert classify_move(5, False).label == "Best"
    assert classify_move(150, False).label == "Mistake"
    assert classify_move(300, False).label == "Blunder"
    assert classify_move(0, True).label == "Brilliant"
    print("test_classifier passed")

if __name__ == "__main__":
    test_classifier()
