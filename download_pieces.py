import requests, os

base_url = "https://assets-themes.chess.com/image/ejgfv/150"

pieces = ["wK","wQ","wR","wB","wN","wP",
          "bK","bQ","bR","bB","bN","bP"]

os.makedirs("pieces/neo", exist_ok=True)

for p in pieces:
    url = f"{base_url}/{p.lower()}.png"  # notice lowercase: wk, wq, etc.
    r = requests.get(url)
    if r.status_code == 200:
        with open(f"pieces/neo/{p}.png", "wb") as f:
            f.write(r.content)
        print(f"✓ Downloaded {p}.png")
    else:
        print(f"✗ Failed {p}.png — status {r.status_code}")