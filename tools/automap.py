#!/usr/bin/env python3
"""Draw an Automap Plus map picture, and its region colours, from a seed's overworld.

Automap Plus (snarfblam; disassembled and extended in Zelda Redux) reveals a
pre-drawn 64x32-pixel picture of Hyrule, one screen at a time, as you visit.
Its picture is of the ORIGINAL overworld, so on a Zelda [reloaded] seed it
would show the wrong map. This tool redraws it from the seed's
spoilers/min/Overworld.png.

The picture is 32 NES tiles (8 across, 4 down) of 2-bit CHR data, 512 bytes.
Each of the 128 overworld screens (16 x 8) is a 4x4-pixel block, drawn the way
snarfblam drew the original: a small room. The block's top row and left column
are a wall line, open where you can walk into the next screen; the 3x3 inside
shows the screen's walls, floor and water. Shades:
    0  not drawn
    1  wall (rock, trees, gravestones) and wall lines
    2  floor
    3  water

Redux colours the map by region: each 16x16-pixel palette area of the HUD
(4 screens across) picks a palette, brown for rock, green for forest and grey
for graveyards. `regions` picks those from the seed's own terrain.

    automap.py render Overworld.png OUT.bin   draw the picture for a seed
    automap.py regions Overworld.png          print the region palette grid
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
WALL, FLOOR, WATER = 1, 2, 3              # picture shades
ROCK, TREE, GRAVE = "rock", "tree", "grave"   # terrain kinds, for regions
# HUD palettes Redux uses for the map: 3 brown, 2 green, 0 grey.
REGION_PALETTE = {ROCK: 3, TREE: 2, GRAVE: 0}


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
    """One spoiler-map pixel -> FLOOR, GRAVE (graveyard floor), TREE, ROCK or WATER.

    The spoiler palette: cream ground (two shades, the darker one is the grid),
    grey graveyard floor (two shades), brown rock, green trees, white rocks and
    gravestones, blue water, black cave mouths and stairs.
    """
    r, g, b = rgb
    if b > 120 and b > r + 40 and b > g + 40:
        return WATER
    if r > 200 and g > 190 and b < 235:   # cream ground and its grid lines
        return FLOOR
    if 100 <= r <= 150 and abs(r - g) < 12 and abs(g - b) < 12:
        return GRAVE
    if g > 90 and r < 40 and b < 40:
        return TREE                       # the two greens
    return ROCK


def tally(rows, x0, x1, y0, y1):
    counts = {FLOOR: 0, GRAVE: 0, TREE: 0, ROCK: 0, WATER: 0}
    for y in range(y0, y1):
        row = rows[y]
        for x in range(x0, x1):
            counts[classify(row[x])] += 1
    total = sum(counts.values()) or 1
    return {k: v / total for k, v in counts.items()}


def shade(t, floor=0.5):
    if t[WATER] > 0.40:
        return WATER
    return FLOOR if t[FLOOR] + t[GRAVE] > floor else WALL


def picture_from_png(path):
    """Return a 32x64 list of shades for the whole overworld."""
    width, height, rows = read_png(path)
    sw, sh = width / SCREENS_X, height / SCREENS_Y
    band = max(2, int(min(sw, sh) / 16))  # edge strip sampled for exits
    pic = [[WALL] * (SCREENS_X * CELL) for _ in range(SCREENS_Y * CELL)]
    for sy in range(SCREENS_Y):
        for sx in range(SCREENS_X):
            X0, Y0 = sx * sw, sy * sh
            # Inside: the screen in thirds.
            for cy in range(3):
                for cx in range(3):
                    t = tally(rows, int(X0 + cx * sw / 3), int(X0 + (cx + 1) * sw / 3),
                              int(Y0 + cy * sh / 3), int(Y0 + (cy + 1) * sh / 3))
                    pic[sy * CELL + 1 + cy][sx * CELL + 1 + cx] = shade(t)
            # Top wall line: open where this screen's top edge and the bottom
            # edge of the screen above are both floor (or both water).
            if sy > 0:
                for cx in range(3):
                    xa, xb = int(X0 + cx * sw / 3), int(X0 + (cx + 1) * sw / 3)
                    here = shade(tally(rows, xa, xb, int(Y0), int(Y0) + band), 0.25)
                    there = shade(tally(rows, xa, xb, int(Y0) - band, int(Y0)), 0.25)
                    if here == there and here != WALL:
                        pic[sy * CELL][sx * CELL + 1 + cx] = here
            # Left wall line, the same against the screen to the left.
            if sx > 0:
                for cy in range(3):
                    ya, yb = int(Y0 + cy * sh / 3), int(Y0 + (cy + 1) * sh / 3)
                    here = shade(tally(rows, int(X0), int(X0) + band, ya, yb), 0.25)
                    there = shade(tally(rows, int(X0) - band, int(X0), ya, yb), 0.25)
                    if here == there and here != WALL:
                        pic[sy * CELL + 1 + cy][sx * CELL] = here
    return pic


# The HUD palette areas over the map, as screen ranges. The map's 4 tile rows
# fall across three attribute rows: 1 tile, 2 tiles, 1 tile, i.e. 2, 4 and 2
# screens tall. Across, each area is 2 tiles, 4 screens.
REGION_ROWS = [(0, 2), (2, 6), (6, 8)]
REGION_COLS = [(0, 4), (4, 8), (8, 12), (12, 16)]


def regions(path):
    """Return a 3x4 grid of HUD palettes for the map, one per palette area."""
    width, height, rows = read_png(path)
    sw, sh = width / SCREENS_X, height / SCREENS_Y
    grid = []
    for y0, y1 in REGION_ROWS:
        line = []
        for x0, x1 in REGION_COLS:
            t = tally(rows, int(x0 * sw), int(x1 * sw), int(y0 * sh), int(y1 * sh))
            # Forest wins near-ties with rock: open ground between trees makes
            # forests read thinner than they look. Grey only where graveyard
            # is the area's main terrain; a corner of graveyard must not turn
            # a forest grey.
            tree, rock, grave = t[TREE] / 0.8, t[ROCK], t[GRAVE]
            kind = max((tree, TREE), (rock, ROCK), (grave, GRAVE))[1]
            line.append(REGION_PALETTE[kind])
        grid.append(line)
    return grid


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
    glyph = {0: " ", WALL: ":", FLOOR: "+", WATER: "#"}
    return "\n".join("".join(glyph[v] for v in row) for row in pic)


# ---------------------------------------------------------------------- main

def main(argv):
    if len(argv) >= 3 and argv[0] == "render":
        open(argv[2], "wb").write(encode(picture_from_png(argv[1])))
    elif len(argv) == 2 and argv[0] == "regions":
        for line in regions(argv[1]):
            print(" ".join(str(v) for v in line))
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
