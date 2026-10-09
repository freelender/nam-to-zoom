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

public sealed class BackendService(AppPaths paths)
{
    public Task<ProcessResult> RunAsync(IEnumerable<string> args, bool training = false,
        Action<string>? report = null, CancellationToken token = default) =>
        ExecuteAsync(training ? paths.Trainer : paths.Python, ["-B", "-m", "nam2zoom", .. args], report, token);

    public Task<ProcessResult> DeviceAsync(IEnumerable<string> args, Action<string>? report = null) =>
        ExecuteAsync(paths.Python, ["-B", Path.Combine(paths.Resources, "tools", "msplus.py"), .. args], report, default);

    public Task<ProcessResult> ProbeDeviceAsync(CancellationToken token) =>
        ExecuteAsync(paths.Python, ["-B", Path.Combine(paths.Resources, "tools", "msplus.py"),
            "--timeout", "0.75", "probe"], token: token);

    public async Task<ProcessResult> ExecuteAsync(string executable, IEnumerable<string> args,
        Action<string>? report = null, CancellationToken token = default)
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
        var logs = Path.Combine(paths.Data, "logs");
        Directory.CreateDirectory(logs);
        start.Environment["NAM2ZOOM_PEDAL_LOG"] = Path.Combine(logs, "pedal_diy.log");
        start.Environment["MPLCONFIGDIR"] = Path.Combine(paths.Data, "mpl-cache");
        start.Environment["MIDO_BACKEND"] = "mido.backends.rtmidi";
        start.Environment.Remove("PYTHONHOME");
        using var process = Process.Start(start) ?? throw new InvalidOperationException("Could not start backend");
        using var cancellation = token.Register(() => {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
        });
        async Task<string> Drain(StreamReader reader)
        {
            var output = new StringBuilder();
            while (await reader.ReadLineAsync() is { } line) { output.AppendLine(line); report?.Invoke(line); }
            return output.ToString();
        }
        var stdout = Drain(process.StandardOutput);
        var stderr = Drain(process.StandardError);
        await process.WaitForExitAsync();
        await Task.WhenAll(stdout, stderr);
        token.ThrowIfCancellationRequested();
        return new(process.ExitCode, await stdout + await stderr);
    }
}
