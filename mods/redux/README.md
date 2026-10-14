# redux (experimental)

> [!WARNING]
> **Experimental.** Two features so far. The automap is tested on the five preset seeds
> in FCEUX and on hardware; the dungeon automap is not yet tested in play. Neither is
> wired into `zelda-rando gen` yet.

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
| Picture at bank 5 `$AD00`, blocks at bank 5 `$AF20` and bank 2 `$B000`: space Reloaded uses | Moved to `$B900`, `$BB00` and `$B800` |
| RAM `$7F10-$7F29`: Reloaded copies code there at power-on | Moved to `$7F30` |
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

- Redux's HUD layout (map right, life left) and arrow counter
- The Redux features that do not touch Reloaded's changes: Copy/Erase, keep hearts on
  load, the bug fixes, Select to toggle the B item, diagonal sword, dungeon music
- `zelda-rando gen --mod redux:FEATURE`
