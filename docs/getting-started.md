# Getting started

From nothing to a randomized Zelda ROM with Redux's features, on Linux. About 30
minutes, most of it waiting for downloads.

## The pieces

```mermaid
flowchart LR
    R["Your USA ROM"] --> G["Reloaded<br/>(Windows app, run under Wine)"]
    G -- "a new world" --> S["Seed ROM"]
    S --> M["Remuxed:<br/>Redux source assembled<br/>onto the seed"]
    M --> O["Your game"]
```

1. **Reloaded** makes the seed: a new overworld and new dungeons. It is a Windows program,
   so it runs in a container with Wine.
2. **Remuxed** then adds Redux's features to that seed: the automap, the HUD, file copy and
   erase, new dungeon music and more. This step is optional (`--mod redux`).

## What you need

| Need | Why |
|---|---|
| Docker | Wine and .NET run in a container, so nothing Windows-related touches the host |
| `innoextract`, `unzip`, `curl` | To unpack the official installer (`sudo dnf install innoextract unzip curl`) |
| About 6 GB of disk | The Wine + .NET 4.8 image is 4.5 GB |
| An unmodified **Legend of Zelda, The (USA)** ROM | The randomizer patches it. Rev 1, Europe and hacks are rejected. |
| `git`, `cmake`, a C++ compiler, Python 3 | For Remuxed: to fetch Redux and build the Asar assembler (`sudo dnf install git cmake gcc-c++ python3`) |

> [!NOTE]
> **Two common misconceptions.** First, that this repo *is* the randomizer: it holds only
> the wrapper, and the randomizer is downloaded from its author during setup. Second, that
> Remuxed applies Redux's patch file to a seed: it cannot, because Redux's patch expects the
> original ROM. Remuxed assembles Redux's *source* onto each seed instead, which is why it
> needs its own setup step.

## 1. Set up

```sh
git clone https://github.com/agiacalone/zelda-remuxed.git
cd zelda-remuxed
./bin/zelda-rando setup
```

Setup downloads the official installer, checks its SHA-256, extracts it to
`~/.local/share/zelda-reloaded/vendor`, compiles the `zrcli` driver against it,
and builds the container image. Most of the time goes to installing .NET 4.8
inside Wine. Expect "Executing wine ..." lines for several minutes.

Good result: the last line reads `set up in /home/you/.local/share/zelda-reloaded`.

## 2. Download the sprites

```sh
./bin/zelda-rando update-packages --community
./bin/zelda-rando list-assets link
```

This uses the app's own updater, the same one the GUI runs at startup.
`--community` adds community packs, which include most of the Zelda hero sprites.

Good result: `459 assets in C:\ProgramData\reloaded\packages\zelda` (the count may grow).

## 3. Set up Remuxed

```sh
./bin/zelda-rando setup-redux
```

This clones Redux at the commit pinned in `mods/redux/PINS`, downloads the Asar
source, checks its SHA-256, and builds it. It takes a minute or two.

Good result: `Redux f096f69 and Asar b8c2623 ready in /home/you/.local/share/zelda-reloaded`.

## 4. Make a seed

```sh
export ZR_ROM="$HOME/roms/Legend of Zelda, The (USA).nes"
./bin/zelda-rando gen --preset 01-new-hyrule --asset link=Zelda --asset "npc=The Quest of Zelda" \
    --mod redux --out out
```

Leave out `--mod redux` for a plain Reloaded seed. With it, the last line reports
how many bytes Remuxed wrote; any safety failure stops the build with the address
and the reason.

The output folder `out/<SEED>/` holds:

| File | What it is |
|---|---|
| `Legend of Zelda [reloaded] SEED.nes` | The game. 256 KB, MMC1 with battery save. Use `--name` to choose the file name. |
| `settings.xml` | The exact settings. Give it and the seed to someone else to reproduce the game. |
| `seedinfo.txt` | Version, seed and sanity hash. The hash also shows on the title screen. |
| `spoilers/{min,med,max}/` | Overworld and dungeon maps, from "where things are" to "everything". |

## 5. Make your own settings

Start from the defaults, or from a preset, and edit the XML:

```sh
./bin/zelda-rando defaults my.xml
./bin/zelda-rando gen --settings my.xml
```

Or build the settings in the Windows GUI, save them (*File → Save*), and pass that file.
The option names in the XML match the GUI's pages. The values used most are
`0` = off, `1` = on, `2` = random, and `a~b` for a range the seed picks from.

## 6. Play

Any NES emulator with MMC1 battery saves works. Tested with FCEUmm in RetroArch
(Steam Deck, ROCKNIX handhelds) and with FCEUX. In game:

- **Save:** on the pause screen, press Up+A, then choose SAVE. Your map is saved with your file.
- **Select** switches the B item.
- The map in the HUD fills in as you explore, coloured by region.

## If something goes wrong

See [troubleshooting.md](troubleshooting.md). Each entry has a command that confirms the cause.
