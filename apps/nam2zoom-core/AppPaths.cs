namespace Nam2ZoomDesktop;

public sealed class AppPaths
{
    public string Resources { get; }
    public string Data { get; }
    public string Python { get; }
    public string DefaultTrainer { get; }
    public RuntimeBootstrap? Bootstrap { get; }
    public string? LocalRuntimeArchive { get; }
    public string TrainingPreference => Path.Combine(Data, "training", "device.txt");
    public string CudaTrainer => Path.Combine(Data, "training", "cuda-venv", "Scripts", "python.exe");
    public string TrainingDevice => File.Exists(TrainingPreference) ? File.ReadAllText(TrainingPreference).Trim() : "auto";
    public string Trainer => OperatingSystem.IsWindows() && TrainingDevice == "cuda" ? CudaTrainer : DefaultTrainer;
    public string Cache => Path.Combine(Data, "adapt-cache");
    public string Backup => Path.Combine(Data, "Backup");

    public AppPaths(string? resources = null, string? data = null)
    {
        Resources = resources ?? FindResources();
        var runtime = Path.Combine(Resources, "runtime");
        var localTestRoot = File.Exists(Path.Combine(runtime, "local-test.marker"))
            ? Path.GetFullPath(Path.Combine(Resources, ".."))
            : null;
        if (localTestRoot is not null)
            LocalRuntimeArchive = Path.Combine(localTestRoot, "python-runtime.tar.gz");
        Data = data ?? Environment.GetEnvironmentVariable("NAM2ZOOM_DATA_DIR")
            ?? (localTestRoot is null ? null : Path.Combine(localTestRoot, "test-data"))
            ?? (OperatingSystem.IsMacOS()
                ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Library", "Application Support", "nam2zoom")
                : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "nam2zoom"));
        Data = Path.GetFullPath(Data);
        var manifest = Path.Combine(runtime, "download.json");
        if (File.Exists(manifest)) Bootstrap = RuntimeBootstrap.Load(manifest, Data);
        var portable = File.Exists(Path.Combine(runtime, "portable.marker"));
        Python = portable
            ? PythonAt(Bootstrap?.PythonHome ?? Path.Combine(runtime, "python"), false)
            : PythonAt(Path.Combine(Resources, ".tooling", "stomphacks", ".venv"), true);
        DefaultTrainer = portable
            ? Python : PythonAt(Path.Combine(Resources, ".tooling", "nam-train-venv"), true);
    }

    internal static string PythonAt(string directory, bool venv) => OperatingSystem.IsWindows()
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
