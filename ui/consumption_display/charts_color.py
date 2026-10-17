"""Color helper shared by the consumption charts (split from charts)."""
from __future__ import annotations



def _color_with_alpha(hex_color: str, alpha: float) -> str:
    channels = hex_color.lstrip("#")
    red = int(channels[0:2], 16)
    green = int(channels[2:4], 16)
    blue = int(channels[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"
