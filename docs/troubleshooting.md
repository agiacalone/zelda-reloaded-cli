# Troubleshooting

Each entry gives the symptom, a command that confirms the cause, and the fix.

> [!CAUTION]
> Use the unmodified *Legend of Zelda, The (USA)* ROM. The wrapper rejects a Rev 1, European or already-patched ROM by checksum.

## Setup

| Symptom | Confirm | Fix |
|---|---|---|
| `not set up; run: zelda-rando setup` | `ls ~/.local/share/zelda-reloaded/vendor/zrcli.exe` | Run `zelda-rando setup`. |
| `installer checksum mismatch` | `sha256sum ~/.local/share/zelda-reloaded/cache/*.zip`; want `c94139a4…` | The download was cut short, or upstream changed the file. Delete the cache and retry. If it still differs, check [reloadedretro.com](https://www.reloadedretro.com/games/zelda) for a new version. |
| `permission denied` on the Docker socket | `docker info` | Add yourself to the `docker` group, or run rootless Docker. |

## Generating

| Symptom | Confirm | Fix |
|---|---|---|
| `ROM is not the unmodified Legend of Zelda, The (USA)` | `tail -c +17 rom.nes \| head -c 131072 \| sha1sum`; want `a12d74c7…` | Use the unmodified USA (PRG0) ROM. |
| `no link asset named '...'` | `zelda-rando list-assets link` | Use the exact name from the list, or run `update-packages --community` first. |
| `could not generate overworld` on every salt, then failure | `grep -o 'RecorderRulesPreset="[a-z0-9]*"' settings.xml` | `any` and `q2` failed every attempt in testing. Set `RecorderRulesPreset="default"`. |
| `timed out after 900s` | Run again with `-v` and watch for `salt N:` lines | Raise `--timeout`. Chaos settings retry more. |

## Reproducing a seed

| Symptom | Confirm | Fix |
|---|---|---|
| Same seed, different game from the Windows GUI | Compare the hash in each `seedinfo.txt` (also on the title screen) | Both sides need version 1.0.98 and the same `settings.xml`. Any changed option changes every seed. |
| `cmp` reports a difference, but the hashes match | `cmp -l a.nes b.nes \| wc -l`; a few hundred bytes | A different graphics pack. Pass the same `--asset` values the other side used. Sprites do not change the hash. |

## Remuxed (`--mod redux`)

| Symptom | Confirm | Fix |
|---|---|---|
| `Redux is not set up; run: zelda-rando setup-redux` | `ls ~/.local/share/zelda-reloaded/asar/asar ~/.local/share/zelda-reloaded/redux` | Run `zelda-rando setup-redux`. |
| `Asar source checksum mismatch` | `grep ASAR_SHA256 mods/redux/PINS` | The download was cut short, or GitHub changed the archive. Retry; if it persists, rebuild Asar from the pinned commit and update `ASAR_SHA256`. |
| `source edit matched 0 times` or `matched 2 times` | `git -C ~/.local/share/zelda-reloaded/redux log -1 --format=%h`; want the `REDUX_COMMIT` in `PINS` | Redux's source differs from the pin. Run `setup-redux` again to check out the pinned commit. |
| `N unsafe writes` with addresses | Rerun with fewer `--mod redux:` features to find which one | A seed option this port has not seen puts Reloaded data where a feature writes. Open an issue with the seed and settings. |
| `features overwrite each other` | The message names both features | Two features want the same bytes. Leave one out with `--mod redux:...`, and report it. |
| The map in the HUD is empty after loading a file | Save on the pause screen (Up+A, SAVE), quit, reload | The map is saved only when you save. The first boot of a new Remuxed build also clears old map data once. |
