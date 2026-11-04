using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.RegularExpressions;

namespace Nam2ZoomDesktop;

public sealed class RetrainingItem(ModelSelection model) : INotifyPropertyChanged
{
    public ModelSelection Model { get; } = model;
    public string Name => Path.GetFileName(Model.Path);
    public string InputRate => $"{Model.SampleRate / 1000.0:0.#} kHz";
    private int number;
    public int Number { get => number; set { number = value; Changed(); } }
    private bool selected = true;
    public bool IsSelected { get => selected; set { selected = value; Changed(); } }
    private double progress;
    public double Progress { get => progress; set { progress = Math.Clamp(value, 0, 100); Changed(); Changed(nameof(ProgressText)); } }
    public string ProgressText => $"{Progress:0}%";
    private string state = "Queued";
    public string State { get => state; set { state = value; Changed(); Changed(nameof(IsRunning)); Changed(nameof(CanCancel)); } }
    public bool IsRunning => State is "Preparing" or "Retraining…" or "Checking quality";
    public bool CanCancel => IsRunning || State == "Queued";
    public string? OutputPath { get; set; }
    public string? PreviewPath { get; set; }
    public string? Error { get; set; }
    public event PropertyChangedEventHandler? PropertyChanged;
    private void Changed([CallerMemberName] string? name = null) => PropertyChanged?.Invoke(this, new(name));
}

public static class TrainingProgress
{
    public static double? Parse(string line, int epochs)
    {
        if (epochs <= 0) return null;
        var completed = Regex.Match(line, @"\bEpoch\s+(\d+)/(\d+)", RegexOptions.IgnoreCase);
        if (completed.Success && int.TryParse(completed.Groups[1].Value, out var count)
            && int.TryParse(completed.Groups[2].Value, out var total) && total > 0)
            return Math.Clamp(100.0 * count / total, 0, 99);
        var batch = Regex.Match(line, @"\bEpoch\s+(\d+):\s*(\d+)%", RegexOptions.IgnoreCase);
        if (batch.Success && int.TryParse(batch.Groups[1].Value, out var epoch)
            && int.TryParse(batch.Groups[2].Value, out var percent) && percent <= 100)
            return Math.Clamp(100.0 * (epoch + percent / 100.0) / epochs, 0, 99);
        return null;
    }
}

public sealed record QueueResult(int Exported, int Declined, int Cancelled, int Failed);

/// <summary>A sequential queue with independent item cancellation and retained completed exports.</summary>
public sealed class RetrainingQueue(ConversionService conversions)
{
    private CancellationTokenSource? currentCancellation;
    public RetrainingItem? Current { get; private set; }
    public void Cancel(RetrainingItem item)
    {
        if (ReferenceEquals(item, Current)) currentCancellation?.Cancel();
        else { item.State = "Cancelled"; item.IsSelected = false; }
    }

    public async Task<QueueResult> RunAsync(IReadOnlyList<RetrainingItem> items, string applicationDirectory,
        int epochs, Func<string, string, Task<bool>> review, Action<RetrainingItem, string> report,
        CancellationToken token)
    {
        var selected = items.Where(i => i.IsSelected).ToArray();
        if (selected.Length == 0) throw new InvalidDataException("Select at least one NAM file to retrain.");
        foreach (var item in selected) { item.State = "Queued"; item.Progress = 0; item.Error = null; }
        var exported = 0; var declined = 0; var cancelled = 0; var failed = 0;
        foreach (var item in selected) {
            if (token.IsCancellationRequested) { item.State = "Cancelled"; cancelled++; continue; }
            if (!item.IsSelected || item.State == "Cancelled") { cancelled++; continue; }
            Current = item;
            using var itemCancellation = CancellationTokenSource.CreateLinkedTokenSource(token);
            currentCancellation = itemCancellation;
            item.State = "Preparing";
            try {
                report(item, "Starting " + item.Name);
                var result = await conversions.ConvertAsync([item.Model], applicationDirectory, epochs,
                    async (warning, preview) => {
                        item.PreviewPath = preview; item.State = "Checking quality";
                        return await review(warning, preview);
                    }, line => {
                        if (line.StartsWith("PREVIEW_DIR=", StringComparison.Ordinal)) item.PreviewPath = line[12..].Trim();
                        report(item, line);
                    }, itemCancellation.Token);
                if (result.Files.Count > 0) {
                    item.OutputPath = result.Files[0]; item.Progress = 100; item.State = "Exported"; exported++;
                } else { item.State = "Declined"; declined++; }
            }
            catch (OperationCanceledException) when (itemCancellation.IsCancellationRequested) {
                item.State = "Cancelled"; cancelled++;
                report(item, "Cancelled " + item.Name + "; completed exports and cache retained.");
            }
            catch (Exception ex) {
                item.State = "Failed"; item.Error = ex.Message; failed++;
                report(item, "Failed " + item.Name + ": " + ex.Message);
            }
            finally { currentCancellation = null; Current = null; }
        }
        return new(exported, declined, cancelled, failed);
    }
}
