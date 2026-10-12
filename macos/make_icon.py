"""Draw the Spec-to-Test app icon as a 1024x1024 PNG (standard library only).

Usage: python make_icon.py OUTPUT.png
"""

import math
import struct
import sys
import zlib

SIZE = 1024

TOP = (99, 102, 241)  # indigo-500
BOTTOM = (67, 56, 202)  # indigo-700
PAGE = (255, 255, 255)
LINE = (199, 202, 245)
CHECK_BG = (16, 185, 129)  # emerald-500


def rounded_rect(px: float, py: float, cx: float, cy: float, hw: float, hh: float, r: float) -> float:
    """Signed distance to a rounded rectangle centred at (cx, cy)."""
    qx = abs(px - cx) - hw + r
    qy = abs(py - cy) - hh + r
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - r


def circle(px: float, py: float, cx: float, cy: float, r: float) -> float:
    return math.hypot(px - cx, py - cy) - r


def segment(px: float, py: float, ax: float, ay: float, bx: float, by: float, w: float) -> float:
    """Distance to a thick line segment with round caps."""
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy) - w


def coverage(d: float) -> float:
    return max(0.0, min(1.0, 0.5 - d))


def over(dst: list[float], color: tuple[int, int, int], a: float) -> None:
    if a <= 0.0:
        return
    for i in range(3):
        dst[i] = dst[i] * (1 - a) + color[i] * a
    dst[3] = dst[3] * (1 - a) + a


def pixel(x: int, y: int) -> bytes:
    px, py = x + 0.5, y + 0.5
    c = [0.0, 0.0, 0.0, 0.0]

    # macOS icon grid: 824x824 rounded square, centred.
    a = coverage(rounded_rect(px, py, 512, 512, 412, 412, 185))
    if a > 0:
        t = (py - 100) / 824
        grad = tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        over(c, grad, a)  # type: ignore[arg-type]

    # The specification page with text lines.
    over(c, PAGE, coverage(rounded_rect(px, py, 470, 480, 190, 245, 36)))
    for i, length in enumerate((250, 290, 220, 270, 160)):
        ly = 330 + i * 62
        over(c, LINE, coverage(segment(px, py, 350, ly, 350 + length - 60, ly, 14)))

    # The "test passed" badge.
    over(c, PAGE, coverage(circle(px, py, 660, 680, 150)))
    over(c, CHECK_BG, coverage(circle(px, py, 660, 680, 126)))
    tick = min(
        segment(px, py, 595, 685, 640, 732, 22),
        segment(px, py, 640, 732, 728, 625, 22),
    )
    over(c, PAGE, coverage(tick))

    alpha = c[3]
    if alpha == 0:
        return b"\x00\x00\x00\x00"
    return bytes((round(c[0]), round(c[1]), round(c[2]), round(alpha * 255)))


def write_png(path: str) -> None:
    rows = bytearray()
    for y in range(SIZE):
        rows.append(0)  # filter: none
        for x in range(SIZE):
            rows += pixel(x, y)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", header))
        f.write(chunk(b"IDAT", zlib.compress(bytes(rows), 9)))
        f.write(chunk(b"IEND", b""))


if __name__ == "__main__":
    write_png(sys.argv[1])
