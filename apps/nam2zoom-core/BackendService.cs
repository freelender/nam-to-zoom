using System.Diagnostics;
using System.Text;

namespace Nam2ZoomDesktop;

public sealed record ProcessResult(int Exit, string Output)
{
    public void RequireSuccess()
    {
        if (Exit != 0) throw new InvalidOperationException($"Backend stopped (exit {Exit}). See the log before retrying.");
    }
}

public interface IConversionBackend
{
    Task<ProcessResult> RunAsync(IEnumerable<string> args, bool training = false,
        Action<string>? report = null, CancellationToken token = default);
}

public sealed class BackendService(AppPaths paths) : IConversionBackend
{
    public Task<ProcessResult> RunAsync(IEnumerable<string> args, bool training = false,
        Action<string>? report = null, CancellationToken token = default) =>
        ExecuteAsync(training ? paths.Trainer : paths.Python, ["-B", "-m", "nam2zoom", .. args], report, token);

    public Task<ProcessResult> DeviceAsync(IEnumerable<string> args, Action<string>? report = null) =>
        ExecuteAsync(paths.Python, ["-B", Path.Combine(paths.Resources, "tools", "msplus.py"), .. args], report, default);

    public Task<ProcessResult> ProbeDeviceAsync(CancellationToken token) =>
        ExecuteAsync(paths.Python, ["-B", Path.Combine(paths.Resources, "tools", "msplus.py"),
            "--timeout", "0.75", "probe"], token: token);

    public Task<ProcessResult> ExecuteAsync(string executable, IEnumerable<string> args,
        Action<string>? report = null, CancellationToken token = default)
        => Task.Run(() => ExecuteCoreAsync(executable, args, report, token), token);

    private async Task<ProcessResult> ExecuteCoreAsync(string executable, IEnumerable<string> args,
        Action<string>? report, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (!File.Exists(executable)) throw new FileNotFoundException("Bundled Python missing", executable);
        Directory.CreateDirectory(paths.Data);
        var start = new ProcessStartInfo(executable) {
            WorkingDirectory = paths.Data, RedirectStandardOutput = true, RedirectStandardError = true,
            UseShellExecute = false, CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        foreach (var arg in args) start.ArgumentList.Add(arg);
        start.Environment["PYTHONPATH"] = Path.Combine(paths.Resources, "tools");
        start.Environment["PYTHONUNBUFFERED"] = "1";
        start.Environment["PYTHONUTF8"] = "1";
        start.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        start.Environment["NAM2ZOOM_DATA_DIR"] = paths.Data;
        start.Environment["NAM2ZOOM_TRAINING_DEVICE"] = paths.TrainingDevice;
        var logs = Path.Combine(paths.Data, "logs");
        Directory.CreateDirectory(logs);
        start.Environment["NAM2ZOOM_PEDAL_LOG"] = Path.Combine(logs, "pedal_diy.log");
        start.Environment["MPLCONFIGDIR"] = Path.Combine(paths.Data, "mpl-cache");
        start.Environment["MIDO_BACKEND"] = "mido.backends.rtmidi";
        start.Environment.Remove("PYTHONHOME");
        using var process = Process.Start(start) ?? throw new InvalidOperationException("Could not start backend");
        // Windows venv launchers and trainers can spawn Python workers. The job
        // owns their lifetime even if the original launcher exits first.
        using var job = WindowsProcessJob.Attach(process);
        async Task<string> Drain(StreamReader reader)
        {
            var output = new StringBuilder();
            while (await reader.ReadLineAsync(token).ConfigureAwait(false) is { } line) { output.AppendLine(line); report?.Invoke(line); }
            return output.ToString();
        }
        // Even buffered reads can complete synchronously. Start both pumps off
        // the caller's UI thread so a verbose trainer cannot monopolize it.
        var stdout = Task.Run(() => Drain(process.StandardOutput));
        var stderr = Task.Run(() => Drain(process.StandardError));
        try {
            await process.WaitForExitAsync(token).ConfigureAwait(false);
            await Task.WhenAll(stdout, stderr).ConfigureAwait(false);
        } catch (OperationCanceledException) when (token.IsCancellationRequested) {
            if (job is not null) job.Terminate();
            else {
                try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
                catch (InvalidOperationException) { }
                catch (System.ComponentModel.Win32Exception) { }
            }
            await process.WaitForExitAsync().ConfigureAwait(false);
            try { await Task.WhenAll(stdout, stderr).ConfigureAwait(false); }
            catch (OperationCanceledException) { }
            throw;
        }
        token.ThrowIfCancellationRequested();
        return new(process.ExitCode, stdout.Result + stderr.Result);
    }
}
