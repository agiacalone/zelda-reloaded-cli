#!/usr/bin/env python3
"""Port Zelda Automap Plus 0.2 (snarfblam) onto a Zelda [reloaded] seed.

    port.py PATCH.ips ORIGINAL.nes SEED.nes MAP.bin OUT.nes

Automap Plus is an IPS patch for the original 128 KB ROM. Reloaded seeds are
256 KB and reuse some of the free space the patch expects, so the patch cannot
be applied as-is. This applies it with the changes worked out on 2026-10-14:

  * The fixed bank moved from bank 7 to bank 15: its records shift by 0x20000.
  * Three blocks Reloaded now occupies are moved to space that is free in the
    original ROM and in every seed tested, and every jump into them is fixed.
  * The map picture is the seed's own (MAP.bin, from automap.py render), placed
    at $B900 in bank 5; the one instruction that addresses it is updated.
  * The heart-refill tweak at $B1F3 is skipped: Reloaded's FastFill rewrote the
    same code, and the automap does not depend on it.

Before writing anything it checks every target: a hook site must still hold the
original bytes, and a new home must be empty (0xFF). If either is not true the
seed was built with options this port has not seen, and it stops.
"""
import hashlib
import os
import sys

# SHA-256 of Automap0.2.IPS from snarfblam's AutomapPatch0.2.zip (romhacking.net hack 796).
# Every offset below was worked out against exactly this patch.
PATCH_SHA256 = "e793711046343e392c1251a7e75ed05e7581d239060598ea52bb50c2cff08ada"

BANK = 0x4000
HDR = 16

# Patch records (original-ROM file offsets) that are handled specially.
SKIP = {
    0x17203,   # bank 5 $B1F3: heart refill speed; Reloaded's FastFill owns it
    0x20010,   # 2 bytes past the end of the original ROM: a quirk of the patch
    0x16D11,   # the original map picture: replaced by the seed's own below
}
# Blocks moved out of space Reloaded uses: (record offset, bank, old addr, new addr)
MOVES = [
    (0x0B010, 2, 0xB000, 0xB800),   # 71 bytes: save/load the visited-screen bits
    (0x16F30, 5, 0xAF20, 0xBB00),   # 17 bytes: HUD macro selector
]
MAP_BANK, MAP_ADDR, MAP_SIZE = 5, 0xB900, 512
MAP_PTR = (5, 0xBCD4)               # operand of `adc #$AD` that sets the map's page
FIXED_REC = 0x1FFD0                 # $FFC0-$FFE5: two fixed-bank routines, 38 bytes
DISPATCH_NEW = 0xFFDB               # the 16-byte bank dispatcher ($FFD6) moves here
STUB_ADDR = 0xFF42                  # 13-byte "switch to bank 5, update, back" stub
BANK6_ADDR = 0xB000                 # the overworld check that used to be in the fixed bank


FIXUPS = []

# RAM. Automap Plus keeps 32 bytes of working state at $6C00-$6C05 and
# $7F10-$7F29. In a Reloaded seed both collide: the game loads overworld data
# over $6C00, and Reloaded's enemy-visibility code is copied from bank 1 into
# $7F10-$7F25 (the game runs part of its code from RAM). The next 32 bytes,
# $7F30-$7F4F, are copied from bank 1 $B7A0-$B7BF, which is empty in Reloaded,
# so the state moves there. The visited-screen bits at $7F50-$7F8F stay put.
def ram_remap(a):
    if 0x7F10 <= a <= 0x7F29:
        return a + 0x20
    if 0x6C00 <= a <= 0x6C05:
        return 0x7F4A + (a - 0x6C00)
    return a


RAM_SOURCE = (1, 0xB7A0, 0x20)     # bank 1 bytes copied into $7F30-$7F4F; must be empty
CODE_RECORDS = {0x17C10, 0x17C40, 0x19D80}   # the automap code that touches that RAM
MACRO_PTR = (6, 0x8619)            # the game's text-macro table entry the automap uses ($7F15)
# Every 6502 opcode with a 16-bit absolute (or absolute-indexed) operand.
ABS_OPS = {0x0D, 0x0E, 0x19, 0x1D, 0x1E, 0x2C, 0x2D, 0x2E, 0x39, 0x3D, 0x3E, 0x4D, 0x4E, 0x59, 0x5D,
           0x5E, 0x6D, 0x6E, 0x79, 0x7D, 0x7E, 0x8C, 0x8D, 0x8E, 0x99, 0x9D, 0xAC, 0xAD, 0xAE, 0xB9,
           0xBC, 0xBD, 0xBE, 0xCC, 0xCD, 0xCE, 0xD9, 0xDD, 0xDE, 0xEC, 0xED, 0xEE, 0xF9, 0xFD, 0xFE}


