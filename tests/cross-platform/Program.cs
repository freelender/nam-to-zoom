using Nam2ZoomDesktop;
using System.Diagnostics;

// Optional maintainer integration check: downloads CUDA into an isolated data
// directory and exercises the same setup service used by the desktop dialog.
if (args.FirstOrDefault() is "--setup-cuda" or "--verify-cuda") {
    var setupPaths = new AppPaths(args[1], args[2]);
    var setupBackend = new BackendService(setupPaths);
    var setupRuntime = new TrainingRuntime(setupPaths, setupBackend);
    if (args[0] == "--setup-cuda") await setupRuntime.SelectAsync(true, Console.WriteLine, default);
    await setupRuntime.VerifyAsync(Console.WriteLine, default);
    if (args[0] == "--verify-cuda") {
        Console.WriteLine("Portable CUDA relocation verification: PASS");
        return 0;
    }
    var probe = await setupBackend.ExecuteAsync(setupPaths.DefaultTrainer,
        ["-c", "import torch; assert torch.version.cuda is None; print('Bundled CPU runtime preserved')"], Console.WriteLine);
    probe.RequireSuccess();
    Console.WriteLine("Portable CUDA setup and verification: PASS");
    return 0;
}

if (args.FirstOrDefault() == "--child") {
    Console.OutputEncoding = System.Text.Encoding.UTF8;
    Console.WriteLine(args[1]);
    for (var n = 0; n < 3000; n++) { Console.WriteLine("stdout " + n); Console.Error.WriteLine("stderr " + n); }
    return 7;
}
if (args.FirstOrDefault() == "--wait") { await Task.Delay(30000); return 0; }
if (args.FirstOrDefault() == "--spawn-worker") {
    await Task.Delay(250); // Give the backend time to attach the launcher to its job.
    using var child = Process.Start(new ProcessStartInfo(Environment.ProcessPath!) {
        UseShellExecute = false, ArgumentList = { "--wait" }
    })!;
    Console.WriteLine("WORKER=" + child.Id);
    if (args[1] == "exit") return 0;
    await Task.Delay(30000); return 0;
}
var temporary = Path.Combine(Path.GetTempPath(), "nam2zoom shared smoke " + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(temporary);
try {
    var paths = new AppPaths(Path.Combine(temporary, "read-only resources"), Path.Combine(temporary, "user data"));
    var di = paths.TrainingDi();
    if (!File.Exists(di) || !di.StartsWith(paths.Data)) throw new Exception("Training resource escaped writable data");
    var backend = new BackendService(paths);
    if (OperatingSystem.IsWindows()) {
        var portable = Path.Combine(paths.Resources, "runtime");
        Directory.CreateDirectory(portable);
        File.WriteAllText(Path.Combine(portable, "portable.marker"), "test");
        var trainingPaths = new AppPaths(paths.Resources, paths.Data);
        var calls = new List<(string Python, string[] Args)>();
        var failure = false;
        var stopped = false;
        var runtime = new TrainingRuntime(trainingPaths, backend, (python, command, report, token) => {
            token.ThrowIfCancellationRequested();
            var arguments = command.ToArray();
            calls.Add((python, arguments));
            if (stopped) throw new OperationCanceledException();
            return Task.FromResult(new ProcessResult(failure && arguments.Any(a => a.Contains("assert torch.cuda")) ? 1 : 0, "test GPU result"));
        });
        await runtime.SelectAsync(false, _ => { }, default);
        if (trainingPaths.Trainer != trainingPaths.DefaultTrainer || trainingPaths.TrainingDevice != "cpu" || calls.Count != 0)
            throw new Exception("CPU selection did not preserve bundled runtime");
        failure = true;
        try { await runtime.SelectAsync(true, _ => { }, default); throw new Exception("Failed GPU accepted"); }
        catch (InvalidOperationException) { }
        if (trainingPaths.TrainingDevice != "cpu") throw new Exception("Failed setup changed preference");
        failure = false; stopped = true;
        try { await runtime.SelectAsync(true, _ => { }, default); throw new Exception("Cancelled GPU accepted"); }
        catch (OperationCanceledException) { }
        if (trainingPaths.TrainingDevice != "cpu") throw new Exception("Cancellation changed preference");
        stopped = false; calls.Clear();
        await runtime.SelectAsync(true, _ => { }, default);
        if (calls.Count != 3 || calls[0].Python != trainingPaths.DefaultTrainer
            || calls[1].Python != trainingPaths.CudaTrainer
            || !calls[1].Args.Contains("torch==2.11.0+cu128")
            || trainingPaths.Trainer != trainingPaths.CudaTrainer)
            throw new Exception("CUDA setup/routing failed");
        var reloaded = new AppPaths(paths.Resources, paths.Data);
        if (reloaded.Trainer != trainingPaths.CudaTrainer) throw new Exception("GPU preference lost after restart");
        var moved = new AppPaths(Path.Combine(temporary, "new portable folder"), paths.Data);
        calls.Clear();
        var movedRuntime = new TrainingRuntime(moved, new BackendService(moved), (python, command, report, token) => {
            calls.Add((python, command.ToArray()));
            return Task.FromResult(new ProcessResult(0, "test GPU result"));
        });
        await movedRuntime.VerifyAsync(_ => { }, default);
        if (calls.Count != 2 || calls[0].Python != moved.DefaultTrainer
            || calls[0].Args[^1] != "rebase" || calls[1].Python != moved.CudaTrainer)
            throw new Exception("Moved portable runtime was not repaired before CUDA launch");
        await runtime.SelectAsync(false, _ => { }, default);
        if (reloaded.Trainer != reloaded.DefaultTrainer) throw new Exception("CPU fallback failed");
        Console.WriteLine("Training setup, verification failure, cancellation, persistence and CPU fallback: PASS");
    }
    var activityPath = Path.Combine(temporary, "activity.log");
    var activity = new BufferedActivityLog(activityPath);
    ProcessResult result;
    try {
        var context = new CountingSynchronizationContext();
        var previous = SynchronizationContext.Current;
        Task<ProcessResult> running;
        SynchronizationContext.SetSynchronizationContext(context);
        try {
            running = backend.ExecuteAsync(Environment.ProcessPath!, ["--child", "spaced/Кабинет/model name.nam"], activity.Report);
        } finally { SynchronizationContext.SetSynchronizationContext(previous); }
        result = await running;
        if (context.Posts != 0) throw new Exception("Backend output captured the UI synchronization context");
        activity.Report(new string('x', BufferedActivityLog.DisplayLimit * 2));
        activity.Report("final status");
        var update = activity.TakeUpdate() ?? throw new Exception("Activity update missing");
        if (update.Text.Length > BufferedActivityLog.DisplayLimit || !update.Text.EndsWith("final status" + Environment.NewLine)
            || update.LastLine != "final status" || activity.TakeUpdate() is not null)
            throw new Exception("Activity display is unbounded, stale or repeatedly refreshed");
    } finally { await activity.DisposeAsync(); }
    var savedLog = await File.ReadAllTextAsync(activityPath);
    if (savedLog.Split('\n').Length != 6004 || !savedLog.Contains("stdout 2999") || !savedLog.Contains("stderr 2999")
        || !savedLog.EndsWith("final status" + Environment.NewLine))
        throw new Exception("Full activity log was truncated or not flushed before shutdown");
    Console.WriteLine("Backend avoids UI context; 6,000 streamed lines persisted with bounded, batched display: PASS");
    if (result.Exit != 7 || !result.Output.Contains("spaced/Кабинет/model name.nam")
        || !result.Output.Contains("stderr 2999") || !result.Output.Contains("stdout 2999"))
        throw new Exception($"Argument encoding or concurrent pipe draining failed (exit {result.Exit}): {result.Output[..Math.Min(500, result.Output.Length)]}");
    using var cancellation = new CancellationTokenSource(300);
    try { await backend.ExecuteAsync(Environment.ProcessPath!, ["--wait"], token: cancellation.Token); throw new Exception("Cancellation did not interrupt child"); }
    catch (OperationCanceledException) { }
    foreach (var launcher in new[] { "wait", "exit" }) {
        using var stop = new CancellationTokenSource();
        var worker = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        var running = backend.ExecuteAsync(Environment.ProcessPath!, ["--spawn-worker", launcher],
            line => { if (line.StartsWith("WORKER=")) worker.TrySetResult(int.Parse(line[7..])); }, stop.Token);
        var pid = await worker.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await Task.Delay(150);
        var elapsed = Stopwatch.StartNew();
        stop.Cancel();
        if (elapsed.ElapsedMilliseconds > 200) throw new Exception("Cancellation blocked its caller");
        try { await running.WaitAsync(TimeSpan.FromSeconds(5)); throw new Exception("Worker cancellation ignored"); }
        catch (OperationCanceledException) { }
        if (OperatingSystem.IsWindows() || launcher == "wait") {
            try {
                using var child = Process.GetProcessById(pid);
                await child.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(5));
            } catch (ArgumentException) { }
        } else { using var child = Process.GetProcessById(pid); child.Kill(); }
    }
    Console.WriteLine("Cancellation returns immediately, stops workers and drains pipes after launcher exit: PASS");
    var models = new[] { new ModelSelection { Label = "AMP" }, new ModelSelection { Label = "amp" } };
    try { BankService.Validate(models); throw new Exception("Case-insensitive duplicate labels accepted"); }
    catch (InvalidDataException) { }
    var liteModels = Enumerable.Range(1, 5).Select(n => new ModelSelection { Label = $"L{n}", ModelProfile = "lite" }).ToArray();
    BankService.Validate(liteModels);
    try { BankService.Validate(liteModels, "compact"); throw new Exception("Lite list accepted as Compact"); }
    catch (InvalidDataException) { }
    if (BankService.MaxModels("lite") != 5) throw new Exception("Incorrect Lite model limit");
    var sixModels = liteModels.Append(new ModelSelection { Label = "L6", ModelProfile = "lite" }).ToArray();
    try { BankService.Validate(sixModels); throw new Exception("Six-model saved Lite list accepted"); }
    catch (InvalidDataException) { }
    try { BankService.Validate(sixModels, "lite"); throw new Exception("Six-model Lite build accepted"); }
    catch (InvalidDataException) { }
    BankService.Validate(Enumerable.Range(1, 10).Select(n => new ModelSelection { Label = $"C{n}" }).ToArray(), "compact");
    var model = Path.Combine(temporary, "model.nam");
    File.WriteAllText(model, "fixture");
    var compact = ConvertedNam.Save(model, model, paths.Data, "compact");
    var lite = ConvertedNam.Save(model, model, paths.Data, "lite");
    if (compact == lite || !compact.Contains("Compact") || !lite.Contains("Lite")) throw new Exception("Export profiles collided");
    if (ConvertedNam.Save(model, model, paths.Data, "compact") != compact) throw new Exception("Identical conversion duplicated");
    Console.WriteLine("Shared paths, DI hash, Unicode arguments, both output streams, cancellation and conversion export: PASS");
    return 0;
} finally { Directory.Delete(temporary, true); }

sealed class CountingSynchronizationContext : SynchronizationContext
{
    public int Posts;
    public override void Post(SendOrPostCallback callback, object? state)
    {
        Interlocked.Increment(ref Posts);
        ThreadPool.QueueUserWorkItem(_ => callback(state));
    }
}
