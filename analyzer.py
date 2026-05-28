import chess
import chess.engine
import config
import threading
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class MoveResult:
    uci: str
    cp_score: Optional[int]
    mate_in: Optional[int]
    rank: int

@dataclass
class AnalysisResult:
    top_moves: List[MoveResult]
    cp_loss: Optional[int]
    best_cp: int
    depth_reached: int     # Actual depth Stockfish reached
    time_used: float       # Seconds spent analyzing
    preset_used: str       # Which preset/tier was active

class Analyzer:
    def __init__(self):
        self.engine = None
        self.prev_best_cp_white = None
        self._current_elo = None
        self._cancel_event = threading.Event()

    def start_engine(self):
        if not self.engine:
            self.engine = chess.engine.SimpleEngine.popen_uci(config.STOCKFISH_PATH)
            try:
                self.engine.configure({"Hash": 128, "Threads": 2})
            except Exception:
                pass

    def stop_engine(self):
        if self.engine:
            try:
                self.engine.quit()
            except chess.engine.EngineTerminatedError:
                pass
            except Exception:
                pass
            self.engine = None
    
    def cancel_analysis(self):
        """Signal that the current analysis should be abandoned (new FEN arrived)."""
        self._cancel_event.set()
    
    def _get_analysis_params(self, fen: str) -> tuple[int, float, str]:
        """
        Determine (depth, time_limit, label) based on the active speed preset.
        
        For "Auto" mode, counts pieces in the FEN and selects the appropriate tier
        from config.AUTO_ADAPTIVE_TIERS.
        """
        preset_name = config.ACTIVE_SPEED_PRESET
        
        if preset_name == "Auto":
            # Count pieces from the FEN placement string (everything before the first space)
            placement = fen.split()[0]
            piece_count = sum(1 for ch in placement if ch.isalpha())
            
            # Find the matching adaptive tier
            for min_p, max_p, depth, time_limit in config.AUTO_ADAPTIVE_TIERS:
                if min_p <= piece_count <= max_p:
                    tier_label = f"Auto({piece_count}pc: d{depth}/{time_limit}s)"
                    return depth, time_limit, tier_label
            
            # Fallback if no tier matches (shouldn't happen)
            return 18, 1.5, "Auto(fallback)"
        
        # Named preset
        if preset_name in config.SPEED_PRESETS:
            depth, time_limit = config.SPEED_PRESETS[preset_name]
            return depth, time_limit, preset_name
        
        # Unknown preset — use Balanced
        return 18, 1.5, "Balanced"
    
    def analyze(self, fen: str) -> Optional[AnalysisResult]:
        """
        Analyze a position using the active speed preset.
        Returns AnalysisResult with metadata about depth reached and time used.
        """
        self._cancel_event.clear()
        
        try:
            board = chess.Board(fen)
            if not board.king(chess.WHITE) or not board.king(chess.BLACK):
                return None
                
            if self._current_elo != config.STOCKFISH_ELO:
                self._current_elo = config.STOCKFISH_ELO
                if self._current_elo <= 0:
                    self.engine.configure({"UCI_LimitStrength": False})
                else:
                    self.engine.configure({"UCI_LimitStrength": True, "UCI_Elo": self._current_elo})
            
            # Get depth/time from the active preset
            depth, time_limit, preset_label = self._get_analysis_params(fen)
            
            import time as _time
            t0 = _time.perf_counter()
            
            # Build the engine limit — time=0 means depth-only (no time cap)
            if time_limit > 0:
                limit = chess.engine.Limit(depth=depth, time=time_limit)
            else:
                limit = chess.engine.Limit(depth=depth)
            
            res = self.engine.analyse(board, limit, multipv=3)
            
            elapsed = _time.perf_counter() - t0
            
            # Check if this analysis was cancelled (new FEN arrived while we were thinking)
            if self._cancel_event.is_set():
                return None
            
            top_moves = []
            max_depth = 0
            for i, info in enumerate(res):
                score = info["score"].white()
                mate_in = None
                if score.is_mate():
                    mate_in = score.mate()
                    cp_score = 10000 if mate_in > 0 else -10000
                else:
                    cp_score = score.score()
                
                top_moves.append(MoveResult(
                    uci=info.get("pv", [chess.Move.null()])[0].uci() if "pv" in info else "",
                    cp_score=cp_score,
                    mate_in=mate_in,
                    rank=i + 1
                ))
                max_depth = max(max_depth, info.get("depth", 0))
                
            current_best_cp_white = top_moves[0].cp_score if top_moves else 0
            
            cp_loss = None
            if self.prev_best_cp_white is not None:
                if not board.turn:  # White just moved
                    cp_loss = self.prev_best_cp_white - current_best_cp_white
                else:               # Black just moved
                    cp_loss = current_best_cp_white - self.prev_best_cp_white
                
                cp_loss = max(0, cp_loss)
                
            self.prev_best_cp_white = current_best_cp_white
            
            return AnalysisResult(
                top_moves=top_moves,
                cp_loss=cp_loss,
                best_cp=current_best_cp_white,
                depth_reached=max_depth,
                time_used=elapsed,
                preset_used=preset_label,
            )
        except chess.engine.EngineTerminatedError as e:
            print(f"Engine crashed: {e}")
            self.stop_engine()
            self.start_engine()
            return None
        except Exception as e:
            print(f"Analysis error: {e}")
            return None
