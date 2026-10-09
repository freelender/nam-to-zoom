using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.ComponentModel;

namespace Nam2ZoomDesktop;

public sealed class ModelSelection : INotifyPropertyChanged
{
    public string Path { get; set; } = "";
    private string label = "";
    public string Label {
        get => label;
        set {
            if (label == value) return;
            label = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Label)));
        }
    }
    public event PropertyChangedEventHandler? PropertyChanged;
    public string? IrPath { get; set; }
    public string ModelProfile { get; set; } = "compact";
    public string Status { get; set; } = "Checking";
    public int SampleRate { get; set; }
    public override string ToString() => $"{Label,-5}  {System.IO.Path.GetFileName(Path)}  • {Status} • {SampleRate} Hz" + (IrPath is null ? "" : " + Cab IR");
}

public sealed record BankResult(string Directory, string Effect, string Icon, string EffectHash, string IconHash, string? Preview);

public sealed class BankService(AppPaths paths, BackendService backend)
{
    public async Task InspectAsync(ModelSelection model, string profile, CancellationToken token = default)
    {
        var result = await backend.RunAsync(["inspect-hybrid", model.Path, "--profile", profile], token: token);
        result.RequireSuccess();
        using var document = JsonDocument.Parse(result.Output);
        model.Status = document.RootElement.GetProperty("status").GetString()!;
        model.SampleRate = document.RootElement.GetProperty("sample_rate").GetInt32();
        model.ModelProfile = profile;
    }

    public static int MaxModels(string profile) => profile switch {
        "compact" => 10, "lite" => 3,
        _ => throw new InvalidDataException("Unknown bank profile.")
    };

    public static void Validate(IReadOnlyList<ModelSelection> models, string? profile = null)
    {
        var selectedProfile = profile ?? models.FirstOrDefault()?.ModelProfile ?? "compact";
        var maximum = MaxModels(selectedProfile);
        if (models.Count < 1 || models.Count > maximum)
            throw new InvalidDataException($"{selectedProfile} banks require 1–{maximum} NAM models.");
        if (models.Any(m => !Regex.IsMatch(m.Label, "^[A-Za-z0-9_-]{1,5}$"))
            || models.Select(m => m.Label.ToUpperInvariant()).Distinct().Count() != models.Count)
            throw new InvalidDataException("Use unique 1–5 character labels (A–Z, 0–9, - or _).");
    }

    public async Task<BankResult?> BuildAsync(IReadOnlyList<ModelSelection> models, string parent,
        string profile, int epochs, Func<string, string?, Task<bool>> review,
        Action<string> report, CancellationToken token)
    {
        Validate(models, profile);
        var workspace = BuildWorkspace.Create(parent);
        var resolved = new List<string>();
        var previews = new List<(string, string)>();
        var exports = new List<(string, string)>();
        var warnings = new List<string>();
        foreach (var model in models) {
            await InspectAsync(model, profile, token);
            if (model.Status == "unsupported") throw new InvalidDataException($"Unsupported NAM: {model.Path}");
            if (model.Status == "direct" && model.IrPath is null) { resolved.Add(model.Path); continue; }
            var args = new List<string> { "adapt", model.Path, "--training-di", paths.TrainingDi(),
                "--cache", paths.Cache, "--epochs", epochs.ToString(System.Globalization.CultureInfo.InvariantCulture),
                "--profile", profile, "--review-quality" };
            if (model.IrPath is not null) args.AddRange(["--ir", model.IrPath]);
            var adapted = await backend.RunAsync(args, true, report, token);
            adapted.RequireSuccess();
            var ready = Marker(adapted.Output, "READY_MODEL=");
            var preview = Marker(adapted.Output, "PREVIEW_DIR=");
            if (!File.Exists(ready) || !System.IO.Directory.Exists(preview))
                throw new InvalidDataException("Conversion model or A/B preview missing.");
            using var quality = JsonDocument.Parse(Marker(adapted.Output, "QUALITY_RESULT="));
            var warning = ConversionQuality.ReviewLine(model.Path, model.Label, quality.RootElement);
            if (warning is not null) warnings.Add(warning);
            if (quality.RootElement.TryGetProperty("ir_gain_db", out var gain) && gain.GetDouble() < -0.1)
                report($"{model.Label}: IR target attenuated {gain.GetDouble():0.00} dB to avoid clipping; audition the lower level.");
            previews.Add((model.Label, preview));
            exports.Add((ready, model.Path));
            resolved.Add(ready);
        }
        token.ThrowIfCancellationRequested();
        var staged = workspace.StagePreviews(previews);
        if (warnings.Count > 0 && !await review(string.Join("\n", warnings), staged)) {
            report("Conversions declined. Cached models and A/B previews retained; no effect built.");
            return null;
        }
        token.ThrowIfCancellationRequested();
        foreach (var (student, original) in exports)
            report("Converted NAM saved: " + ConvertedNam.Save(student, original, paths.Data, profile));
        var buildArgs = new List<string> { "build-bank" };
        buildArgs.AddRange(resolved);
        foreach (var model in models) buildArgs.AddRange(["--label", model.Label]);
        buildArgs.AddRange(["--output", workspace.Output, "--profile", profile]);
        (await backend.RunAsync(buildArgs, report: report, token: token)).RequireSuccess();
        token.ThrowIfCancellationRequested();
        var effect = System.IO.Path.Combine(workspace.Output, "build", "N2ZBANK.ZD2");
        var icon = System.IO.Path.ChangeExtension(effect, ".ZIC");
        return new(workspace.Output, effect, icon, Hash(effect), Hash(icon), workspace.CompletePreviews());
    }

    public async Task InstallAsync(BankResult result, bool backup, Action<string> report)
    {
        var args = new List<string> { "install-bank", result.Effect, "--session", Session(backup),
            "--approved-zd2-sha256", result.EffectHash, "--approved-zic-sha256", result.IconHash, "--ack-risk" };
        if (!backup) args.Add("--no-backup");
        (await backend.RunAsync(args, report: report)).RequireSuccess();
    }

    public async Task UninstallAsync(bool backup, Action<string> report)
    {
        var args = new List<string> { "uninstall-bank", "--session", Session(backup), "--ack-risk" };
        if (!backup) args.Add("--no-backup");
        (await backend.RunAsync(args, report: report)).RequireSuccess();
    }

    private string Session(bool backup) => System.IO.Path.Combine(backup ? paths.Backup : System.IO.Path.Combine(paths.Data, "sessions"),
        DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + "-" + Guid.NewGuid().ToString("N")[..8]);
    private static string Hash(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)));
    private static string Marker(string output, string prefix) => output.Split('\n').Select(l => l.Trim())
        .LastOrDefault(l => l.StartsWith(prefix, StringComparison.Ordinal))?[prefix.Length..]
        ?? throw new InvalidDataException("Backend result missing: " + prefix);
}
