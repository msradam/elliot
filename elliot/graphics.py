"""Kitty terminal graphics: detect support and emit image escape sequences.

The Kitty graphics protocol transmits a PNG and displays it inline, scaled to a
cell box. Ghostty, Kitty, and WezTerm speak it. asciinema cannot record it, so
the auto policy stays on the half-block renderer inside a recording.

Protocol reference: https://sw.kovidgoyal.net/kitty/graphics-protocol/
"""

from __future__ import annotations

import base64
import os

_CHUNK = 4096  # max base64 bytes per escape, per the protocol


def kitty_supported() -> bool:
    """True when the current terminal can display Kitty graphics."""
    if os.environ.get("ASCIINEMA_SESSION"):  # a recording must stay portable
        return False
    if os.environ.get("KITTY_WINDOW_ID"):
        return True
    if any(key.startswith("GHOSTTY_") for key in os.environ):
        return True
    if os.environ.get("TERM_PROGRAM", "").lower() in ("ghostty", "wezterm"):
        return True
    return "kitty" in os.environ.get("TERM", "")


def resolve_graphics(mode: str) -> str:
    """Resolve ``auto`` to ``kitty`` or ``half`` for the current terminal."""
    if mode in ("kitty", "half"):
        return mode
    return "kitty" if kitty_supported() else "half"


def place_image(png: bytes, cols: int, rows: int) -> str:
    """Escape sequence that draws ``png`` at the cursor, scaled to cols x rows."""
    payload = base64.standard_b64encode(png)
    chunks = [payload[i : i + _CHUNK] for i in range(0, len(payload), _CHUNK)] or [b""]
    parts: list[str] = []
    for i, chunk in enumerate(chunks):
        control = []
        if i == 0:
            control = [f"a=T,f=100,c={cols},r={rows},C=1,q=2"]
        control.append(f"m={1 if i < len(chunks) - 1 else 0}")
        parts.append(f"\x1b_G{','.join(control)};{chunk.decode('ascii')}\x1b\\")
    return "".join(parts)


def delete_images() -> str:
    """Escape sequence that removes every image (data and placements)."""
    return "\x1b_Ga=d,d=A,q=2\x1b\\"
