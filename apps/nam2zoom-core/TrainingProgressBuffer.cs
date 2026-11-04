namespace Nam2ZoomDesktop;

/// <summary>Coalesce trainer output for timer-driven UI updates without dispatching per line.</summary>
public sealed class TrainingProgressBuffer
{
    private readonly object gate = new();
    private TrainingUpdate? pending;
    public void Report(RetrainingItem item, string line, int epochs)
    {
        var percent = TrainingProgress.Parse(line, epochs);
        var state = line.StartsWith("Retraining ", StringComparison.Ordinal) ? "Retraining…"
            : line.StartsWith("Held-out ESR", StringComparison.Ordinal) ? "Checking quality" : null;
        if (percent is null && state is null) return;
        lock (gate) {
            var previous = ReferenceEquals(pending?.Item, item) ? pending : null;
            pending = new(item, state ?? previous?.State,
                Math.Max(percent ?? 0, previous?.Progress ?? 0));
        }
    }
    public TrainingUpdate? TakeUpdate()
    {
        lock (gate) { var update = pending; pending = null; return update; }
    }
}
public sealed record TrainingUpdate(RetrainingItem Item, string? State, double Progress);
