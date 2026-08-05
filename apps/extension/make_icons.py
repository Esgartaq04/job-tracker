"""Generate the extension icons — a white hexagon on the app's indigo, matching the
⬢ mark in the web header. Written by hand rather than pulled from a design tool so the
repo has no binary asset nobody can regenerate.

    python make_icons.py
"""

import struct
import zlib
from pathlib import Path

BACKGROUND = (99, 102, 241)  # accent
FOREGROUND = (255, 255, 255)


def hexagon_contains(x: float, y: float, cx: float, cy: float, radius: float) -> bool:
    """Point-in-regular-hexagon (flat-top), by the standard half-plane test."""
    dx = abs(x - cx) / radius
    dy = abs(y - cy) / radius
    return dy <= 0.8660254 and (0.8660254 * dx + 0.5 * dy) <= 0.8660254


def render(size: int) -> bytes:
    center = size / 2 - 0.5
    outer = size * 0.42
    rows = bytearray()

    for y in range(size):
        rows.append(0)  # PNG filter type 0 (None) for this scanline
        for x in range(size):
            # 2x2 supersampling: cheap antialiasing on the hexagon's diagonals.
            covered = sum(
                hexagon_contains(x + ox, y + oy, center, center, outer)
                for ox in (0.25, 0.75)
                for oy in (0.25, 0.75)
            ) / 4
            rows.extend(
                round(background + (foreground - background) * covered)
                for background, foreground in zip(BACKGROUND, FOREGROUND, strict=True)
            )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    icons = Path(__file__).parent / "icons"
    icons.mkdir(exist_ok=True)
    for size in (48, 128):
        path = icons / f"icon-{size}.png"
        path.write_bytes(render(size))
        print(f"wrote {path} ({path.stat().st_size} bytes)")
