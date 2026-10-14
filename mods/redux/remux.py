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

def automap_edits(work, seed_dir, features):
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
        (r"(!LOW_X\s*=\s*)\$62", r"\g<1>$21"),	# see hud_subscreen_edits
        # The picture's address is also built from an immediate.
        (r"\tadc #\$AD(\s)", r"\tadc #$B9\1"),
        # Redux draws the map into the four tile banks its overworld animation
        # uses. Reloaded has one 8 KB tile RAM: draw once, never switch banks.
        (r"jmp DrawMapAllBanks", "jmp DoDrawWholeMap"),
        (r"\tjsr SetChrBank_6 ?\n", "\t; (no tile-bank switch on Reloaded)\n"),
        (r"(ClearAndReturn:[^\n]*\n)\tlda !disable_animation", r"\1\tlda #$01\t; animation is always off on Reloaded"),
        # Region colours, from the seed's terrain (original layout: map at
        # tile columns 2-9). hud-layout sets them again for its layout.
        (r"\tdb \$C0,\$FF,\$70,\$00,\$00,\$44,\$55,\$55[^\n]*\n\tdb \$C0,\$AF,\$36,\$00,\$00,\$44,\$55,\$55[^\n]*\n",
         attribute_rows(grid, [0xC0, 0xFF, 0x70, 0x00, 0x00, 0x44, 0x55, 0x55,
                               0xC0, 0xAF, 0x36, 0x00, 0x00, 0x44, 0x55, 0x55], 2)),
    ] + ([] if "arrows" in features else [
        # HUD icons: Redux's column is rupee, key, arrow, bomb, which needs
        # the arrow counter. Without it, keep the original column.
        (r"db \$20,\$6B,\$84,!RUPEE,!KEY,!ARROW,!BOMB,\$FF", "db $20,$6B,$84,!RUPEE,$24,!KEY,!BOMB,$FF"),
    ])


