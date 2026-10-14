// zrcli: headless driver for "Legend of Zelda [reloaded]" 1.0.98 by MetalMachine.
//
// It loads the program's own DLLs and repeats what the GUI's Generate button does
// (Reloaded.UI.Zelda.App.Dialogs.GenerateDlg.DoGeneration), so a given seed and
// settings file produce the same ROM as the Windows app.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Xml.Linq;
using MM.Common;
using MM.RomStudio.Common;
using Reloaded.Cloud.Enums;
using Reloaded.Lib;
using Reloaded.Lib.Models;
using Reloaded.Lib.Zelda;
using Reloaded.Lib.Zelda.App;

class Host : IGeneratorHost
{
    public bool Verbose;
    public void ReportProgress(decimal p, string s) { if (Verbose) Console.Error.WriteLine($"  {p,5:0.0}% {s}"); }
}

static class Program
{
    // The version string the GUI feeds into the RNG and hash. Must match 1.0.98
    // or the same seed gives a different game.
    const string VersionStr = "1.0.98";
    const string SeedChars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

    class Op
    {
        public string Key, Type; public int Group;
        public Op(string k, int g, string t) { Key = k; Group = g; Type = t; }
    }

    // From Reloaded.UI.Zelda.App.Resources.Operations.xml (Key, ExecOrder, Type).
    static readonly Op[] Ops =
    {
        new Op("overworld_mode", 2, "OverworldConfig"), new Op("dungeons_mode", 2, "DungeonConfig"),
        new Op("general_stats", 1, "StartStats"), new Op("general_equips", 1, "StartEquipment"),
        new Op("general_pieces", 1, "StartTriforces"), new Op("general_damage", 1, "WeaponDamage"),
        new Op("general_options", 1, "Behaviors"), new Op("combat_difficulty", 3, "CombatDifficulty"),
        new Op("enemy_visibility", 3, "EnemyVisibility"), new Op("specials_equipment", 0, "EquipConfig"),
        new Op("specials_bubbles", 0, "BubbleConfig"), new Op("specials_likelikes", 0, "LikeLikeConfig"),
        new Op("specials_enemies", 0, "EnemyConfig"), new Op("specials_spriteswaps", 0, "SpriteSwapsOp"),
    };

    class Custom
    {
        public string Key, Type, AssetType; public int Pass;
        public Custom(string k, int p, string t, string a) { Key = k; Pass = p; Type = t; AssetType = a; }
    }

    // From Reloaded.UI.Zelda.App.Resources.Customizations.xml, in the GUI's order.
    static readonly Custom[] Customs =
    {
        new Custom("font", 1, "FontGraphics", "FontAsset"),
        new Custom("overworld", 2, "OverworldGraphics", "OverworldGfxAsset"),
        new Custom("dungeons", 2, "DungeonGraphics", "DungeonGfxAsset"),
        new Custom("link", 2, "LinkGraphics", "LinkAsset"),
        new Custom("npc", 2, "NPCGraphics", "NPCAsset"),
        new Custom("items", 1, "ItemGraphics", "ItemsAsset"),
        new Custom("enemies", 2, "EnemyGraphics", "EnemiesAsset"),
        new Custom("bosses", 2, "BossGraphics", "BossesAsset"),
        new Custom("ganon", 2, "GanonGraphics", "GanonAsset"),
    };

    static string PackagesDir => Path.Combine(ReloadedRootPaths.AppDataRoot, "packages", "zelda");

    // Dungeon generation recurses deeply, so give it more than the default 1 MB stack.
    static int Main(string[] args)
    {
        int rc = 1;
        var t = new Thread(() => rc = Run(args), 256 * 1024 * 1024);
        t.Start();
        t.Join();
        return rc;
    }

    static int Usage()
    {
        Console.Error.WriteLine(@"usage:
  zrcli generate --rom ZELDA.nes --out DIR [--settings FILE] [--seed SEED] [--name NAME]
                 [--prefs FILE] [--asset CATEGORY=FILE.asset ...] [-v]
  zrcli defaults FILE            write the GUI's default settings to FILE
  zrcli update-packages [--community]
                                 download the official (and optionally community) graphics packs
  zrcli list-assets [CATEGORY]   list downloaded graphics; categories: " + string.Join(", ", Customs.Select(c => c.Key)));
        return 2;
    }

    static int Run(string[] argv)
    {
        if (argv.Length == 0) return Usage();
        string cmd = argv[0];
        var a = ParseArgs(argv.Skip(1).ToArray(), out var positional, out var assets);
        try
        {
            switch (cmd)
            {
                case "generate": return Generate(a, assets);
                case "defaults":
                    if (positional.Count != 1) return Usage();
                    NewConfig().Persist().Save(positional[0]);
                    return 0;
                case "roundtrip":
                    // Load settings and save them again, to check nothing is lost.
                    if (positional.Count != 2) return Usage();
                    var rt = NewConfig();
                    LoadSettings(rt, positional[0]);
                    rt.Persist().Save(positional[1]);
                    Console.WriteLine($"config hash {rt.GetConfigHash()}");
                    return 0;
                case "update-packages": return UpdatePackages(a.ContainsKey("community"));
                case "list-assets": return ListAssets(positional.FirstOrDefault());
                default: return Usage();
            }
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"zrcli: {e.GetType().Name}: {e.Message}");
            if (a.ContainsKey("v")) Console.Error.WriteLine(e);
            return 1;
        }
    }

