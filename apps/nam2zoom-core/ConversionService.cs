using System.Globalization;
using System.Text.Json;

namespace Nam2ZoomDesktop;

public sealed record ConversionResult(IReadOnlyList<string> Files, int Declined);

/// <summary>Retrain individual NAM files without building effects or contacting devices.</summary>
public sealed class ConversionService(AppPaths paths, IConversionBackend backend)
{
    public const string Profile = "lite";
    public const string LoaderUrl = "https://sym.bios.is/?open=nam";
    public const string SharingText = "These Zoom-ready NAM files use A2 Lite at 44.1 kHz. "
        + "You can share them with other users without retraining again. "
        + "Share models you have permission to redistribute. "
        + "To load a NAM file onto a compatible Zoom pedal, use " + LoaderUrl + ". "
        + "sym.bios.is is for loading files onto pedals; it does not host or share retrained NAM models.";

    public async Task InspectAsync(ModelSelection model, CancellationToken token = default)
    {
        var result = await backend.RunAsync(["inspect-hybrid", model.Path, "--profile", Profile], token: token);
        result.RequireSuccess();
        using var document = JsonDocument.Parse(result.Output);
        var info = document.RootElement;
        var status = info.GetProperty("status").GetString();
        if (status is not ("direct" or "adaptable"))
            throw new InvalidDataException($"{Path.GetFileName(model.Path)}: "
                + (info.TryGetProperty("reason", out var reason) ? reason.GetString() : "Unsupported NAM file."));
        model.Status = status;
        model.SampleRate = info.GetProperty("sample_rate").GetInt32();
        model.ModelProfile = Profile;
    }

    public async Task<ConversionResult> ConvertAsync(IReadOnlyList<ModelSelection> models, string applicationDirectory,
        int epochs, Func<string, string, Task<bool>> review, Action<string> report, CancellationToken token)
    {
        if (models.Count == 0) throw new InvalidDataException("Add at least one NAM file to retrain.");
        if (epochs is < 1 or > 300) throw new ArgumentOutOfRangeException(nameof(epochs));
        if (models.Any(m => m.IrPath is not null))
            throw new InvalidDataException("This retraining queue does not support cabinet IR changes. Add the original NAM file.");

        var directory = Path.Combine(applicationDirectory, "Converted_NAM");
        // Check access before starting potentially lengthy training. Never silently relocate exports.
        Directory.CreateDirectory(directory);
        var probe = Path.Combine(directory, ".write-check-" + Guid.NewGuid().ToString("N"));
        using (new FileStream(probe, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1, FileOptions.DeleteOnClose)) { }

        var exported = new List<string>();
        var declined = 0;
        foreach (var model in models) {
            token.ThrowIfCancellationRequested();
            await InspectAsync(model, token);
            var ready = model.Path;
            if (model.Status != "direct") {
                report("Retraining " + Path.GetFileName(model.Path) + " to A2 Lite at 44.1 kHz…");
                var adapted = await backend.RunAsync(["adapt", model.Path, "--training-di", paths.TrainingDi(),
                    "--cache", paths.Cache, "--epochs", epochs.ToString(CultureInfo.InvariantCulture),
                    "--profile", Profile, "--review-quality"], true, report, token);
                adapted.RequireSuccess();
                ready = Marker(adapted.Output, "READY_MODEL=");
                using var quality = JsonDocument.Parse(Marker(adapted.Output, "QUALITY_RESULT="));
                var warning = ConversionQuality.ReviewLine(model.Path, Path.GetFileNameWithoutExtension(model.Path), quality.RootElement);
                if (warning is not null) {
                    var preview = Marker(adapted.Output, "PREVIEW_DIR=");
                    if (!Directory.Exists(preview)) throw new InvalidDataException("Conversion preview folder missing.");
                    if (!await review(warning, preview)) {
                        declined++;
                        model.Status = "declined";
                        report("Conversion declined; cached model and previews retained: " + model.Path);
                        continue;
                    }
                }
                // Validate the returned file against the Zoom-ready architecture before exporting.
                var candidate = new ModelSelection { Path = ready };
                await InspectAsync(candidate, token);
                if (candidate.Status != "direct") throw new InvalidDataException("Conversion did not produce a Zoom-ready A2 Lite 44.1 kHz NAM.");
            }
            token.ThrowIfCancellationRequested();
            var destination = ConvertedNam.Save(ready, model.Path, applicationDirectory);
            exported.Add(destination);
            model.Status = "exported";
            report("Zoom-ready NAM saved: " + destination);
        }
        if (exported.Count > 0)
            File.WriteAllText(Path.Combine(directory, "README.txt"), SharingText + Environment.NewLine);
        return new(exported, declined);
    }

    private static string Marker(string output, string prefix) => output.Split('\n').Select(l => l.Trim())
        .LastOrDefault(l => l.StartsWith(prefix, StringComparison.Ordinal))?[prefix.Length..]
        ?? throw new InvalidDataException("Backend result missing: " + prefix);
}
