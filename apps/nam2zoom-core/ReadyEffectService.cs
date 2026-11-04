using System.Security.Cryptography;
using System.Text.Json;

namespace Nam2ZoomDesktop;

/// <summary>Packages already-retrained Lite models, then uses the existing guarded deployment CLI.</summary>
public sealed class ReadyEffectService(AppPaths paths, IConversionBackend backend)
{
    public const string Profile = "lite";
    public const int MaximumModels = 5;

    public async Task<BankResult> BuildAsync(IReadOnlyList<ModelSelection> models, string parent,
        Action<string> report, CancellationToken token, bool compactEffect = false,
        int effectSlot = 1, string? effectName = null, bool nameArtwork = true)
    {
        var named = effectName is not null;
        var slot = EffectSlot.Get(effectSlot);
        effectName ??= slot.DefaultName;
        if (!System.Text.RegularExpressions.Regex.IsMatch(effectName, "^[A-Za-z0-9 _-]{1,8}$") || effectName != effectName.Trim())
            throw new InvalidDataException("Use an effect name of 1–8 letters, digits, spaces, - or _, without surrounding spaces.");
        BankService.Validate(models, Profile);
        if (models.Any(m => !System.Text.RegularExpressions.Regex.IsMatch(m.Label, "^[A-Za-z0-9_-]{1,6}$")))
            throw new InvalidDataException("Use unique 1–6 character model labels containing letters, numbers, underscores or hyphens.");
        foreach (var model in models) {
            token.ThrowIfCancellationRequested();
            var result = await backend.RunAsync(["inspect-hybrid", model.Path, "--profile", Profile], token: token);
            result.RequireSuccess();
            using var document = JsonDocument.Parse(result.Output);
            if (document.RootElement.GetProperty("status").GetString() != "direct")
                throw new InvalidDataException($"{Path.GetFileName(model.Path)} is not a retrained A2 Lite 44.1 kHz NAM. Retrain it on the Retrain page first.");
            if (model.IrPath is not null) throw new InvalidDataException("Build effect accepts retrained NAMs without additional IR processing.");
        }
        var workspace = BuildWorkspace.Create(parent);
        var args = new List<string> { "build-ready-effect" };
        args.AddRange(models.Select(m => m.Path));
        foreach (var model in models) args.AddRange(["--label", model.Label]);
        args.AddRange(["--output", workspace.Output, "--profile", Profile]);
        args.AddRange(["--effect-slot", effectSlot.ToString()]);
        if (named) args.AddRange(["--effect-name", effectName]);
        if (!nameArtwork) args.Add("--no-name-artwork");
        if (compactEffect) args.Add("--compact-effect");
        (await backend.RunAsync(args, report: report, token: token)).RequireSuccess();
        return Load(Path.Combine(workspace.Output, "build", slot.Filename));
    }

    public static BankResult Load(string effect)
    {
        effect = Path.GetFullPath(effect);
        var slot = EffectSlot.All.FirstOrDefault(s => string.Equals(Path.GetFileName(effect), s.Filename, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException("Choose a nam2zoom slot's ZD2 file.");
        var icon = Path.ChangeExtension(effect, ".ZIC");
        if (!File.Exists(effect) || !File.Exists(icon)) throw new FileNotFoundException("The built ZD2 and companion ZIC must be present together.");
        var raw = File.ReadAllBytes(effect);
        if (raw.Length < 111 || !raw.AsSpan(0,4).SequenceEqual("ZDLF"u8)
            || System.Buffers.Binary.BinaryPrimitives.ReadUInt32LittleEndian(raw.AsSpan(96,4)) != slot.Id)
            throw new InvalidDataException("Effect ID and slot filename do not match.");
        return new(Path.GetDirectoryName(effect)!, effect, icon, Hash(effect), Hash(icon), null);
    }

    public static EffectSlot SlotFor(BankResult bank) => EffectSlot.All.Single(s =>
        string.Equals(s.Filename, Path.GetFileName(bank.Effect), StringComparison.OrdinalIgnoreCase));

    public static string NameFor(BankResult bank) => System.Text.Encoding.ASCII.GetString(File.ReadAllBytes(bank.Effect), 100, 11).TrimEnd('\0');

    public async Task InstallAsync(BankResult bank, bool fullBackup, Action<string> report)
    {
        if (Hash(bank.Effect) != bank.EffectHash || Hash(bank.Icon) != bank.IconHash)
            throw new InvalidDataException("The built effect changed. Rebuild or load it again before approving installation.");
        var args = new List<string> { "install-bank", bank.Effect, "--session", Session(fullBackup),
            "--approved-zd2-sha256", bank.EffectHash, "--approved-zic-sha256", bank.IconHash, "--ack-risk" };
        if (!fullBackup) args.Add("--no-backup");
        // Deliberately non-cancellable: the underlying file transfer must finish safely.
        (await backend.RunAsync(args, report: report)).RequireSuccess();
    }

    public async Task UninstallAsync(bool fullBackup, Action<string> report, int effectSlot = 1)
    {
        var slot = EffectSlot.Get(effectSlot);
        var args = new List<string> { "uninstall-bank", "--effect-slot", slot.Number.ToString(), "--session", Session(fullBackup), "--ack-risk" };
        if (!fullBackup) args.Add("--no-backup");
        (await backend.RunAsync(args, report: report)).RequireSuccess();
    }

    private string Session(bool backup) => Path.Combine(backup ? paths.Backup : Path.Combine(paths.Data, "sessions"),
        DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + "-" + Guid.NewGuid().ToString("N")[..8]);
    private static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)));
}
