from dataclasses import dataclass

@dataclass
class MoveRating:
    label: str
    color: str
    symbol: str

def classify_move(cp_loss: int, is_sacrifice: bool = False) -> MoveRating:
    if is_sacrifice:
        return MoveRating("Brilliant", "#1baca6", "✦")
    
    if cp_loss <= 10:
        return MoveRating("Best", "#6dbb4f", "★")
    if cp_loss <= 30:
        return MoveRating("Excellent", "#96bc4b", "✓")
    if cp_loss <= 60:
        return MoveRating("Good", "#b0c44a", "✓")
    if cp_loss <= 100:
        return MoveRating("Inaccuracy", "#f0c55a", "?")
    if cp_loss <= 200:
        return MoveRating("Mistake", "#e07b38", "?!")
    
    return MoveRating("Blunder", "#cc3333", "??")
