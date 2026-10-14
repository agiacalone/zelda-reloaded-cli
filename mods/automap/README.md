# automap (experimental)

> [!WARNING]
> **Experimental.** This works on the seeds tested so far, but it is not yet wired
> into `zelda-rando gen` and has not been tested on every preset. See *Status* below.

[Zelda Automap Plus](https://www.romhacking.net/hacks/796/) by snarfblam adds a small
overworld map to the status bar. Each screen fills in the first time you visit it, so
the map is a record of where you have been. It was written for the original game, and
its map picture is of the original Hyrule.

This mod puts it on a Zelda [reloaded] seed:

- **The map picture is the seed's own.** `tools/automap.py` draws it from the seed's
  `spoilers/min/Overworld.png`, so the map shows the new Hyrule.
- **The patch is ported to Reloaded's ROM layout.** It cannot be applied as-is: Reloaded
  doubles the ROM to 256 KB, moves the fixed bank, and uses some of the free space and
  RAM the patch expects.

## Use

You need snarfblam's `AutomapPatch0.2.zip` from romhacking.net (it is not included, and
romhacking.net blocks scripted downloads). Unzip it to get `Automap0.2.IPS`.

```sh
python3 tools/automap.py render out/SEED/spoilers/min/Overworld.png map.bin
python3 mods/automap/port.py Automap0.2.IPS "Legend of Zelda, The (USA).nes" \
    out/SEED/SEED.nes map.bin out/SEED/SEED-automap.nes
```

`port.py` checks the patch's SHA-256 and refuses any other version. Before it writes
anything, it checks every target in the seed: code it patches must still be the original
bytes, and space it moves things into must be empty. If either check fails, the seed was
made with options this port has not seen, and it stops instead of writing a broken ROM.

## What the port changes

| Problem in a Reloaded seed | Change |
|---|---|
| The fixed bank moved from bank 7 to bank 15 | Its records shift by `0x20000` |
| Reloaded uses three blocks of the patch's free space | Moved to free space; 9 jumps re-pointed |
| The fixed bank has only 16 free bytes | One routine fits exactly; the other is split into a bank 6 check and a 13-byte stub |
| The patch's RAM overlaps Reloaded's overworld data (`$6C00`) and its enemy-visibility code, which the game copies into RAM (`$7F10`) | 32 bytes of state moved to `$7F30-$7F4F`; 39 references rewritten, including the text-macro table entry the map draws through |
| That RAM is refilled from ROM at power-on, so the draw flag started set | The ROM source of the six flags is zeroed |
| The same copy erased the saved map at every power-on | The copy stops at `$7F50`; a stub writes Reloaded's `$7FFF` marker |
| The heart-refill tweak at bank 5 `$B1F3` | Skipped: Reloaded's own FastFill rewrote that code |

## Status

Tested on seed `BFEWOT86S` (preset 01), in FCEUX and on an Anbernic RG34XX-SP running
ROCKNIX (FCEUmm):

- [x] Boots and plays; graphics and status bar correct
- [x] New game starts with a dark map; visited screens fill in from the seed's map
- [x] The map is saved with your file and survives a power cycle
- [ ] Every screen revealed matches the seed's overworld
- [ ] Dungeons, the pause screen, dying and continuing
- [ ] The other four presets, especially the mirrored world of preset 03
- [ ] `zelda-rando gen --mod automap`

Credit: Zelda Automap Plus is snarfblam's work. This directory contains only the code
that ports it; the patch itself is never included.
