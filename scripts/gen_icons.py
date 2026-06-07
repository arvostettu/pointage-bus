"""Génère les icônes PWA (PNG) sans dépendance externe (zlib + struct).

Dessine un bus blanc stylisé sur fond bleu. Lancer :  python3 scripts/gen_icons.py
Les PNG sont écrits dans app/static/ et commités comme assets.
"""

import os
import struct
import zlib

BG = (37, 99, 235)       # bleu marque
BODY = (244, 246, 251)   # blanc cassé
GLASS = (147, 197, 253)  # vitres
WHEEL = (17, 24, 39)     # roues
LIGHT = (250, 204, 21)   # phare

STATIC = os.path.join(os.path.dirname(__file__), "..", "app", "static")


def rrect(u, v, x0, y0, x1, y1, r):
    if x0 + r <= u <= x1 - r and y0 <= v <= y1:
        return True
    if x0 <= u <= x1 and y0 + r <= v <= y1 - r:
        return True
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        if (u - cx) ** 2 + (v - cy) ** 2 <= r * r:
            return True
    return False


def circ(u, v, cx, cy, rad):
    return (u - cx) ** 2 + (v - cy) ** 2 <= rad * rad


def pixel(u, v):
    col = BG
    if rrect(u, v, 0.18, 0.28, 0.82, 0.62, 0.07):
        col = BODY
    if 0.235 <= u <= 0.765 and 0.335 <= v <= 0.44:
        col = GLASS
        t = (u - 0.235) / 0.106  # 5 vitres, 6 montants
        if abs(t - round(t)) < 0.06:
            col = BODY
    if circ(u, v, 0.80, 0.55, 0.022):
        col = LIGHT
    if circ(u, v, 0.33, 0.64, 0.085) or circ(u, v, 0.67, 0.64, 0.085):
        col = WHEEL
    if circ(u, v, 0.33, 0.64, 0.038) or circ(u, v, 0.67, 0.64, 0.038):
        col = BODY
    return col


def write_png(path, n):
    raw = bytearray()
    for y in range(n):
        raw.append(0)  # filtre 0
        v = (y + 0.5) / n
        for x in range(n):
            raw += bytes(pixel((x + 0.5) / n, v))

    def chunk(typ, data):
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))  # RGB 8 bits
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    out += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(out)
    print("wrote", os.path.relpath(path), f"({n}x{n})")


if __name__ == "__main__":
    write_png(os.path.join(STATIC, "icon-192.png"), 192)
    write_png(os.path.join(STATIC, "icon-512.png"), 512)
    write_png(os.path.join(STATIC, "apple-touch-icon.png"), 180)
