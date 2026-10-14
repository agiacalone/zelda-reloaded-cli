#!/usr/bin/env python3
"""Zelda Remuxed: assemble Zelda Redux features onto a Zelda [reloaded] seed.

    remux.py --redux DIR --asar BIN [--feature NAME ...] ORIGINAL.nes SEED_DIR OUT.nes

DIR is a checkout of The Legend of Zelda Redux source (GPL-3, ShadowOne333).
BIN is Asar 2 built from source. ORIGINAL is the unmodified Legend of Zelda
(USA) ROM; SEED_DIR is a seed folder as zelda-rando writes it (the .nes and
spoilers/min/Overworld.png).

Redux is written against the original ROM. Reloaded rebuilds the world, moves
the fixed bank from 7 to 15, and uses some of the space and RAM Redux expects
to be free. Each feature therefore gets a list of source edits (FEATURES below)
that move it out of Reloaded's way, and a small amount of Reloaded-specific
glue (GLUE). Asar then repoints every jump to the moved code.

Nothing is trusted blindly. After assembling, every byte that changed must be
one of: free space in the seed (0xFF), a byte Reloaded left as in the original
game (a hook Redux expects to patch), or a glue write listed in GLUE_SITES with
the seed byte it expects to replace. Anything else stops the build.
"""
import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "tools"))
import automap  # noqa: E402

HDR, BANK = 16, 0x4000


class RemuxError(Exception):
    pass


# ----------------------------------------------------------------- features

def automap_edits(work, seed_dir):
    """Redux's Automap Plus (snarfblam's patch, disassembled by ShadowOne333)."""
    picture = work / "map.bin"
    picture.write_bytes(automap.encode(automap.picture_from_png(seed_dir / "spoilers/min/Overworld.png")))
    grid = automap.regions(seed_dir / "spoilers/min/Overworld.png")
    return [
        # The map picture: Reloaded uses bank 5 $AD00. Draw the seed's own.
        (r"%org\(\$AD00,5\)", "%org($B900,5)"),
        (r"(!MapTiles\s*=\s*)\$AD00", r"\g<1>$B900"),
        (r'incbin "code/gameplay/automap_tiles.bin"', f'incbin "{picture}"'),
        # Two blocks in space Reloaded uses.
        (r"%org\(\$AF20,5\)", "%org($BB00,5)"),
        (r"%org\(\$B000,2\)", "%org($B800,2)"),
        # RAM: Reloaded copies code into $7F10-$7F25 at power-on.
        (r"(!SecondPpuStringIndex\s*=\s*)\$7F10", r"\g<1>$7F30"),
        (r"(!MapBlipY\s*=\s*)\$7F29", r"\g<1>$7F49"),
        # Fixed bank: Reloaded leaves 14 bytes at $FF42 and 16 at $FFDB.
        # SafeBlipUpdate (16 bytes) moves whole; DoWholeMapHijack splits into
        # a check in bank 6 and a 13-byte bank-swap stub.
        (r"%org\(\$FFD6,7\)", "%org($FFDB,7)"),
        (r"%org\(\$FFC0,7\)\s*;[^\n]*\nDoWholeMapHijack:.*?\nExit:[^\n]*\n; Displaced code\n\tinc \$11[^\n]*\n\trts",
         "%org($B000,6)\n"
         "DoWholeMapHijack:\n"
         "\tlda !LevelNumber\n"
         "\tbne Exit\n"
         "\tjsr WholeMapStub\n"
         "Exit:\n"
         "\tinc $11\n"
         "\trts\n"
         "%org($FF42,7)\n"
         "WholeMapStub:\n"
         "\tlda #$05\n"
         "\tjsr !BankSwap\n"
         "\tjsr DrawWholeMap\n"
         "\tlda #$06\n"
         "\tjmp !BankSwap"),
        # Fast life fill: Reloaded's own FastFill rewrote this code. Drop it.
        (r"%org\(\$B1F2,5\).*?\n\tinc \$066F[^\n]*\n\trts\n", ""),
        # The picture's address is also built from an immediate.
        (r"\tadc #\$AD(\s)", r"\tadc #$B9\1"),
        # Redux draws the map into the four tile banks its overworld animation
        # uses. Reloaded has one 8 KB tile RAM: draw once, never switch banks.
        (r"jmp DrawMapAllBanks", "jmp DoDrawWholeMap"),
        (r"\tjsr SetChrBank_6 ?\n", "\t; (no tile-bank switch on Reloaded)\n"),
        (r"(ClearAndReturn:[^\n]*\n)\tlda !disable_animation", r"\1\tlda #$01\t; animation is always off on Reloaded"),
        # HUD icons: Redux's column is rupee, key, arrow, bomb, which needs
        # the arrow counter. Keep the original column until that is ported.
        (r"db \$20,\$6B,\$84,!RUPEE,!KEY,!ARROW,!BOMB,\$FF", "db $20,$6B,$84,!RUPEE,$24,!KEY,!BOMB,$FF"),
        # Region colours, from the seed's terrain.
        (r"\tdb \$C0,\$FF,\$70,\$00,\$00,\$44,\$55,\$55[^\n]*\n\tdb \$C0,\$AF,\$36,\$00,\$00,\$44,\$55,\$55[^\n]*\n",
         attribute_rows(grid)),
    ]


