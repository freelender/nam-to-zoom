using System.Text.Json;
using Nam2ZoomDesktop;

var root = Path.Combine(Path.GetTempPath(), "nam2zoom-retraining-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try {
    var application = Path.Combine(root, "portable app");
    Directory.CreateDirectory(application);
    var paths = new AppPaths(root, Path.Combine(root, "private data"));
    var fake = new FakeBackend(root);
    var service = new ConversionService(paths, fake);
    var models = Enumerable.Range(1, 5).Select(n => {
        var path = Path.Combine(root, "capture " + n + ".nam"); File.WriteAllText(path, "original " + n);
        return new ModelSelection { Path = path };
    }).ToArray();
    var result = await service.ConvertAsync(models, application, 100, (_, _) => Task.FromResult(true), _ => {}, default);
    if (result.Files.Count != 5 || result.Files.Any(f => Path.GetDirectoryName(f) != Path.Combine(application, "Converted_NAM")))
        throw new Exception("Queue must export individual NAMs beside the app without a bank-size limit or Lite subfolder.");
    if (fake.Adaptations != 5 || !File.ReadAllText(Path.Combine(application, "Converted_NAM", "README.txt")).Contains(ConversionService.LoaderUrl))
        throw new Exception("Retraining or sharing instructions missing.");
    if (models.Any(m => !File.ReadAllText(m.Path).StartsWith("original"))) throw new Exception("Source overwritten.");

    fake.Direct = true;
    var repeated = await service.ConvertAsync([new ModelSelection { Path = result.Files[0] }], application, 100,
        (_, _) => throw new Exception("Ready NAM must not request quality approval."), _ => {}, default);
    if (repeated.Files[0] != result.Files[0] || fake.Adaptations != 5) throw new Exception("Ready NAM must be reused without retraining.");

    fake.Direct = false; fake.PoorQuality = true;
    var declined = await service.ConvertAsync([models[0]], application, 100, (_, _) => Task.FromResult(false), _ => {}, default);
    if (declined.Files.Count != 0 || declined.Declined != 1) throw new Exception("Declined conversion exported.");

    fake.PoorQuality = false; fake.InvalidStudent = true;
    try {
        await service.ConvertAsync([models[0]], application, 100, (_, _) => Task.FromResult(true), _ => {}, default);
        throw new Exception("Invalid student exported.");
    } catch (InvalidDataException) { }

    using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
    try {
        await service.ConvertAsync([models[0]], application, 100, (_, _) => Task.FromResult(true), _ => {}, cancelled.Token);
        throw new Exception("Cancelled queue continued.");
    } catch (OperationCanceledException) { }

    fake.InvalidStudent = false;
    var runner = new RetrainingQueue(service);
    var jobs = models.Take(3).Select(m => new RetrainingItem(m)).ToArray();
    jobs[2].IsSelected = false;
    var batch = await runner.RunAsync(jobs, application, 100, (_, _) => Task.FromResult(true),
        (item, line) => { if (ReferenceEquals(item, jobs[0]) && line.StartsWith("Epoch")) runner.Cancel(item); }, default);
    if (batch.Cancelled != 1 || batch.Exported != 1 || jobs[0].State != "Cancelled" || jobs[1].Progress != 100 || jobs[2].State != "Queued")
        throw new Exception("Per-file cancellation must continue the queue and skip unselected items.");
    using var stopAll = new CancellationTokenSource();
    jobs = models.Take(3).Select(m => new RetrainingItem(m)).ToArray();
    batch = await runner.RunAsync(jobs, application, 100, (_, _) => Task.FromResult(true),
        (_, line) => { if (line.StartsWith("Epoch")) stopAll.Cancel(); }, stopAll.Token);
    if (batch.Cancelled != 3 || jobs.Any(i => i.State != "Cancelled")) throw new Exception("Cancel all must stop pending jobs.");
    fake.FailNext = true;
    jobs = models.Take(2).Select(m => new RetrainingItem(m)).ToArray();
    batch = await runner.RunAsync(jobs, application, 100, (_, _) => Task.FromResult(true), (_, _) => {}, default);
    if (batch.Failed != 1 || batch.Exported != 1 || jobs[0].Error is null) throw new Exception("One failed file must not discard the rest of the queue.");
    if (TrainingProgress.Parse("Epoch 2: 50%|#####|", 10) != 25
        || TrainingProgress.Parse("Epoch 20/100 — loss: 0.123", 100) != 20
        || TrainingProgress.Parse("Epoch 9: 100%", 10) != 99
        || TrainingProgress.Parse("Downloading 50%", 100) is not null)
        throw new Exception("Progress must track training epochs and leave completion for export verification.");
    var updates = new TrainingProgressBuffer();
    var progressItem = jobs[0];
    await Task.Run(() => {
        updates.Report(progressItem, "Retraining capture", 100);
        for (var n = 0; n < 20000; n++) updates.Report(progressItem, $"Epoch {n % 100}/100", 100);
        updates.Report(progressItem, "Held-out ESR: 0.01", 100);
    });
    var latest = updates.TakeUpdate();
    if (latest?.Item != progressItem || latest.Progress != 99 || latest.State != "Checking quality" || updates.TakeUpdate() is not null)
        throw new Exception("Verbose progress must coalesce into one UI update, retaining latest state and highest progress.");
    var nextItem = jobs[1]; updates.Report(nextItem, "Epoch 1/100", 100);
    if (updates.TakeUpdate()?.Progress != 1) throw new Exception("Progress leaked between queue items.");
    var displayLog = Path.Combine(root, "display-log.txt");
    await using (var buffered = new BufferedActivityLog(displayLog)) {
        buffered.Report("before clear"); buffered.ClearDisplay(); buffered.Report("after clear");
        if (buffered.TakeUpdate()?.Text != "after clear" + Environment.NewLine) throw new Exception("Clear log must clear the visible tail.");
    }
    if (!File.ReadAllText(displayLog).Contains("before clear")) throw new Exception("Clear display must preserve the full log on disk.");

    var mac = Path.Combine(root, "mac", "nam2zoom.app", "Contents", "MacOS");
    if (ConvertedNam.ApplicationDirectory(mac) != Path.Combine(root, "mac")) throw new Exception("Exports must be beside the macOS bundle.");
    if (ConvertedNam.ApplicationDirectory(application) != application) throw new Exception("Windows export base incorrect.");
    Console.WriteLine("Retraining queue, Lite-only output, no device/build calls, quality approval, cancellation, source preservation and Windows/macOS export paths: PASS");
} finally { Directory.Delete(root, recursive: true); }

