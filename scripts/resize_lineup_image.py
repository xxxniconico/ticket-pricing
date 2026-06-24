#!/usr/bin/env python3
"""Resize guoan_lineup_no_crowd.png to match original source dimensions."""
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow", "-q"])
    from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ORIG_SRC = ROOT / "assets" / "c__Users_xxxsu_AppData_Roaming_Cursor_User_workspaceStorage_8c6e00948550c15aa352041a8a2adbba_images_f143bb6f35c79e7519e04fcafc0f93e9-39908be9-b4e7-4050-a245-aa2120b9c2f7.png"
# fallback: cursor assets path
CURSOR_ASSETS = Path("/mnt/c/Users/xxxsu/.cursor/projects/wsl-Ubuntu-home-xxxsuli-ticket-pricing/assets")
if not ORIG_SRC.exists() and CURSOR_ASSETS.exists():
    for p in CURSOR_ASSETS.glob("*f143bb6f*.png"):
        ORIG_SRC = p
        break

EDITED = ROOT / "assets" / "guoan_lineup_no_crowd.png"
if not EDITED.exists() and (CURSOR_ASSETS / "guoan_lineup_no_crowd.png").exists():
    EDITED = CURSOR_ASSETS / "guoan_lineup_no_crowd.png"

OUT = ROOT / "assets" / "guoan_lineup_no_crowd.png"

if not ORIG_SRC.exists():
    print("Original not found:", ORIG_SRC)
    sys.exit(1)
if not EDITED.exists():
    print("Edited not found:", EDITED)
    sys.exit(1)

orig = Image.open(ORIG_SRC)
edited = Image.open(EDITED)
print(f"Original: {orig.size[0]}x{orig.size[1]}")
print(f"Edited:   {edited.size[0]}x{edited.size[1]}")

resized = edited.resize(orig.size, Image.Resampling.LANCZOS)
OUT.parent.mkdir(parents=True, exist_ok=True)
resized.save(OUT, quality=95, optimize=True)
# mirror to cursor assets if different
cursor_out = CURSOR_ASSETS / "guoan_lineup_no_crowd.png"
if cursor_out.parent.exists():
    resized.save(cursor_out, quality=95, optimize=True)

print(f"Saved: {OUT} ({resized.size[0]}x{resized.size[1]})")