class PortError(Exception):
    pass


def ips_records(path):
    d = open(path, "rb").read()
    if hashlib.sha256(d).hexdigest() != PATCH_SHA256:
        raise PortError(f"{path}: not Automap Plus 0.2 (SHA-256 mismatch)")
    if d[:5] != b"PATCH":
        raise PortError(f"{path}: not an IPS patch")
    p, out = 5, []
    while d[p:p + 3] != b"EOF":
        off = int.from_bytes(d[p:p + 3], "big")
        size = int.from_bytes(d[p + 3:p + 5], "big")
        p += 5
        if size == 0:
            run = int.from_bytes(d[p:p + 2], "big")
            out.append((off, bytes([d[p + 2]]) * run))
            p += 3
        else:
            out.append((off, d[p:p + size]))
            p += size
    return out


def file_off(bank, addr):
    base = 0xC000 if bank in (7, 15) else 0x8000
    return HDR + bank * BANK + (addr - base)


def orig_bank(off):
    return (off - HDR) // BANK


def orig_addr(off):
    bank = orig_bank(off)
    return (0xC000 if bank == 7 else 0x8000) + (off - HDR) % BANK


class Rom:
    def __init__(self, data, original):
        self.data = bytearray(data)
        self.orig = original
        self.claimed = []           # (start, end) file ranges written, to catch overlaps

    def _claim(self, off, n, what):
        for s, e in self.claimed:
            if off < e and s < off + n:
                raise PortError(f"{what}: overlaps another write at 0x{s:05X}")
        self.claimed.append((off, off + n))

    def hook(self, off, data, orig_off, what):
        """Overwrite live game code: it must still be the original bytes."""
        want = self.orig[orig_off:orig_off + len(data)]
        have = bytes(self.data[off:off + len(data)])
        if have != want:
            raise PortError(f"{what}: seed code at 0x{off:05X} differs from the original "
                            f"({have.hex()} vs {want.hex()}); unsupported seed options")
        self._claim(off, len(data), what)
        self.data[off:off + len(data)] = data

    def place(self, off, data, what):
        """Write into free space: it must be empty (0xFF) in the seed."""
        have = self.data[off:off + len(data)]
        if any(b != 0xFF for b in have):
            raise PortError(f"{what}: 0x{off:05X}+{len(data)} is not free in this seed")
        self._claim(off, len(data), what)
        self.data[off:off + len(data)] = data


def word(v):
    return bytes([v & 0xFF, v >> 8])


