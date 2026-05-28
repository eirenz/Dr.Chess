import chess.engine
import config

engine = chess.engine.SimpleEngine.popen_uci(config.STOCKFISH_PATH)
try:
    for name, option in engine.options.items():
        print(f"{name}: {option.type} [min: {option.min}, max: {option.max}]")
finally:
    engine.quit()