    // OperationsConfig.Restore, plus a fix for a bug in OverworldConfig.Restore
    // (1.0.98): it reads RecorderRulesPreset into UseBurnRulesPreset, so the
    // burn rules are overwritten and the recorder rules are never loaded. The GUI
    // only escapes it when the settings come from memory rather than a file.
    static void LoadSettings(OperationsConfig config, string path)
    {
        var xml = XElement.Load(path);
        config.Restore(xml);
        var gen = xml.Descendants("OverworldConfig").Elements("GenerationSettings").FirstOrDefault();
        if (gen == null || !config.ContainsKey("overworld_mode")) return;
        object ow = config["overworld_mode"];
        object settings = ow.GetType().GetProperty("DefinedGenerationSettings").GetValue(ow);
        if (settings == null) return;
        var t = settings.GetType();
        t.GetProperty("UseBurnRulesPreset").SetValue(settings, (string)gen.Attribute("BurnRulesPreset"));
        t.GetProperty("UseRecorderRulesPreset").SetValue(settings, (string)gen.Attribute("RecorderRulesPreset"));
    }

    static OperationsConfig NewConfig()
    {
        var config = new OperationsConfig();
        foreach (var op in Ops)
        {
            var t = Type.GetType($"Reloaded.Lib.Zelda.Operations.{op.Type}, Reloaded.Lib.Zelda.Operations", true);
            config[op.Key] = (IOperation)Activator.CreateInstance(t);
        }
        return config;
    }

    // Same subscriptions the GUI makes: official ("Partner") packs always,
    // community ("Verified") packs when the user opts in.
    static int UpdatePackages(bool community)
    {
        Directory.CreateDirectory(PackagesDir); // the GUI makes this at startup
        var updater = new PackageUpdater("zelda");
        updater.Subscribe(CreatorType.Partner);
        if (community) updater.Subscribe(CreatorType.Verified); else updater.Unsubscribe(CreatorType.Verified);
        updater.UpdatePackages();
        int n = Directory.Exists(PackagesDir) ? Directory.EnumerateFiles(PackagesDir, "*.asset", SearchOption.AllDirectories).Count() : 0;
        Console.WriteLine($"{n} assets in {PackagesDir}");
        return 0;
    }

    static int ListAssets(string category)
    {
        foreach (var c in Customs.Where(c => category == null || c.Key == category))
        {
            var type = Type.GetType($"MM.RomStudio.Modules.Zelda.AssetImpls.{c.AssetType}, MM.RomStudio.Modules.Zelda", true);
            foreach (var info in AssetInfoClient.GetAssetInfos(PackagesDir, type).OrderBy(i => i.AssetName))
                Console.WriteLine($"{c.Key}\t{info.AssetName}\t{info.AssetCategory}\t{info.GetCreditString()}\t{info.GetFilename()}");
        }
        return 0;
    }