def attribute_rows(grid, base, col0):
    """The HUD attribute bytes $23C0-$23CF with the map's palette areas set.

    The map is 8 tiles wide from tile column col0, on rows 3-6. An attribute
    byte covers 4x4 tiles in 2x2 quadrants (TL, TR, BL, BR = bits 0-1, 2-3,
    4-5, 6-7)."""
    base = list(base)
    rowband = {3: 0, 4: 1, 5: 1, 6: 2}
    for trow in (3, 4, 5, 6):
        for tcol in range(col0, col0 + 8):
            pal = grid[rowband[trow]][(tcol - col0) // 2]
            i = (trow // 4) * 8 + tcol // 4
            shift = ((trow % 4) // 2) * 4 + ((tcol % 4) // 2) * 2
            base[i] = (base[i] & ~(3 << shift)) | (pal << shift)
    line = lambda b: "\tdb " + ",".join(f"${v:02X}" for v in b) + "\t; set by remux.py from the seed's terrain\n"
    return line(base[:8]) + line(base[8:])


def hud_layout_edits(work, seed_dir, features):
    """Redux's HUD layout: life on the left, map on the right."""
    grid = automap.regions(seed_dir / "spoilers/min/Overworld.png")
    return [
        # The status-bar template: Reloaded uses bank 5 $AC70.
        (r"%org\(\$AC70,5\)", "%org($AE10,5)"),
        # Dungeon HUD attributes: Redux puts them at bank 6 $A2CD, over the
        # end of the game-over menu ("RETRY"), which its caution-screen
        # feature moves first. That feature is not ported; use free space.
        (r"%org\(\$A2CD,6\)", "%org($B100,6)"),
        # Redux's dot offsets and mini-maps are for the original dungeons.
        # Reloaded builds its own; transform_hud_layout shifts those instead.
        (r"\n; DUNGEONS \\\\.*?(?=\n;\*+\n;\tChange \"LEVEL-0\")", "\n"),
        (r"(!LOW_X\s*=\s*)\$62", r"\g<1>$21"),	# see hud_subscreen_edits
        # Redux renames "LEVEL-7" to "DUNGEON-7" and moves the digit to fit,
        # but the digit then lands past the end of Reloaded's caption. Keep
        # "LEVEL-7"; just move it above the map, as Redux does (PPU $2042 ->
        # $2056). The digit is part of the same transfer, so it moves too.
        (r"; Move Dungeon numeral two tiles to the right.*?\tdb \"DUNGEON-\"[^\n]*\n",
         "%org($9D05,6)\n\tdb $56\t; LEVEL-x caption: $2042 -> $2056\n"),
        # Region colours for the map at tile columns 22-29.
        (r"\tdb \$44,\$55,\$55,\$00,\$00,\$C0,\$FF,\$70[^\n]*\n\tdb \$44,\$55,\$05,\$00,\$00,\$C0,\$AF,\$3A[^\n]*\n",
         attribute_rows(grid, [0x44, 0x55, 0x55, 0x00, 0x00, 0xC0, 0xFF, 0x70,
                               0x44, 0x55, 0x05, 0x00, 0x00, 0xC0, 0xAF, 0x3A], 22)),
    ]


def arrows_edits(work, seed_dir, features):
    """Redux's arrow counter. Its arrow-drop routine runs from RAM; move it to
    the RAM routine area (ROM $9EC4, run at $7FA0) and point the hook there."""
    return [
        (r"\tjmp \$7EE1", "\tjmp $7FA0"),
        (r"%org\(\$B751,1\)[^\n]*\n", "org $9EC4-$8000+$4000+!headersize\nbase $7FA0\t; RAM routine area\n"),
    ]


def hud_subscreen_edits(work, seed_dir, features):
    """Redux's HUD and subscreen tweaks."""
    return [
        # Link's Level 3 palette: Reloaded picks its own dungeon palettes.
        (r"%org\(\$9607,6\)[^\n]*\n\tdb \$0F,\$29,\$27,\$17[^\n]*\n", ""),
        # Redux's small "x" is tile $62, which Reloaded's "LEVEL-" caption
        # uses as its dash. Keep the original "X" (tile $21) for counters.
        (r"\tlda #\$62\t; Originally A9 21[^\n]*Rupee icon[^\n]*\n", "\tlda #$21\n"),
        (r"\tlda #\$62\t; Originally A9 21[^\n]*Key counter[^\n]*\n", "\tlda #$21\n"),
        (r"\tldy #\$62\t; Originally A0 21[^\n]*\n", "\tldy #$21\n"),
        # "TRIFORCE OF WISDOM": Reloaded draws the caption its own way, so
        # moving "TRIFORCE" never takes effect and "OF WISDOM" lands on it.
        (r"; Change \"TRIFORCE\" for \"TRIFORCE OF WISDOM\".*?\tdw triforce_outline\n", ""),
    ]


def hud_extra(work, redux):
    """The status-bar tiles Redux's HUD draws with: bomb, infinity, arrow and
    empty heart ($61, $63-$66), full heart, rupee and key ($F2, $F7, $F9).
    Not its small "x" ($62): Reloaded uses that tile as a dash. Copied from Redux's graphics one tile at a time, so Reloaded's
    own font and hero graphics stay."""
    gfx = pathlib.Path(redux) / "code/gfx"
    b = (gfx / "data_01b.bin").read_bytes()    # bank 2 from $877F; tile $50 at +$500
    c = (gfx / "data_01c.bin").read_bytes()    # bank 2 from $8E7F; tile $F2 at +0
    asm = []
    for t in [0x61, 0x63, 0x64, 0x65, 0x66]:
        (work / f"tile{t:02X}.bin").write_bytes(b[0x500 + (t - 0x50) * 16:0x500 + (t - 0x4F) * 16])
        asm.append(f'%org(${0x8C7F + (t - 0x50) * 16:04X},2)\n\tincbin "tile{t:02X}.bin"')
    # The subscreen says "SAVE: UP+A". Reloaded's own save check (bank 5
    # $AD1F) takes Up+A on controller 2 or Up+Select+A on controller 1; make
    # controller 1's plain Up+A, as in Redux.
    asm.append("%org($AD2A,5)\n\tdb $88\n%org($AD2C,5)\n\tdb $88")
    for t in (0xF2, 0xF7, 0xF9):
        (work / f"tile{t:02X}.bin").write_bytes(c[(t - 0xF2) * 16:(t - 0xF1) * 16])
        asm.append(f'%org(${0x8E7F + (t - 0xF2) * 16:04X},2)\n\tincbin "tile{t:02X}.bin"')
    return "\n".join(asm) + "\n"


def rupee_edits(work, seed_dir, features):
    """The 999-rupee counter reads the status-bar template; follow it to $AE10."""
    return [
        (r"%org\(\$AC70,5\)", "%org($AE10,5)"),
        (r"lda \$AC70,y", "lda $AE10,y"),
        (r"(!LOW_X\s*=\s*)\$62", r"\g<1>$21"),	# see hud_subscreen_edits
        (r"\tlda #\$62", "\tlda #$21"),
    ]


# Dungeon map tables in bank 6: per level, the X offset of the map dot, then
# $21 bytes later the PPU macro list that draws the level's HUD mini-map.
DUNGEON_DOTS = [0x942A + n * 0xFC for n in range(9)] + \
               [0x8174, 0x81AD, 0x81E4, 0x8221, 0x825A, 0x829D, 0x82DD, 0x831C, 0x835F]


def transform_hud_layout(out, seed):
    """Move each of the seed's own dungeon mini-maps 20 tiles right, as Redux
    does for the original dungeons: +$14 on each PPU address, +$A0 on the dot.
    Every list is parsed and checked before anything changes."""
    changed = 0
    for dot in DUNGEON_DOTS:
        d = file_off(6, dot)
        out[d] = (seed[d] + 0xA0) & 0xFF
        o = d + 0x21
        for _ in range(16):
            if seed[o] == 0xFF:
                break
            hi, lo, ctl = seed[o], seed[o + 1], seed[o + 2]
            n = ctl & 0x3F or 64
            size = 1 if ctl & 0x40 else n
            col = lo & 0x1F
            span = 1 if ctl & 0x80 else n
            if hi != 0x20 or not 0x40 <= lo < 0xE0 or col + 0x14 + span > 32:
                raise RemuxError(f"dungeon mini-map at {where(o)} is not the expected format")
            out[o + 1] = lo + 0x14
            o += 3 + size
            changed += 1
        else:
            raise RemuxError(f"dungeon mini-map at {where(d + 0x21)} has no terminator")
    return changed


def automap_extra(work, redux):
    """Redux's quarter-heart tiles $50-$53. Redux ships them inside its whole
    bank-2 graphics; copy just those four tiles, so Reloaded's own font and
    hero graphics stay."""
    blob = (pathlib.Path(redux) / "code/gfx/data_01b.bin").read_bytes()   # starts at bank 2 $877F
    (work / "hearts.bin").write_bytes(blob[0x500:0x540])
    return '%org($8C7F,2)\n\tincbin "hearts.bin"\n'


def no_edits(work, seed_dir, features):
    return []


def no_extra(work, redux):
    return ""


FEATURES = {
    "automap": ("code/gameplay/automap.asm", automap_edits, automap_extra),
    "dungeon-automap": ("code/gameplay/dungeon_automap.asm", no_edits, no_extra),
    # Redux's HUD: these four go together and in this order (move_maps.asm
    # rewrites code from the other three and from the automap).
    "hud-subscreen": ("code/menus/hud_and_subscreen.asm", hud_subscreen_edits, hud_extra),
    "arrows": ("code/gameplay/arrows.asm", arrows_edits, no_extra),
    "rupees": ("code/gameplay/rupee.asm", rupee_edits, no_extra),
    "hud-layout": ("code/gameplay/move_maps.asm", hud_layout_edits, no_extra),
    # Features that touch nothing Reloaded changed.
    "save-hearts": ("code/menus/save_hearts.asm", no_edits, no_extra),
    "fix-bait": ("code/bugfixes/bait_keep_fix.asm", no_edits, no_extra),
    "fix-candle": ("code/bugfixes/candle_flame_invulnerable.asm", no_edits, no_extra),
    "fix-cave-timer": ("code/bugfixes/cave_room_timer.asm", no_edits, no_extra),
    "fix-level1-door": ("code/bugfixes/dungeon_front_room.asm", no_edits, no_extra),
    "fix-keyhole": ("code/bugfixes/khananakey_fix.asm", no_edits, no_extra),
    "fix-beam": ("code/bugfixes/magic_beam_align.asm", no_edits, no_extra),
    "fix-leave-cave": ("code/bugfixes/overworld_leave_cave.asm", no_edits, no_extra),
    "fix-scroll": ("code/bugfixes/overworld_scroll_timing.asm", no_edits, no_extra),
    "sword-draw": ("code/gameplay/sword_draw.asm", no_edits, no_extra),
    "sword-swing": ("code/gameplay/sword_swing.asm", no_edits, no_extra),
}
# On hold: they build safely but break name registration on a Reloaded seed.
#   copy-erase  (code/menus/menu_tweaks.asm): the name is never saved; Redux's
#               file screen clashes with Reloaded's save handling.
#   item-toggle (code/gameplay/item_toggle.asm): its routine at bank 2 $B7A8
#               assumes bank 2 is mapped; registration never finishes.
# On hold: builds safely and passes FCEUX tests, but dungeon music plays wrong
# on hardware (heard on the Steam Deck, 2026-10-14).
#   dungeon-music (code/music/dungeon_music.asm): hooks the music sequencer in
#               bank 0 and picks songs by the level number at $10.


def redux_order(redux, features):
    """Sort features into the order Redux's code/main.asm includes them; some
    files patch code that earlier ones wrote."""
    main = (pathlib.Path(redux) / "code/main.asm").read_text()
    pos = {name: main.find(path.split("/", 1)[1]) for name, (path, _, _) in FEATURES.items()}
    missing = [f for f in features if pos[f] < 0]
    if missing:
        raise RemuxError(f"not in Redux's main.asm (renamed upstream?): {', '.join(missing)}")
    return sorted(features, key=lambda f: pos[f])

# --------------------------------------------------------------------- glue

# Persistence. At every power-on and game start the game copies bank 1
# $A500-$BF6F into RAM $6C90-$7FFF. On a Reloaded seed that copy runs to the
# end of RAM and erases the saved maps at $7F60-$7F8F. Stop it at $7F50; a
# stub writes the one byte Reloaded keeps beyond that ($7FFF = $A5), copies
# the RAM routines (below), then runs the shortened copy.
GLUE = """
%org($8CB0,1)
RemuxCopyStub:
\tldx #$1F\t; RAM routines: ROM bank 1 $9EC4-$9EE3 -> RAM $7FA0-$7FBF
-\tlda $9EC4,x
\tsta $7FA0,x
\tdex
\tbpl -
{extra}\tlda #$A5
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
# RAM routines. Redux places small routines in the part of bank 1 the game
# copies to RAM; Reloaded fills that part, and the mirrored seeds leave no gap
# big enough. The stub above therefore also copies 32 bytes from free ROM
# (bank 1 $9EC4) to RAM $7FA0-$7FBF, which nothing else uses: features that
# need a RAM routine assemble it there (see arrows_edits).
# Glue writes into Reloaded's own code: (bank, address, seed byte expected).
GLUE_SITES = [(1, 0x8D31, 0x80), (1, 0x8D37, 0x00), (15, 0xE902, 0x00), (15, 0xE903, 0x8D),
              (15, 0xE997, 0x00), (15, 0xE998, 0x8D),
              # hud-subscreen: Reloaded's save check, and #$A8 -> and #$88 (Up+A)
              (5, 0xAD2A, 0xA8), (5, 0xAD2C, 0xA8)]

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


def group(bad):
    """Collapse unsafe writes into address ranges, for a readable report."""
    out, run = [], None
    for off, why in bad:
        if run and off <= run[1] + 4 and why == run[2]:
            run[1] = off
        else:
            if run:
                out.append(run)
            run = [off, off, why]
    if run:
        out.append(run)
    return [f"{where(a)}-${(int(where(b)[-4:], 16)):04X} ({b - a + 1} bytes): {why}" for a, b, why in out]


def edit(text, edits, name):
    for pattern, repl in edits:
        text, n = re.subn(pattern, repl, text, count=1, flags=re.S)
        if n != 1:
            raise RemuxError(f"{name}: source edit did not match: {pattern[:60]}")
    return text


# Tile blocks in bank 2 that Reloaded copies into banks 8 and up, each with an
# anchor: distinctive bytes that locate the block in every copy. The blocks are
# not the same distance apart in the copies, so each needs its own anchor.
TILE_BLOCKS = [
    # (block start, block end, anchor address, anchor length)
    (0x8C7F, 0x8E7F, 0x8D7F, 0x100),   # tiles $50-$6F; anchor tiles $60-$6F
    (0x8E7F, 0x8F7F, 0x8E7F, 0x20),    # tiles $F2-$FF; anchor tiles $F2-$F3
]


def mirror_tiles(out, seed):
    """Copy tile-graphics writes in bank 2 into Reloaded's extra tile copies.

    Reloaded keeps further copies of the original bank 2 tile sets in banks 8
    and up and loads tiles from those, so a tile written only to bank 2 never
    reaches the screen. A run is copied to the same distance from its block's
    anchor in each copy, if the copy still holds the bytes the seed had there.
    A tile write outside the known blocks stops the build."""
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
    copies = mirrored = 0
    for start, end, anchor, alen in TILE_BLOCKS:
        s0, e0, a0 = file_off(2, start), file_off(2, end), file_off(2, anchor)
        key = bytes(seed[a0:a0 + alen])
        hits = [k for k in range(file_off(8, 0x8000), len(seed) - alen) if seed[k:k + alen] == key]
        copies = max(copies, len(hits))
        for a, b in runs:
            if not s0 <= a < e0:
                continue
            for k in hits:
                t = k + (a - a0)
                if bytes(seed[t:t + b - a]) == bytes(seed[a:b]):
                    out[t:t + b - a] = out[a:b]
                    mirrored += 1
    stray = [where(a) for a, b in runs
             if not any(file_off(2, s0) <= a < file_off(2, e0) for s0, e0, _, _ in TILE_BLOCKS)]
    # Only tile writes are mirrored; other bank 2 writes (code, data) are fine.
    return copies, mirrored


# ----------------------------------------------------------------- graphics

# Redux ships its graphics as whole blocks (code/gfx/graphics.asm). Reloaded
# keeps many of the original blocks, some moved or copied several times, and
# its graphics packs redraw others. Groups of blocks, by what they draw:
GFX_GROUPS = {
    "graphics": ["data_00a.bin", "data_00b.bin",          # intro, title screen
                 "data_01b.bin", "data_01c.bin",          # font, hearts, rupee, key
                 "data_02a.bin",                          # dungeon walls and floors
                 "data_03f.bin", "data_03g.bin", "data_03h.bin"],   # bosses, Ganon, Zelda
    "graphics-overworld": ["data_02b.bin"],               # overworld tiles
}
# Tiles Redux redraws that Reloaded uses for something else: (block, tile offset).
GFX_EXCLUDE = {
    ("data_01b.bin", 0x590),   # tile $59: Redux lettering; blank in Reloaded
    ("data_01b.bin", 0x620),   # tile $62: Redux's small "x"; Reloaded's dash
}


def gfx_blocks(redux):
    """(block name, original file offset, size) in graphics.asm order."""
    src = (pathlib.Path(redux) / "code/gfx/graphics.asm").read_text()
    out, cur = [], None
    for line in src.splitlines():
        m = re.match(r"\s*%org\(\$([0-9A-F]+),(\d+)\)", line)
        if m:
            cur = file_off(int(m.group(2)), int(m.group(1), 16))
            continue
        m = re.match(r'\s*incbin "([^"]+)"', line)
        if m and cur is not None:
            n = (pathlib.Path(redux) / m.group(1)).stat().st_size
            out.append((m.group(1).split("/")[-1], cur, n))
            cur += n
    return out


def apply_graphics(out, seed, original, redux, groups):
    """Write Redux's redrawn tiles wherever the seed still has the original.

    Each block is located in the seed by 64-byte windows of its original bytes;
    a location counts only if at least half its tiles still match. At each
    location a tile is written only if the seed still has the original tile
    there, so a graphics pack's own tiles always win."""
    wanted = {b for g in groups for b in GFX_GROUPS[g]}
    gfx = pathlib.Path(redux) / "code/gfx"
    report = []
    for name, off, n in gfx_blocks(redux):
        if name not in wanted:
            continue
        new = (gfx / name).read_bytes()
        orig = original[off:off + n]
        tiles = range(0, n - 15, 16)
        changed = [t for t in tiles if new[t:t + 16] != orig[t:t + 16] and (name, t) not in GFX_EXCLUDE]
        places = set()
        for k in range(0, max(1, n - 64), 256):
            w, i = orig[k:k + 64], seed.find(orig[k:k + 64])
            while i >= 0:
                places.add(i - k)
                i = seed.find(w, i + 1)
        good = [a for a in sorted(places) if 0 <= a and a + n <= len(seed)
                and sum(seed[a + t:a + t + 16] == orig[t:t + 16] for t in tiles) >= len(tiles) / 2]
        written = 0
        for a in good:
            for t in changed:
                if seed[a + t:a + t + 16] == orig[t:t + 16]:
                    out[a + t:a + t + 16] = new[t:t + 16]
                    written += 1
        report.append(f"{name}: {len(good)} location(s), {written} tiles")
    return report


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

    gfx_only = [f for f in features if f in GFX_GROUPS]
    features = redux_order(redux, [f for f in features if f not in GFX_GROUPS]) + gfx_only
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
        for name in [f for f in features if f in FEATURES]:
            path, make_edits, make_extra = FEATURES[name]
            src = (work / path).read_text()
            (work / path).write_text(edit(src, make_edits(work, seed_dir, features), name))
            includes.append(f"incsrc {path}")
            (work / f"{name}-extra.asm").write_text(make_extra(work, redux))
            includes.append(f"incsrc {name}-extra.asm")
        extra = ""
        if "hud-layout" in features:
            # The dungeon caption ("LEVEL-7") is a screen write kept in
            # battery RAM at $681C, filled from ROM only when a save file is
            # first created. Re-point it at every power-on, so files made
            # before the HUD layout get the new position too.
            extra = "\tlda #$56\t; dungeon caption: PPU $2042 -> $2056\n\tsta $681D\n"
        (work / "glue.asm").write_text(GLUE.replace("{extra}", extra))
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
    bad = []          # (offset, reason)
    for i in range(HDR, len(seed)):
        if out[i] == seed[i]:
            continue
        if seed[i] == 0xFF:
            continue                                   # free space
        if i in glue:
            if seed[i] != glue[i]:
                bad.append((i, f"glue expected {glue[i]:02X}, seed has {seed[i]:02X}"))
            continue
        oe = original_equiv(i)
        if oe is not None and seed[i] == original[oe]:
            continue                                   # untouched by Reloaded
        bad.append((i, "Reloaded's bytes"))
    if bad:
        raise RemuxError(f"{len(bad)} unsafe writes:\n  " + "\n  ".join(group(bad)))
    if "hud-layout" in features:
        transform_hud_layout(out, seed)
    gfx = [g for g in features if g in GFX_GROUPS]
    for line in apply_graphics(out, seed, original, redux, gfx) if gfx else []:
        print(f"  {line}")
    copies, n = mirror_tiles(out, seed)        # after graphics: copies its bank 2 tiles too
    pathlib.Path(out_path).write_bytes(out)
    changed = sum(a != b for a, b in zip(out, seed))
    print(f"remux: {', '.join(features)}: {changed} bytes written, "
          f"{n} tile runs mirrored into {copies} tile copies -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--redux", required=True)
    ap.add_argument("--asar", required=True)
    ap.add_argument("--feature", action="append", choices=sorted(FEATURES) + sorted(GFX_GROUPS), default=None)
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
