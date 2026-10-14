#!/usr/bin/env python3
"""Draw a Zelda Automap Plus map image from a seed's own overworld.

Zelda Automap Plus (snarfblam) reveals a pre-drawn 64x32-pixel picture of
Hyrule, one screen at a time, as you visit. Its picture is of the ORIGINAL
overworld, so on a Zelda [reloaded] seed it would show the wrong map. This
tool redraws that picture from the seed's spoilers/min/Overworld.png.

The picture is 32 NES tiles (8 across, 4 down) of 2-bit CHR data, 512 bytes.
Each of the 128 overworld screens (16 x 8) is a 4x4-pixel block, and each
pixel is one of three shades:
    0  blocked (rock, trees, statues)
    1  walkable ground
    3  water

    automap.py render Overworld.png OUT.bin   draw the picture for a seed
    automap.py show FILE.bin                  print a picture as text
    automap.py diff A.bin B.bin               compare two pictures, pixel by pixel

Pure standard library: the PNG decoder below handles the 8-bit RGB, RGBA and
palette images the randomizer writes.
"""
import struct
import sys
import zlib

SCREENS_X, SCREENS_Y = 16, 8
CELL = 4                                  # pixels per screen, each way
BLOCKED, WALK, WATER = 0, 1, 3


# ---------------------------------------------------------------- PNG reading

def read_png(path):
    """Return (width, height, rows) where rows[y][x] is an (r, g, b) tuple."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    pos, idat, palette = 8, b"", None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if depth != 8 or interlace or ctype not in (2, 3, 6):
        raise ValueError(f"{path}: unsupported PNG (depth {depth}, type {ctype}, interlace {interlace})")
    bpp = {2: 3, 3: 1, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = width * bpp
    rows, prev = [], bytearray(stride)
    for y in range(height):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        if ctype == 3:
            rows.append([palette[v] for v in line])
        else:
            rows.append([tuple(line[i:i + 3]) for i in range(0, stride, bpp)])
    return width, height, rows


# ------------------------------------------------------------- classification

def classify(rgb):
    r, g, b = rgb
    if b > 120 and b > r + 40 and b > g + 40:
        return WATER
    if r > 200 and g > 190:               # sand/cream ground, light graveyard floor
        return WALK
    if r > 150 and g > 150 and b > 150 and abs(r - g) < 20 and abs(g - b) < 20:
        return WALK                       # pale grey paths
    return BLOCKED


def picture_from_png(path):
    """Return a 32x64 list of shades for the whole overworld."""
    width, height, rows = read_png(path)
    sw, sh = width / SCREENS_X, height / SCREENS_Y
    pic = [[BLOCKED] * (SCREENS_X * CELL) for _ in range(SCREENS_Y * CELL)]
    for sy in range(SCREENS_Y):
        for sx in range(SCREENS_X):
            for cy in range(CELL):
                for cx in range(CELL):
                    x0 = int(sx * sw + cx * sw / CELL)
                    x1 = int(sx * sw + (cx + 1) * sw / CELL)
                    y0 = int(sy * sh + cy * sh / CELL)
                    y1 = int(sy * sh + (cy + 1) * sh / CELL)
                    counts = {BLOCKED: 0, WALK: 0, WATER: 0}
                    for y in range(y0, y1, 2):        # every other pixel is plenty
                        row = rows[y]
                        for x in range(x0, x1, 2):
                            counts[classify(row[x])] += 1
                    total = sum(counts.values()) or 1
                    if counts[WATER] / total > 0.40:
                        shade = WATER
                    elif counts[WALK] / total > 0.50:
                        shade = WALK
                    else:
                        shade = BLOCKED
                    pic[sy * CELL + cy][sx * CELL + cx] = shade
    return pic


# ------------------------------------------------------------------ CHR codec

def encode(pic):
    """32x64 shades -> 512 bytes of NES 2bpp CHR, tiles row-major, 8 across."""
    out = bytearray()
    for ty in range(4):
        for tx in range(8):
            lo, hi = bytearray(8), bytearray(8)
            for y in range(8):
                for x in range(8):
                    v = pic[ty * 8 + y][tx * 8 + x]
                    lo[y] |= (v & 1) << (7 - x)
                    hi[y] |= ((v >> 1) & 1) << (7 - x)
            out += lo + hi
    return bytes(out)


def decode(data):
    pic = [[0] * 64 for _ in range(32)]
    for t in range(32):
        ty, tx = divmod(t, 8)
        for y in range(8):
            lo, hi = data[t * 16 + y], data[t * 16 + 8 + y]
            for x in range(8):
                b = 7 - x
                pic[ty * 8 + y][tx * 8 + x] = ((lo >> b) & 1) | (((hi >> b) & 1) << 1)
    return pic


def text(pic):
    glyph = {BLOCKED: ".", WALK: ":", 2: "+", WATER: "#"}
    return "\n".join("".join(glyph[v] for v in row) for row in pic)


# ---------------------------------------------------------------------- main

def main(argv):
    if len(argv) >= 3 and argv[0] == "render":
        open(argv[2], "wb").write(encode(picture_from_png(argv[1])))
    elif len(argv) == 2 and argv[0] == "show":
        print(text(decode(open(argv[1], "rb").read())))
    elif len(argv) == 3 and argv[0] == "diff":
        a = decode(open(argv[1], "rb").read())
        b = decode(open(argv[2], "rb").read())
        same = sum(a[y][x] == b[y][x] for y in range(32) for x in range(64))
        print(f"{same}/2048 pixels match ({100 * same / 2048:.1f}%)")
        for y in range(32):
            print("".join(("." if a[y][x] == b[y][x] else "x") for x in range(64)))
    else:
        print(__doc__.strip().split("\n\n")[-2], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
