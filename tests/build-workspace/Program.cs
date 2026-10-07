using System.Diagnostics;
using Nam2ZoomDesktop;

if (args.Length is not (3 or 4)) throw new ArgumentException("Usage: smoke <portable root> <Python with audio libraries> <converted NAM> [compact|lite]");
var portable = Path.GetFullPath(args[0]);
var python = Path.GetFullPath(args[1]);
var student = Path.GetFullPath(args[2]);
var profile = args.Length == 4 ? args[3] : "compact";
if (profile is not ("compact" or "lite")) throw new ArgumentException("Unknown model profile");
var temporary = Path.Combine(Path.GetTempPath(), "nam2zoom-build-workspace-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(temporary);
try {
    var source = Path.Combine(temporary, "cached-preview");
    Directory.CreateDirectory(source);
    File.WriteAllText(Path.Combine(source, "original.wav"), "original audio");
    File.WriteAllText(Path.Combine(source, "converted.wav"), "converted audio");
    var declined = BuildWorkspace.Create(temporary);
    var preview = declined.StagePreviews([("AMP", source)]);
    if (Directory.Exists(declined.Output) || preview is null || !File.Exists(Path.Combine(preview, "AMP", "converted.wav")))
        throw new Exception("Review previews must not create the bank output");
    // Declining review leaves previews usable without an effect output.
    if (File.ReadAllText(Path.Combine(preview, "AMP", "original.wav")) != "original audio")
        throw new Exception("Declined previews were not preserved");
    foreach (var (converted, count) in new[] { (false, 1), (true, 1), (false, 10), (true, 10) }) {
        var workspace = BuildWorkspace.Create(temporary);
        if (workspace.Output == declined.Output) throw new Exception("Repeated builds reused a path");
        workspace.StagePreviews(converted ? [("AMP", source)] : []);
        if (Directory.Exists(workspace.Output)) throw new Exception("Bank output was created before backend execution");
        var start = new ProcessStartInfo(python) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in new[] { "-m", "nam2zoom", "build-bank" })
            start.ArgumentList.Add(argument);
        for (var i = 0; i < count; i++) start.ArgumentList.Add(student);
        for (var i = 0; i < count; i++) {
            start.ArgumentList.Add("--label");
            start.ArgumentList.Add(count == 1 ? "AMP" : $"AMP{i}");
        }
        foreach (var argument in new[] { "--output", workspace.Output, "--profile", profile })
            start.ArgumentList.Add(argument);
        start.Environment["PYTHONPATH"] = Path.Combine(portable, "tools");
        using var backend = Process.Start(start)!;
        var stdout = backend.StandardOutput.ReadToEndAsync();
        var stderr = backend.StandardError.ReadToEndAsync();
        await backend.WaitForExitAsync();
        if (backend.ExitCode != 0) throw new Exception(await stdout + await stderr);
        if (!File.Exists(Path.Combine(workspace.Output, "build", "N2ZBANK.ZD2"))
            || !File.Exists(Path.Combine(workspace.Output, "build", "N2ZBANK.ZIC")))
            throw new Exception("Backend did not produce effect and icon");
        using var manifest = System.Text.Json.JsonDocument.Parse(File.ReadAllText(Path.Combine(workspace.Output, "manifest.json")));
        if (manifest.RootElement.GetProperty("params")[0].GetProperty("values").GetArrayLength() != Math.Max(2, count))
            throw new Exception("Model selector does not contain every slot");
        var completed = workspace.CompletePreviews();
        if (converted) {
            if (completed != Path.Combine(workspace.Output, "preview") || Directory.Exists(workspace.StagedPreviews)
                || File.ReadAllText(Path.Combine(completed, "AMP", "converted.wav")) != "converted audio")
                throw new Exception("Successful build did not retain previews in the final output");
        } else if (completed is not null) throw new Exception("Direct build created unnecessary previews");
    }
    Console.WriteLine("Preview review, converted/direct builds, one/ten slots and actual portable backend: PASS");
} finally {
    // Only this test's newly allocated temporary directory is removed.
    var resolved = Path.GetFullPath(temporary);
    if (Path.GetDirectoryName(resolved) != Path.TrimEndingDirectorySeparator(Path.GetTempPath())
        || !Path.GetFileName(resolved).StartsWith("nam2zoom-build-workspace-", StringComparison.Ordinal))
        throw new Exception("Unexpected cleanup target");
    Directory.Delete(resolved, recursive: true);
}