sealed class FakeBackend(string root) : IConversionBackend
{
    public int Adaptations;
    public bool Direct, PoorQuality, InvalidStudent, FailNext;
    private string Student => Path.Combine(root, "student.nam");
    public Task<ProcessResult> RunAsync(IEnumerable<string> arguments, bool training = false, Action<string>? report = null, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        var args = arguments.ToArray();
        if (args[Array.IndexOf(args, "--profile") + 1] != "lite") throw new Exception("Conversion must always target Lite.");
        if (args[0] == "inspect-hybrid") {
            var ready = Direct || (args[1] == Student && !InvalidStudent);
            return Task.FromResult(new ProcessResult(0, JsonSerializer.Serialize(new { status = ready ? "direct" : "adaptable", sample_rate = ready ? 44100 : 48000 })));
        }
        if (args[0] != "adapt" || !training || !args.Contains("--review-quality"))
            throw new Exception("Unexpected effect/device command or missing training/quality gate.");
        Adaptations++;
        report?.Invoke("Epoch 0: 50%|#####|");
        token.ThrowIfCancellationRequested();
        if (FailNext) { FailNext = false; return Task.FromResult(new ProcessResult(1, "test failure")); }
        File.WriteAllText(Student, "Zoom-ready converted weights");
        var preview = Path.Combine(root, "preview"); Directory.CreateDirectory(preview);
        return Task.FromResult(new ProcessResult(0, $"READY_MODEL={Student}\nPREVIEW_DIR={preview}\nQUALITY_RESULT="
            + JsonSerializer.Serialize(new { esr = PoorQuality ? .2 : .01, max_esr = .05, correlation = .99 })));
    }
}
