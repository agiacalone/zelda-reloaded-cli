#!/usr/bin/env python3
"""Build the preset settings files from the GUI defaults (defaults.xml).

Each preset is the default settings plus a list of changes. Run it after
editing a preset below; it rewrites presets/<name>.xml.

    python3 presets/make-presets.py

The hero sprite is not part of the settings file. It is a graphics pack chosen
at generation time (zelda-rando gen --asset link=NAME); HERO records the one
each preset is meant to use. Presets with a Zelda hero also record NPC = "The
Quest of Zelda" (--asset npc=NAME), whose captive in Level 9 is Link, so the
roles are swapped at both ends of the game.
"""
import copy
import pathlib
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent

# RecorderRulesPreset "any" and "q2" made every overworld attempt fail in 1.0.98
# ("could not generate overworld", 20 of 20 salts), so no preset uses it.
#
# Option values used below: 0 = off, 1 = on, 2 = random. Numbers written as
# "a~b" are ranges; the seed picks a value in them.

OW_GEN = dict(EntranceRulesPreset="q1", BombRulesPreset="default", BurnRulesPreset="default",
              RecorderRulesPreset="default", AllowOverworldEnemies="1", AllowDungeonEnemies="0",
              AllowBossesAsEnemies="0", AllowSecondQuestBubbles="0", EnemyRulesPreset="medium")
DG_GEN = dict(BuildRulesPreset="q1", AllowOverworldEnemies="0", AllowDungeonEnemies="1",
              AllowBossesAsEnemies="0", AllowSecondQuestBubbles="0", EnemyRulesPreset="medium",
              UseNonStandardRooms="0", FlipMirrorRooms="0", SwapRoomTiles="0", FlippedMode="0",
              AllowBlackout="0")

PRESETS = {
    "01-new-hyrule": dict(
        title="A New Hyrule", stars=1, hero="Zelda", npc="The Quest of Zelda",
        overworld=dict(EnemyRulesPreset="easier"),
        dungeons=dict(EnemyRulesPreset="easier"),
        stats=dict(Hearts="4~4", MaxHearts="4~4", Bombs="4~4"),
        behaviors=dict(StackPotions="1"),
    ),
    "02-moonlit": dict(
        title="Hyrule by Moonlight", stars=2, hero="Zelda (Breath of the Wild)", npc="The Quest of Zelda",
        overworld=dict(EntranceRulesPreset="any", BombRulesPreset="any", BurnRulesPreset="any",
                       RecorderRulesPreset="default", AllowDungeonEnemies="1"),
        night=1,
        dungeons=dict(BuildRulesPreset="q2", EnemyRulesPreset="prog", UseNonStandardRooms="1",
                      FlipMirrorRooms="1", SwapRoomTiles="1"),
        equip=dict(BraceletForGraves="1"),
    ),
    "03-looking-glass": dict(
        title="Through the Looking Glass", stars=3, hero="Shadow Link",
        overworld=dict(EntranceRulesPreset="q2", BombRulesPreset="any", BurnRulesPreset="any",
                       RecorderRulesPreset="default", EnemyRulesPreset="harder", AllowDungeonEnemies="1"),
        ow_mirror=1, ow_recolor=1,
        dungeons=dict(BuildRulesPreset="chaos", EnemyRulesPreset="medium", UseNonStandardRooms="1",
                      FlipMirrorRooms="1", SwapRoomTiles="1", FlippedMode="1"),
        dg_mirror=1, dg_recolor=1,
        swaps=dict(ItemsEnabled="1", EnemiesEnabled="1"),
        bubbles=dict(DisableA="0", SwapButtons="1", Invert="1", DecidePerLevel="1"),
    ),
    "04-haunted": dict(
        title="The Haunting of Hyrule", stars=4, hero="Zelda (The Quest of Zelda)", npc="The Quest of Zelda",
        overworld=dict(EntranceRulesPreset="any", BombRulesPreset="any", BurnRulesPreset="any",
                       RecorderRulesPreset="default", EnemyRulesPreset="harder",
                       AllowDungeonEnemies="1", AllowBossesAsEnemies="1"),
        night=1,
        dungeons=dict(BuildRulesPreset="chaos", EnemyRulesPreset="harder", UseNonStandardRooms="1",
                      FlipMirrorRooms="1", SwapRoomTiles="1", AllowBlackout="1",
                      AllowOverworldEnemies="1"),
        dg_recolor=1,
        # 4 = fully visible, 0 = invisible; 1-3 dither the sprite away.
        visibility={"Ghini": "0~0", "Darknut": "2~2", "Wizzrobe": "1~1", "Gibdo": "2~2",
                    "Stalfos": "2~2", "Lynel": "2~2", "PolsVoice": "2~2", "Bubble": "1~1",
                    "Wallmaster": "1~1", "LikeLike": "2~2"},
        combat=dict(BaseDefenseAdjustment="1~1", BaseOffenseAdjustment="125~125"),
        likelikes=dict(Shield="1", Ring="1", Money="1", MinSimulThings="1", MaxSimulThings="2"),
        enemies=dict(GanonWarping="2~2", GanonStunTime="48~48"),
    ),
    "05-gauntlet": dict(
        title="Ganon's Gauntlet", stars=5, hero="Zelda (Hyrule Warriors)", npc="The Quest of Zelda",
        overworld=dict(EntranceRulesPreset="any", BombRulesPreset="any", BurnRulesPreset="any",
                       RecorderRulesPreset="default", EnemyRulesPreset="random",
                       AllowDungeonEnemies="1", AllowBossesAsEnemies="1", AllowSecondQuestBubbles="1"),
        ow_mirror=2,
        dungeons=dict(BuildRulesPreset="chaos", EnemyRulesPreset="random", UseNonStandardRooms="1",
                      FlipMirrorRooms="1", SwapRoomTiles="1", FlippedMode="2", AllowBlackout="1",
                      AllowOverworldEnemies="1", AllowBossesAsEnemies="1", AllowSecondQuestBubbles="1"),
        dg_mirror=2, dg_recolor=1,
        visibility={"Wizzrobe": "2~2", "Bubble": "2~2", "Ghini": "1~1"},
        combat=dict(BaseDefenseAdjustment="1~2", EachDefenseAdjustment="0~1",
                    BaseOffenseAdjustment="150~150", EachOffenseAdjustment="100~125"),
        damage={"sword1": "12~20", "sword1_beam": "12~20", "sword2": "24~40", "sword2_beam": "24~40",
                "sword3": "48~80", "sword3_beam": "48~80", "arrows": "24~40", "bombs": "48~80",
                "candle": "12~20", "wand": "24~40", "wand_beam": "24~40"},
        bubbles=dict(DisableA="1", DisableB="1", Slow="1", SwapButtons="1", Drunk="1", Invert="1",
                     HalfDefense="1", HalfOffense="1", MinSimulCurses="1", MaxSimulCurses="2",
                     DecidePerLevel="1", MinCurseTime="16", MaxCurseTime="32"),
        likelikes=dict(Shield="1", Money="1", Key="1", Bombs="1", Potion="1", Ring="1",
                       MinSimulThings="1", MaxSimulThings="2", DecidePerLevel="1",
                       MinDelay="48", MaxDelay="96"),
        equip=dict(BraceletForGraves="1", BraceletForBlocks="1"),
        enemies=dict(Enable2QStalfos="1", Enable2QRopes="1", GanonHealing="1~2",
                     GanonWarping="3~4", GanonStunTime="32~48"),
    ),
}