    static int Generate(Dictionary<string, string> a, List<KeyValuePair<string, string>> assets)
    {
        if (!a.ContainsKey("rom") || !a.ContainsKey("out")) return Usage();
        var config = NewConfig();
        if (a.ContainsKey("settings")) LoadSettings(config, a["settings"]);

        var prefs = new UserPrefs();
        if (a.ContainsKey("prefs")) prefs.RestoreProperties(XElement.Load(a["prefs"]));

        // Graphics customizations, one asset per category, applied in the GUI's two passes.
        var pass1 = new List<ICustomization>();
        var pass2 = new List<ICustomization>();
        foreach (var c in Customs)
        {
            var files = assets.Where(kv => kv.Key == c.Key).Select(kv => kv.Value).ToList();
            if (files.Count == 0) continue;
            var t = Type.GetType($"Reloaded.Lib.Zelda.Customizations.{c.Type}, Reloaded.Lib.Zelda.Customizations", true);
            var custom = (ICustomization)Activator.CreateInstance(t);
            var sel = (SelectedAssets)t.GetProperty("SelectedAssets").GetValue(custom);
            sel.UseFavorites = false;
            sel.AssetList.AddRange(files);
            (c.Pass == 1 ? pass1 : pass2).Add(custom);
        }
        foreach (var kv in assets.Where(kv => !Customs.Any(c => c.Key == kv.Key)))
            throw new ArgumentException($"unknown asset category '{kv.Key}'");

        string seed = a.ContainsKey("seed") ? a["seed"].ToUpperInvariant() : NewSeed();
        uint cfgHash = config.GetConfigHash();
        var host = new Host { Verbose = a.ContainsKey("v") };
        if (host.Verbose)
        {
            byte[] hb = Util.CreateHashBytes(VersionStr, cfgHash.ToString(), seed);
            Console.Error.WriteLine($"seed {seed}, config hash {cfgHash}, sanity hash {hb[0]:X2}{hb[1]:X2}{hb[2]:X2}");
        }
        string seedFolder = Path.Combine(a["out"], seed);
        string romName = (a.ContainsKey("name") ? a["name"] : "Legend of Zelda [reloaded] " + seed) + ".nes";

        // The GUI retries with a new salt up to 20 times when a seed fails validation.
        for (int salt = 0; salt < 20; salt++)
        {
            try
            {
                var gen = new Generator { CustomizationsPass1 = pass1, CustomizationsPass2 = pass2, UserPrefs = prefs };
                RNG rng = Util.CreateSeededRng(VersionStr, cfgHash, seed, salt);
                var ops = new List<IOperation>();
                foreach (var g in Ops.GroupBy(o => o.Group).OrderBy(g => g.Key))
                    ops.AddRange(g.Select(o => config[o.Key]).OrderByDescending(o => o.GetPriority() + rng.GetRandomInt(10)));
                gen.Operations = ops;
                var state = new ReloadedState { SeedFolder = seedFolder, VersionString = VersionStr };
                state.Load(a["rom"]);
                gen.Generate(rng, host, state);
                if (!SeedValidator.Validate(state))
                {
                    Console.Error.WriteLine($"salt {salt}: seed failed validation, retrying");
                    continue;
                }
                byte[] h = Util.CreateHashBytes(VersionStr, cfgHash.ToString(), seed);
                string hash = $"{h[0]:X2}{h[1]:X2}{h[2]:X2}";
                Directory.CreateDirectory(seedFolder);
                state.Save(Path.Combine(seedFolder, romName), hash);
                config.Persist().Save(Path.Combine(seedFolder, "settings.xml"));
                File.WriteAllLines(Path.Combine(seedFolder, "seedinfo.txt"), new[] {
                    "Version: " + VersionStr, "Flagset Code: (not available)", "Seed: " + seed, "Hash: " + hash });
                Console.WriteLine($"{seed}\t{hash}\t{Path.Combine(seedFolder, romName)}");
                return 0;
            }
            catch (Exception e)
            {
                Console.Error.WriteLine($"salt {salt}: {e.GetType().Name}: {e.Message}");
                if (host.Verbose) Console.Error.WriteLine(e);
            }
        }
        Console.Error.WriteLine("zrcli: generation failed after 20 attempts");
        return 1;
    }

    static string NewSeed()
    {
        var r = new Random();
        return new string(Enumerable.Range(0, r.Next(6, 13)).Select(_ => SeedChars[r.Next(SeedChars.Length)]).ToArray());
    }

    // --key value, --flag, bare positionals; --asset may repeat as CATEGORY=FILE.
    static Dictionary<string, string> ParseArgs(string[] args, out List<string> positional, out List<KeyValuePair<string, string>> assets)
    {
        var d = new Dictionary<string, string>();
        positional = new List<string>();
        assets = new List<KeyValuePair<string, string>>();
        for (int i = 0; i < args.Length; i++)
        {
            if (!args[i].StartsWith("-")) { positional.Add(args[i]); continue; }
            string k = args[i].TrimStart('-');
            string v = (i + 1 < args.Length && !args[i + 1].StartsWith("-")) ? args[++i] : "";
            if (k == "asset")
            {
                int eq = v.IndexOf('=');
                if (eq < 1) throw new ArgumentException("--asset needs CATEGORY=FILE");
                assets.Add(new KeyValuePair<string, string>(v.Substring(0, eq), v.Substring(eq + 1)));
            }
            else d[k] = v;
        }
        return d;
    }
}
