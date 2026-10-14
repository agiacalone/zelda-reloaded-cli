# Getting started

From nothing to a randomized Zelda ROM on Linux. About 20 minutes, most of it
waiting for downloads.

## What you need

| Need | Why |
|---|---|
| Docker | Wine and .NET run in a container, so nothing Windows-related touches the host |
| `innoextract`, `unzip`, `curl` | To unpack the official installer (`sudo dnf install innoextract unzip curl`) |
| About 6 GB of disk | The Wine + .NET 4.8 image is 4.5 GB |
| An unmodified **Legend of Zelda, The (USA)** ROM | The randomizer patches it. Rev 1, Europe and hacks are rejected. |

> [!NOTE]
> **A common misconception:** that this repo *is* the randomizer. It holds only
> the wrapper. The randomizer is downloaded from its author during setup,
> because its license forbids redistributing it in any other form.

## 1. Set up

```sh
git clone git@github.com:agiacalone/zelda-reloaded-cli.git
cd zelda-reloaded-cli
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

## 3. Make a seed

```sh
export ZR_ROM="$HOME/roms/Legend of Zelda, The (USA).nes"
./bin/zelda-rando gen --preset 01-new-hyrule --asset "link=Zelda" --out out
```

The output folder `out/<SEED>/` holds:

| File | What it is |
|---|---|
| `Legend of Zelda [reloaded] SEED.nes` | The game. 256 KB, MMC1 with battery save. |
| `settings.xml` | The exact settings. Give it and the seed to someone else to reproduce the game. |
| `seedinfo.txt` | Version, seed and sanity hash. The hash also shows on the title screen. |
| `spoilers/{min,med,max}/` | Overworld and dungeon maps, from "where things are" to "everything". |

## 4. Make your own settings

Start from the defaults, or from a preset, and edit the XML:

```sh
./bin/zelda-rando defaults my.xml
./bin/zelda-rando gen --settings my.xml
```

Or build the settings in the Windows GUI, save them (*File → Save*), and pass that file.
The option names in the XML match the GUI's pages. The values used most are
`0` = off, `1` = on, `2` = random, and `a~b` for a range the seed picks from.

## If something goes wrong

| Symptom | Confirm | Fix |
|---|---|---|
| `not set up; run: zelda-rando setup` | `ls ~/.local/share/zelda-reloaded/vendor/zrcli.exe` | Run setup |
| `installer checksum mismatch` | `sha256sum ~/.local/share/zelda-reloaded/cache/*.zip`; want `c94139a4…` | The upstream file changed. Delete the cache and retry; if it still differs, check reloadedretro.com for a new version |
| `ROM is not the unmodified Legend of Zelda, The (USA)` | `tail -c +17 rom.nes \| head -c 131072 \| sha1sum`; want `a12d74c7…` | Use the unmodified USA (PRG0) ROM |
| `no link asset named '...'` | `zelda-rando list-assets link` | Use the exact name from the list, or run `update-packages --community` |
| `timed out after 900s` | Run again with `-v` and watch for `salt N:` lines | Raise `--timeout`; chaos settings retry more |
