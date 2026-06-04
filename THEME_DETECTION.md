# Theme Auto-Detection Engine

ChessOverlay uses a custom-built computer vision engine to automatically identify what piece theme and board background you are currently using on Chess.com. It requires zero manual configuration to track your games.

## How It Works

The engine uses three layers of processing to guarantee flawless detection on standard 2D boards:

1. **Adaptive Thresholding Calibration**
   The overlay actively scans the game board and calibrates an adaptive threshold based on the 40th percentile of image match scores. This dynamic calibration ensures that the engine can always find where pieces are located, regardless of whether the pieces cast deep shadows or have high contrast edges.

2. **High-Resolution Shape Discrimination (128x128)**
   Some themes use mathematically identical base shapes but apply subtle visual differences. For instance, the `neo` theme and the `alpha` theme are identical in geometry, but `alpha` has thicker stroke lines. The engine performs an initial one-off scan at a high `128x128` resolution to preserve these high-frequency stroke details, successfully distinguishing them.

3. **Full BGR Color Tiebreakers**
   Some themes are geometrically identical *and* share the same stroke weight, differing only by color tint (e.g., `classic` vs `icy_sea`, or `neo_wood` vs `marble`). To solve this, the template matching algorithm operates in the full 3-channel BGR color space instead of grayscale, running a secondary MSE (Mean Squared Error) color tiebreaker to definitively select the correct theme.

## 3D Theme Limitations

> [!WARNING]  
> **Dynamic 3D Rendering vs Static Template Matching**
> 
> The auto-detection engine performs flawlessly on **all 34 2D themes** (like `neo`, `marble`, `glass`, `metal`, etc.). However, there is a fundamental limitation when using **3D Piece Themes** (`3d_staunton`, `3d_wood`, `3d_plastic`, `3d_chesskid`).
>
> When you use a 3D theme on Chess.com, the browser runs a complex WebGL/CSS 3D renderer. The pieces cast dynamic, overlapping shadows that change depending on their position on the board and their neighboring pieces. 
>
> Our engine relies on "template matching" (comparing a flat, perfect 2D template against the screen). Because a 3D piece's visual representation changes constantly based on its shadows, the correlation math breaks down. While the overlay *will* detect that pieces exist on the board (thanks to the adaptive thresholding), it will struggle to reliably tell a 3D Pawn apart from a 3D Bishop.
>
> **Recommendation:** For competitive play or if you require 100% flawless overlay accuracy, we highly recommend using any of the standard 2D piece themes (like `neo`, `alpha`, `classic`).

## Pristine Assets
The engine uses pristine, uncompressed 150x150 piece assets pulled directly from the Chess.com CDN to ensure the template images perfectly match the browser output.
