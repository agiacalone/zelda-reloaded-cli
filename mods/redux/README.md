# redux: Zelda Remuxed internals

How `remux.py` puts Zelda Redux features onto a Zelda [reloaded] seed: every edit to
Redux's source, the battery-RAM map, and the checks that stop a bad build. For using it,
see the [main README](../../README.md) and `zelda-rando gen --mod redux`.

> [!NOTE]
> Every feature below is tested in FCEUX on the five preset seeds. The automap, dungeon
> automap, HUD, Copy/Erase, dungeon music, sword, item drops and graphics have also been
> played on a Steam Deck (RetroDECK, FCEUmm); the item toggle is tested in FCEUX only so
> far. Several fixes were found only in play, so new features get a hardware pass
> before they ship.

**Zelda Remuxed** puts features of [The Legend of Zelda Redux](https://github.com/ShadowOne333/The-Legend-of-Zelda-Redux)
(ShadowOne333 and contributors, GPL-3) onto a Zelda [reloaded] seed. Redux improves the
original game; Reloaded builds a new world. Redux's source is modular, one file per
feature, so `remux.py` assembles chosen features straight onto the seed.

Redux is written against the original ROM, and Reloaded changes that ROM: it moves the
fixed bank from 7 to 15 and uses some of the space and RAM Redux expects to be free.
Each feature therefore gets a short list of source edits that move it out of Reloaded's
way. The assembler then repoints every jump to the moved code.

## Use

```sh
python3 mods/redux/remux.py --redux REDUX_DIR --asar ASAR \
    "Legend of Zelda, The (USA).nes" out/SEED out/SEED/remuxed.nes
```

| Input | What |
|---|---|
| `REDUX_DIR` | Redux source: [agiacalone/The-Legend-of-Zelda-Redux](https://github.com/agiacalone/The-Legend-of-Zelda-Redux) at `f096f692a8900108713210c09e72545de5a4cf9e` |
| `ASAR` | [Asar](https://github.com/RPGHacker/asar) 2 built from source, branch `asar_2_beta` at `b8c26234f0fae893aab8ec842670244309a3ab2f` (`cmake -S src -B build -G Ninja && ninja -C build`) |
| `out/SEED` | a seed folder from `zelda-rando gen`: the ROM and `spoilers/min/Overworld.png` |

Neither Redux nor Asar is included. Both are fetched at the commits above and built
locally; Redux's bundled `bin/asar` binary is not used.

## Safety

After assembling, every changed byte must be one of these, or the build stops:

- free space in the seed (`0xFF`)
- a byte Reloaded left as in the original game, where Redux expects to patch
- a glue write listed in `GLUE_SITES`, with the seed byte it expects to replace

## The automap

Redux's automap is snarfblam's Automap Plus, disassembled and extended by ShadowOne333:
quarter hearts, a map coloured by region, and a blinking position marker. On a seed:

| Problem | Change |
|---|---|
| Redux's map picture is of the original Hyrule | `tools/automap.py` draws the seed's own from its spoiler map |
| Redux's region colours are chosen for the original Hyrule | Each HUD palette area (4 screens across) picks green, grey or brown from the seed's terrain |
| Picture at bank 5 `$AD00`, blocks at bank 5 `$AF20` and bank 2 `$B000`: space Reloaded uses | Moved to `$B900`, `$BB00` and `$B100` |
| RAM `$7F10-$7F29`: Reloaded copies code there at power-on | Moved; see the RAM map below |
| Two fixed-bank routines; Reloaded leaves only small gaps in bank 15 | One moves to `$FFDB`; the other splits into a bank 6 check and a 13-byte stub at `$FF42` |
| Redux draws the map into the four tile banks of its overworld animation | Reloaded has one tile bank: draw once, never switch |
| Fast life fill at bank 5 `$B1F2` | Left out: Reloaded's FastFill rewrote that code |
| Redux's HUD icons include the arrow counter | The original icon column, until the arrow counter is ported |
| Quarter-heart tiles live in Redux's whole-bank graphics | Only those four tiles are copied, into bank 2 and Reloaded's 10 tile copies |
| The game's power-on RAM copy erases the saved maps | The copy stops at `$7F50`; a stub keeps Reloaded's `$7FFF` marker |

## The dungeon automap

`dungeon-automap` (tacoschip's, from Redux) needs no edits: it writes only free space
and code Reloaded left as in the original, and the routines it calls are unchanged in
the seeds checked. Rooms appear on the dungeon map as you enter them.

## The HUD

Redux's HUD is four features that go together, in this order: `hud-subscreen`,
`arrows`, then `automap`, `rupees` and `hud-layout`. Life moves left, the map moves
right, and the counters become rupees, keys, arrows and bombs (999 rupees, an arrow
count).

| Problem | Change |
|---|---|
| The status-bar template at bank 5 `$AC70`: space Reloaded uses | Moved to `$AE10`; the rupee code that reads it follows |
| Redux's dungeon mini-maps and map dots are for the original dungeons | Left out; instead each seed's own are moved 20 tiles right (`+$14` on each screen address, `+$A0` on each dot), after a parser checks every list |
| Link's Level 3 palette tweak | Left out: Reloaded picks its own dungeon palettes |
| The HUD's icons and hearts are in Redux's whole-bank graphics | Ten tiles are copied, into bank 2 and Reloaded's tile copies; each tile block has its own anchor |
| Redux's "TRIFORCE OF WISDOM" caption: Reloaded draws the caption its own way, so "OF WISDOM" landed on "TRIFORCE" | Left out |
| The subscreen says "SAVE: UP+A"; Reloaded's save takes Up+A on controller 2 or Up+Select+A on controller 1 | Reloaded's check (bank 5 `$AD2A`, `$AD2C`) now takes Up+A on controller 1, as in Redux |
| Redux renames the dungeon caption "LEVEL-7" to "DUNGEON-7" and moves the digit; Reloaded draws its own caption, so the digit was lost | Keep "LEVEL-7" and move it above the map (`$2042` to `$2056`). The caption is kept in battery RAM, so the power-on stub re-points it for older save files too |
| Redux's small "x" is tile `$62`, which Reloaded uses as the dash in "LEVEL-7" | The counters keep the original "X" (tile `$21`) |
| The dungeon HUD attributes at bank 6 `$A2CD` overwrite the end of the game-over menu ("RETRY"); Redux moves that menu text in a feature not ported here | Moved to `$B100` |
| The arrow-drop routine runs from RAM, in a part of bank 1 the mirrored seeds fill | A RAM routine area: the power-on stub copies bank 1 `$9EC4` to RAM `$7F84-$7F9F` (see the RAM map) |

### Features that overwrite each other

The byte check compares each write with the seed, so it cannot see one feature
overwrite another. `check_overwrites` builds the features one more at a time, in
Redux's order, and stops if a feature changes a byte an earlier one wrote, apart from
the overwrites Redux documents (`ALLOWED_OVERWRITES`: `move_maps.asm` and `rupee.asm`
patch the HUD, arrow and automap code). It caught the item toggle (bank 2
`$B7A8-$B85B`) overwriting the automap's save code, which the port had placed at
`$B800`; that broke name registration. The automap block now sits at `$B100`. The
check adds a minute or so per build. Moving the block to `$BA00` then put it on
Copy/Erase's code, which the check caught on the next build.

Source edits must match exactly once: `edit()` stops the build on a second match.
Copy/Erase's map copy once read the new address and wrote the old one, because an
edit changed only the first of two matches.

### A blind spot of the safety check

The check accepts a write over a byte Reloaded left as in the original game, because
that is how Redux patches the original. It cannot tell when Redux overwrites original
content that another Redux feature moves out of the way first. "RETRY" was lost that
way. Each port is therefore also played through its menus, not only built.

## Features that need no edits

These touch nothing Reloaded changed, build together without overwriting one another,
and pass a new game, a death, a save and a reload in FCEUX:

| Feature | Redux file | What it does |
|---|---|---|
| `save-hearts` | `menus/save_hearts.asm` | Keep the hearts you saved with (at least 3) |
| `fix-bait`, `fix-candle`, `fix-cave-timer`, `fix-level1-door`, `fix-keyhole`, `fix-beam`, `fix-leave-cave`, `fix-scroll` | `bugfixes/*.asm` | Redux's eight bug fixes |
| `sword-draw`, `sword-swing` | `gameplay/sword_*.asm` | The diagonal sword swing |
| `item-toggle` | `gameplay/item_toggle.asm` | Select switches the B item instead of pausing |
| `dungeon-music` | `music/dungeon_music.asm` | Four dungeon themes: levels 1 and 5 the original, 2 and 6 A New Light, 3 and 7 Perils of Darkness, 4 and 8 Triforce Power |
| `copy-erase` | `menus/menu_tweaks.asm` | Redux's file screen: copy and erase files; a copy takes the saved map along (edits: the map's new address, and the game-over heart stays at X `$40`, because Redux's caution screen that moves the menu text is not ported) |

Copy/Erase looked broken twice (names never saved; then existing files shown as
empty). Both times the cause was the automap's bank 2 block sitting on Copy/Erase's
code (`$BA00-$BE9A`), not Reloaded's save handling. The block now sits at `$B100`.
Both build safely; the clash is in behaviour, not bytes. `dungeon-music` is on hold
too: it passes every FCEUX test, but dungeon music plays wrong on hardware.

## Battery RAM map

`$6000-$7FFF` is battery-backed. At every power-on and game start the game copies
bank 1 `$A500+` over `$6C90-$7F4F` (the stub stops it there). Measured with a write
trace across the overworld and all nine levels, plus a scan of every absolute access:

| Range | Owner | Use |
|---|---|---|
| `$7F10-$7F25` | Reloaded | Code copied in at power-on (enemy visibility) |
| `$7F26-$7F39` | Remuxed (automap) | Working data: PPU macro, map bits, blip position |
| `$7F40-$7F83` | Reloaded | Graphics streamer (bank 3 `$BA38`): 64-byte chunks staged when a room loads new enemy, boss or NPC graphics |
| `$7F84-$7F9F` | Remuxed | RAM routines, copied from bank 1 `$9EC4` at power-on (the arrow drop) |
| `$7FAF` | Remuxed | `$5A` once the map area has been cleared |
| `$7FB0-$7FBF` | Remuxed (automap) | Visited screens |
| `$7FC0-$7FEF` | Remuxed (automap) | Saved maps, 16 bytes per file |
| `$7FFF` | Reloaded | `$A5` marker |

The first port put the automap at `$7F30-$7F8F` and the arrow routine at `$7FA0`.
The streamer overwrote the maps in rooms that load graphics, and a graphics bug
overwrote the routine's source in ROM; together they froze the game on a miniboss and
on the sword pickup (2026-10-14). The graphics step now writes a tile only where the
assembled ROM, not just the seed, still has the original.

## Graphics

Redux ships its graphics as whole blocks. Reloaded keeps many of the original blocks,
some moved or copied (the dungeon set nine times), and its graphics packs redraw
others. `graphics` finds every copy of each block in the seed, by windows of the
original bytes, and writes Redux's version of a tile only where the seed still has the
original tile. A pack's own tile (your hero, an NPC set) always wins.

| Group | Blocks | What it draws |
|---|---|---|
| `graphics` | `data_00a`, `data_00b`, `data_01b`, `data_01c`, `data_02a`, `data_03f-h` | Intro and title, font, hearts and icons, dungeon walls and floors, bosses, Ganon, Zelda |
| `graphics-overworld` | `data_02b` | Overworld tiles (not yet tested in play: Redux drew them for its own column layouts) |

Not ported: `data_01a` (Link, items, sword) and `data_03a-e` (enemies, NPCs), which
the graphics packs replace. Tiles `$59` and `$62` are excluded: Reloaded uses `$62`
as the dash in "LEVEL-7".

## Keeping up with Redux

Redux is an active project. `PINS` records the Redux and Asar commits Remuxed is built
against. `upstream-check` fetches upstream Redux, builds every finished feature onto a
reference seed, and posts to ntfy only when something changed:

- upstream moved and Remuxed still builds: the pin can move
- upstream moved and the build fails: the message names the source edit or the address
  that stopped it, which is what needs adapting

On reason it runs weekly from the user timer `remuxed-upstream.timer` (Monday 06:00).
Run it by hand with `mods/redux/upstream-check -n` to print the result without notifying.

## Next

- `graphics-overworld`, tested in play
- `zelda-rando gen --mod redux:FEATURE`