def op(root, key):
    return root.find(f"./Operation[@Key='{key}']")[0]


def set_text(parent, name, value):
    parent.find(name).text = str(value)


def make_generated(cfg, gen_defaults, changes, mirror=0, recolor=0, night=None):
    """Switch an overworld or dungeon section from vanilla to generated."""
    set_text(cfg, "UseNormalQ1", "false")
    set_text(cfg, "Generate", "true")
    gen = ET.Element("GenerationSettings", {**gen_defaults, **changes})
    idx = list(cfg).index(cfg.find("Generate")) + 1
    cfg.insert(idx, gen)
    set_text(cfg, "MirroringMode", mirror)
    set_text(cfg, "RecoloringMode", recolor)
    if night is not None:
        set_text(cfg, "NightMode", night)


def build(name, p, base):
    root = copy.deepcopy(base)
    make_generated(op(root, "overworld_mode"), OW_GEN, p.get("overworld", {}),
                   p.get("ow_mirror", 0), p.get("ow_recolor", 0), p.get("night", 0))
    make_generated(op(root, "dungeons_mode"), DG_GEN, p.get("dungeons", {}),
                   p.get("dg_mirror", 0), p.get("dg_recolor", 0))
    for k, v in p.get("stats", {}).items():
        set_text(op(root, "general_stats"), k, v)
    for k, v in p.get("behaviors", {}).items():
        set_text(op(root, "general_options"), k, v)
    for k, v in p.get("damage", {}).items():
        op(root, "general_damage").find(f"./Entry[@Key='{k}']").set("Value", v)
    combat = op(root, "combat_difficulty")
    for k, v in p.get("combat", {}).items():
        set_text(combat, k, v)
    vis = op(root, "enemy_visibility")
    for k, v in p.get("visibility", {}).items():
        ET.SubElement(vis, "Entry", Key=k, Value=v)
    for key, attrs in (("specials_equipment", "equip"), ("specials_bubbles", "bubbles"),
                       ("specials_likelikes", "likelikes"), ("specials_spriteswaps", "swaps")):
        for k, v in p.get(attrs, {}).items():
            op(root, key).set(k, v)
    enemies = op(root, "specials_enemies")
    for k, v in p.get("enemies", {}).items():
        set_text(enemies, k, v)
    ET.indent(root, space="  ")
    out = HERE / f"{name}.xml"
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    print(f"{out.name}: {p['title']} ({'*' * p['stars']}), hero: {p['hero']}")


def main():
    base = ET.parse(HERE / "defaults.xml").getroot()
    for name, p in PRESETS.items():
        build(name, p, base)
    with open(HERE / "HEROES.tsv", "w") as f:
        for name, p in PRESETS.items():
            f.write(f"{name}\t{p['hero']}\t{p['title']}\t{p['stars']}\t{p.get('npc', '')}\n")


if __name__ == "__main__":
    main()
