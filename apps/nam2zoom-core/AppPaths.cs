namespace Nam2ZoomDesktop;

public sealed class AppPaths
{
    public string Resources { get; }
    public string Data { get; }
    public string Python { get; }
    public string Trainer { get; }
    public string Cache => Path.Combine(Data, "adapt-cache");
    public string Backup => Path.Combine(Data, "Backup");

    public AppPaths(string? resources = null, string? data = null)
    {
        Resources = resources ?? FindResources();
        Data = data ?? Environment.GetEnvironmentVariable("NAM2ZOOM_DATA_DIR")
            ?? (OperatingSystem.IsMacOS()
                ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library", "Application Support", "nam2zoom")
                : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "nam2zoom"));
        Data = Path.GetFullPath(Data);
        var bundled = Path.Combine(Resources, "runtime", "python");
        Python = File.Exists(Path.Combine(Resources, "runtime", "portable.marker"))
            ? PythonAt(bundled, false)
            : PythonAt(Path.Combine(Resources, ".tooling", "stomphacks", ".venv"), true);
        Trainer = File.Exists(Path.Combine(Resources, "runtime", "portable.marker"))
            ? Python : PythonAt(Path.Combine(Resources, ".tooling", "nam-train-venv"), true);
    }

    private static string PythonAt(string directory, bool venv) => OperatingSystem.IsWindows()
        ? Path.Combine(directory, venv ? "Scripts" : "", "python.exe")
        : Path.Combine(directory, "bin", "python3");

    private static string FindResources()
    {
        // macOS executable is Contents/MacOS/nam2zoom; backend lives in Resources.
        var bundle = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "Resources"));
        if (File.Exists(Path.Combine(bundle, "tools", "nam2zoom", "__main__.py"))) return bundle;
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, "tools", "nam2zoom", "__main__.py"))) return directory.FullName;
        throw new DirectoryNotFoundException("Backend resources missing. Extract the entire release ZIP.");
    }

    public string TrainingDi()
    {
        const string hash = "F27F5EA4A1BC4245AF5C4DFF5DE5B75FB7AEF71C1B10E196B35EA5EF41122153";
        var target = Path.Combine(Data, "training", "TRAINING_DI.wav");
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        using var resource = typeof(AppPaths).Assembly.GetManifestResourceStream("Nam2ZoomDesktop.TRAINING_DI.wav")
            ?? throw new FileNotFoundException("Training DI resource missing");
        using var memory = new MemoryStream();
        resource.CopyTo(memory);
        var bytes = memory.ToArray();
        if (Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)) != hash)
            throw new InvalidDataException("Training DI hash mismatch");
        File.WriteAllBytes(target, bytes);
        return target;
    }
}