def attribute_rows(grid):
    """The HUD attribute bytes $23C0-$23CF with the map's palette areas set.

    The original-layout map sits at tile columns 2-9, rows 3-6. An attribute
    byte covers 4x4 tiles in 2x2 quadrants (TL, TR, BL, BR = bits 0-1, 2-3,
    4-5, 6-7)."""
    base = [0xC0, 0xFF, 0x70, 0x00, 0x00, 0x44, 0x55, 0x55,
            0xC0, 0xAF, 0x36, 0x00, 0x00, 0x44, 0x55, 0x55]
    rowband = {3: 0, 4: 1, 5: 1, 6: 2}
    for trow in (3, 4, 5, 6):
        for tcol in range(2, 10):
            pal = grid[rowband[trow]][(tcol - 2) // 2]
            i = (trow // 4) * 8 + tcol // 4
            shift = ((trow % 4) // 2) * 4 + ((tcol % 4) // 2) * 2
            base[i] = (base[i] & ~(3 << shift)) | (pal << shift)
    line = lambda b: "\tdb " + ",".join(f"${v:02X}" for v in b) + "\t; set by remux.py from the seed's terrain\n"
    return line(base[:8]) + line(base[8:])


def automap_extra(work, redux):
    """Redux's quarter-heart tiles $50-$53. Redux ships them inside its whole
    bank-2 graphics; copy just those four tiles, so Reloaded's own font and
    hero graphics stay."""
    blob = (pathlib.Path(redux) / "code/gfx/data_01b.bin").read_bytes()   # starts at bank 2 $877F
    (work / "hearts.bin").write_bytes(blob[0x500:0x540])
    return '%org($8C7F,2)\n\tincbin "hearts.bin"\n'


FEATURES = {
    "automap": ("code/gameplay/automap.asm", automap_edits, automap_extra),
}

# --------------------------------------------------------------------- glue

# Persistence. At every power-on and game start the game copies bank 1
# $A500-$BF6F into RAM $6C90-$7FFF. On a Reloaded seed that copy runs to the
# end of RAM and erases the saved maps at $7F60-$7F8F. Stop it at $7F50; a
# stub writes the one byte Reloaded keeps beyond that ($7FFF = $A5), then
# runs the shortened copy.
GLUE = """
%org($8CF0,1)
RemuxCopyStub:
\tlda #$A5
\tsta $7FFF
\tjmp $8D00
%org($8D31,1)
\tdb $7F
%org($8D37,1)
\tdb $50
%org($E902,7)
\tdw RemuxCopyStub
%org($E997,7)
\tdw RemuxCopyStub
"""
# Glue writes into Reloaded's own code: (bank, address, seed byte expected).
GLUE_SITES = [(1, 0x8D31, 0x80), (1, 0x8D37, 0x00), (15, 0xE902, 0x00), (15, 0xE903, 0x8D),
              (15, 0xE997, 0x00), (15, 0xE998, 0x8D)]

# ------------------------------------------------------------------ helpers


def file_off(bank, addr):
    return HDR + bank * BANK + (addr - (0xC000 if bank in (7, 15) else 0x8000))


def where(off):
    bank = (off - HDR) // BANK
    base = 0xC000 if bank in (7, 15) else 0x8000
    return f"bank {bank} ${base + (off - HDR) % BANK:04X}"


def original_equiv(off):
    """File offset in the original ROM of a seed byte, or None for new banks."""
    bank = (off - HDR) // BANK
    if bank == 15:
        return off - 8 * BANK
    return off if bank < 7 else None


def edit(text, edits, name):
    for pattern, repl in edits:
        text, n = re.subn(pattern, repl, text, count=1, flags=re.S)
        if n != 1:
            raise RemuxError(f"{name}: source edit did not match: {pattern[:60]}")
    return text


def mirror_tiles(out, seed):
    """Copy tile-graphics writes in bank 2 into Reloaded's extra tile copies.

    Reloaded keeps further copies of the original bank 2 tile set in banks 8
    and up and loads tiles from those, so a tile written only to bank 2 never
    reaches the screen. Each copy is located by an anchor: the 256 bytes of
    tiles $60-$6F (bank 2 $8D7F), which are distinctive. A run written in bank
    2 is copied to the same distance from each anchor, if the copy still holds
    the bytes the seed had there."""
    anchor = file_off(2, 0x8D7F)
    key = bytes(seed[anchor:anchor + 0x100])
    copies = [k for k in range(file_off(8, 0x8000), len(seed) - 0x100) if seed[k:k + 0x100] == key]
    lo, hi = file_off(2, 0x8000), file_off(3, 0x8000)
    runs, i = [], lo
    while i < hi:
        if out[i] != seed[i]:
            j = i
            while j < hi and out[j] != seed[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    mirrored = 0
    for k in copies:
        for a, b in runs:
            t = k + (a - anchor)
            if file_off(8, 0x8000) <= t and bytes(seed[t:t + b - a]) == bytes(seed[a:b]):
                out[t:t + b - a] = out[a:b]
                mirrored += 1
    return len(copies), mirrored


# --------------------------------------------------------------------- main

def remux(redux, asar, features, original_path, seed_dir, out_path):
    seed_dir = pathlib.Path(seed_dir)
    roms = list(seed_dir.glob("*.nes"))
    if len(roms) != 1:
        raise RemuxError(f"{seed_dir}: expected one .nes")
    seed = bytearray(roms[0].read_bytes())
    original = pathlib.Path(original_path).read_bytes()
    if len(seed) != HDR + 16 * BANK:
        raise RemuxError("seed must be a 256 KB Zelda [reloaded] ROM")

    with tempfile.TemporaryDirectory(prefix="remux-") as tmp:
        work = pathlib.Path(tmp)
        shutil.copytree(pathlib.Path(redux) / "code", work / "code")
        macros = (work / "code/macros.asm").read_text()
        # Reloaded's fixed bank is bank 15: send every bank-7 org there.
        macros = edit(macros, [
            (r"org <address>-\$C000\+\$4000\*<bank>\+!headersize", "org <address>-$C000+$4000*15+!headersize"),
            (r"pad <address>-\$C000\+\$4000\*<bank>\+!headersize", "pad <address>-$C000+$4000*15+!headersize"),
        ], "macros.asm")
        (work / "code/macros.asm").write_text(macros)
        includes = []
        for name in features:
            path, make_edits, make_extra = FEATURES[name]
            src = (work / path).read_text()
            (work / path).write_text(edit(src, make_edits(work, seed_dir), name))
            includes.append(f"incsrc {path}")
            (work / f"{name}-extra.asm").write_text(make_extra(work, redux))
            includes.append(f"incsrc {name}-extra.asm")
        (work / "glue.asm").write_text(GLUE)
        (work / "main.asm").write_text("\n".join([
            "norom", "!headersize = $10", "optimize dp always", "dpbase 0",
            'incsrc "code/macros.asm"', *includes, "incsrc glue.asm", ""]))
        target = work / "out.nes"
        target.write_bytes(seed)
        r = subprocess.run([asar, "--no-title-check", "--fix-checksum=off", "main.asm", str(target)],
                           cwd=work, capture_output=True, text=True)
        if r.returncode:
            raise RemuxError("asar failed:\n" + (r.stdout + r.stderr).strip())
        out = bytearray(target.read_bytes())

    if len(out) != len(seed):
        raise RemuxError("assembly changed the ROM size")
    glue = {file_off(b, a): v for b, a, v in GLUE_SITES}
    bad = []
    for i in range(HDR, len(seed)):
        if out[i] == seed[i]:
            continue
        if seed[i] == 0xFF:
            continue                                   # free space
        if i in glue:
            if seed[i] != glue[i]:
                bad.append(f"{where(i)}: glue expected {glue[i]:02X}, seed has {seed[i]:02X}")
            continue
        oe = original_equiv(i)
        if oe is not None and seed[i] == original[oe]:
            continue                                   # untouched by Reloaded
        bad.append(f"{where(i)}: seed byte {seed[i]:02X} is Reloaded's, not free or original")
    if bad:
        raise RemuxError(f"{len(bad)} unsafe writes, first:\n  " + "\n  ".join(bad[:12]))
    copies, n = mirror_tiles(out, seed)
    pathlib.Path(out_path).write_bytes(out)
    changed = sum(a != b for a, b in zip(out, seed))
    print(f"remux: {', '.join(features)}: {changed} bytes written, "
          f"{n} tile runs mirrored into {copies} tile copies -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--redux", required=True)
    ap.add_argument("--asar", required=True)
    ap.add_argument("--feature", action="append", choices=sorted(FEATURES), default=None)
    ap.add_argument("original")
    ap.add_argument("seed_dir")
    ap.add_argument("out")
    a = ap.parse_args()
    try:
        remux(a.redux, a.asar, a.feature or ["automap"], a.original, a.seed_dir, a.out)
    except RemuxError as e:
        print(f"remux: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