def port(ips_path, original_path, seed_path, map_path, out_path):
    original = open(original_path, "rb").read()
    seed = open(seed_path, "rb").read()
    mapbin = open(map_path, "rb").read()
    if len(original) != HDR + 8 * BANK:
        raise PortError("ORIGINAL must be the 128 KB Legend of Zelda (USA)")
    if len(seed) != HDR + 16 * BANK:
        raise PortError("SEED must be a 256 KB Zelda [reloaded] ROM")
    if len(mapbin) != MAP_SIZE:
        raise PortError(f"MAP must be {MAP_SIZE} bytes")
    recs = ips_records(ips_path)
    rom = Rom(seed, original)

    # Where moved code now lives, for fixing the jumps that point at it.
    moved = {(bank, old): new for _, bank, old, new in MOVES}
    sizes = {off: len(data) for off, data in recs}

    def relocate(bank, value):
        for (b, old), new in moved.items():
            rec = next(o for o, bb, oo, _ in MOVES if bb == b and oo == old)
            if b == bank and old <= value < old + sizes[rec]:
                return new + (value - old)
        return value

    debug_skip = {int(x, 16) for x in os.environ.get("AUTOMAP_DEBUG_SKIP", "").split(",") if x}
    for off, data in recs:
        if off in SKIP or off in debug_skip:
            continue
        bank = orig_bank(off)
        addr = orig_addr(off)
        data = bytearray(data)
        is_free = all(b == 0xFF for b in original[off:off + len(data)])

        if off == FIXED_REC:
            continue                                   # handled below

        # Fix absolute JSR/JMP operands inside the record that point into moved blocks.
        for i in range(len(data) - 2):
            if data[i] in (0x20, 0x4C):
                v = data[i + 1] | data[i + 2] << 8
                nv = relocate(bank, v)
                if nv != v:
                    data[i + 1:i + 3] = word(nv)
                    FIXUPS.append(f"bank {bank} ${addr + i:04X}: ${v:04X} -> ${nv:04X}")
        # A 2-byte record is an operand patched after an existing JSR/JMP.
        if len(data) == 2 and original[off - 1] in (0x20, 0x4C):
            v = data[0] | data[1] << 8
            nv = relocate(bank, v)
            if nv != v:
                FIXUPS.append(f"bank {bank} ${addr:04X} (operand): ${v:04X} -> ${nv:04X}")
            data[:] = word(nv)

        if off in CODE_RECORDS:
            i = 0
            while i < len(data) - 2:
                if data[i] in ABS_OPS:
                    v = data[i + 1] | data[i + 2] << 8
                    nv = ram_remap(v)
                    if nv != v:
                        data[i + 1:i + 3] = word(nv)
                        FIXUPS.append(f"bank {bank} ${addr + i:04X}: RAM ${v:04X} -> ${nv:04X}")
                        i += 3
                        continue
                i += 1

        # A pointer built from immediates: lda #lo / sta $00 / lda #hi / sta $01.
        # $9D70 sends the map tile buffer this way, so the operand scan above
        # cannot see it.
        if off in CODE_RECORDS:
            for i in range(len(data) - 7):
                if (data[i], data[i + 2], data[i + 3], data[i + 4], data[i + 6], data[i + 7]) == \
                        (0xA9, 0x85, 0x00, 0xA9, 0x85, 0x01):
                    v = data[i + 1] | data[i + 5] << 8
                    nv = ram_remap(v)
                    if nv != v:
                        data[i + 1], data[i + 5] = nv & 0xFF, nv >> 8
                        FIXUPS.append(f"bank {bank} ${addr + i:04X}: pointer ${v:04X} -> ${nv:04X}")

        move = next(((b, o, n) for r, b, o, n in MOVES if r == off), None)
        if move:
            rom.place(file_off(bank, move[2]), bytes(data), f"moved block ${move[1]:04X}")
            continue
        target_bank = 15 if bank == 7 else bank
        target = file_off(target_bank, addr)
        if is_free:
            rom.place(target, bytes(data), f"automap code ${addr:04X} (bank {bank})")
        else:
            rom.hook(target, bytes(data), off, f"hook ${addr:04X} (bank {bank})")

    # The automap's RAM: its new home must be copied from empty ROM, and the
    # text-macro table entry it draws through must follow it.
    src = file_off(RAM_SOURCE[0], RAM_SOURCE[1])
    if any(x != 0xFF for x in rom.data[src:src + RAM_SOURCE[2] + 0x40]):
        raise PortError("bank 1 $B7A0-$B7FF is not empty: $7F30-$7F8F would hold seed code")
    # The game copies bank 1 $A500-$BF6F into RAM $6C90-$7FFF at power-on and at
    # game start, so these RAM bytes start as whatever the ROM holds there. Empty
    # ROM is $FF, which would leave the draw flag set (garbage tiles every frame).
    # Zero the source of the six flags/counters ($7F4A-$7F4F). The visited bits
    # ($7F50-$7F8F) are left out of the copy entirely (see Persistence below);
    # the start-up clear zeroes them on a fresh save.
    rom.data[src + 0x1A:src + 0x20] = bytes(6)
    mp = file_off(*MACRO_PTR)
    if rom.data[mp:mp + 2] != word(0x7F15):
        raise PortError("text-macro table entry for the map tile buffer not found")
    rom.data[mp:mp + 2] = word(ram_remap(0x7F15))
    FIXUPS.append(f"bank 6 ${MACRO_PTR[1]:04X}: macro pointer $7F15 -> ${ram_remap(0x7F15):04X}")

    # Persistence. At every power-on and game start the game copies bank 1
    # $A500-$BF6F into RAM $6C90-$7FFF, which overwrote the per-slot map bits at
    # $7F60-$7F8F before the automap could load them. Stop the copy at $7F50.
    # Reloaded keeps one byte in that tail: $7FFF = $A5 (a marker it checks), so
    # a stub in bank 1's free space writes it, then runs the shortened copy.
    loop_hi, loop_lo = file_off(1, 0x8D31), file_off(1, 0x8D37)
    if (rom.data[loop_hi], rom.data[loop_lo]) != (0x80, 0x00) or rom.data[loop_hi - 1] != 0xC9 or rom.data[loop_lo - 1] != 0xC9:
        raise PortError("RAM copy loop end not found at bank 1 $8D30/$8D36")
    tail = file_off(1, 0xB7C0)
    if any(x != 0xFF for x in rom.data[tail:tail + 0xAF]) or rom.data[tail + 0xAF] != 0xA5:
        raise PortError("bank 1 copy tail is not empty apart from the $7FFF marker; unsupported seed")
    rom.data[loop_hi], rom.data[loop_lo] = 0x7F, 0x50
    stub = bytes([0xA9, 0xA5, 0x8D, 0xFF, 0x7F,        # lda #$A5 ; sta $7FFF
                  0x4C, 0x00, 0x8D])                    # jmp $8D00 (the copy)
    rom.place(file_off(1, 0x8CF0), stub, "copy stub")
    for call in (0xE901, 0xE996):
        c = file_off(15, call)
        if rom.data[c:c + 3] != bytes([0x20, 0x00, 0x8D]):
            raise PortError(f"RAM copy call at ${call:04X} not found")
        rom.data[c + 1:c + 3] = word(0x8CF0)
    FIXUPS.append("RAM copy now stops at $7F50; $7FFF marker set by stub at bank 1 $8CF0")

    # The map picture: the seed's own, and the one instruction that finds it.
    rom.place(file_off(MAP_BANK, MAP_ADDR), mapbin, "map picture")
    ptr = file_off(*MAP_PTR)
    if 0x17C40 in debug_skip:
        pass
    elif rom.data[ptr] != 0xAD or rom.data[ptr - 1] != 0x69:
        raise PortError("map pointer instruction not found where expected")
    else:
        rom.data[ptr] = MAP_ADDR >> 8

    # The fixed bank. Routine 2 ($FFD6, 16 bytes) fits the free 16 bytes at $FFDB.
    fixed = dict(recs)[FIXED_REC]
    dispatcher = fixed[0x16:0x26]
    rom.place(file_off(15, DISPATCH_NEW), dispatcher, "bank dispatcher")
    # Its caller, `JSR $FFD6` at $F322, is a 2-byte operand record already applied
    # above with the old address; repoint it.
    call = file_off(15, 0xF323)
    if 0x1F333 in debug_skip:
        pass
    elif rom.data[call:call + 2] != word(0xFFD6):
        raise PortError("dispatcher call site not found")
    else:
        rom.data[call:call + 2] = word(DISPATCH_NEW)
    # Routine 1 ($FFC0, 18 bytes) is split: the overworld check moves to bank 6,
    # where its only caller lives, and the fixed bank keeps a 13-byte stub.
    stub = bytes([0xA9, 0x05, 0x20, 0xAC, 0xFF,       # lda #5 ; jsr $FFAC (map bank 5)
                  0x20, 0x66, 0xBC,                   # jsr $BC66 (redraw the map)
                  0xA9, 0x06, 0x4C, 0xAC, 0xFF])      # lda #6 ; jmp $FFAC (back to bank 6)
    rom.place(file_off(15, STUB_ADDR), stub, "bank-switch stub")
    check = bytes([0xA5, 0x10,                        # lda $10    (level: 0 = overworld)
                   0xD0, 0x03,                        # bne +3
                   0x20, STUB_ADDR & 0xFF, STUB_ADDR >> 8,   # jsr stub
                   0xE6, 0x11,                        # inc $11
                   0x60])                             # rts
    rom.place(file_off(6, BANK6_ADDR), check, "overworld check")
    caller = file_off(6, 0x8089)                      # bank 6: `JMP $FFC0`, applied above
    if 0x18099 in debug_skip:
        pass
    elif rom.data[caller:caller + 3] != bytes([0x4C, 0xC0, 0xFF]):
        raise PortError("bank 6 caller not found")
    else:
        rom.data[caller + 1:caller + 3] = word(BANK6_ADDR)

    open(out_path, "wb").write(rom.data)
    return len(rom.claimed)


if __name__ == "__main__":
    if len(sys.argv) != 6:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    try:
        n = port(*sys.argv[1:])
    except PortError as e:
        sys.exit(f"automap: {e}")
    print(f"automap: ported ({n} regions written)")
    for f in FIXUPS:
        print("  fixup", f)
