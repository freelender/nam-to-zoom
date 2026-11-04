namespace Nam2ZoomDesktop;

public static class ConvertedNam
{
    public static string ApplicationDirectory(string executableDirectory)
    {
        for (var directory = new DirectoryInfo(Path.GetFullPath(executableDirectory)); directory is not null; directory = directory.Parent)
            if (directory.Name.EndsWith(".app", StringComparison.OrdinalIgnoreCase))
                return directory.Parent?.FullName ?? throw new DirectoryNotFoundException("Application folder missing.");
        return Path.GetFullPath(executableDirectory);
    }

    public static string Save(string student, string original, string appDirectory, string? profile = null)
    {
        var directory = Path.Combine(appDirectory, "Converted_NAM");
        if (profile is not null) {
            if (profile is not ("compact" or "lite")) throw new ArgumentException("Unknown model profile", nameof(profile));
            directory = Path.Combine(directory, profile == "lite" ? "Lite" : "Compact");
        }
        Directory.CreateDirectory(directory);
        var name = Path.GetFileName(original);
        var stem = Path.GetFileNameWithoutExtension(name);
        var extension = Path.GetExtension(name);
        if (!System.Text.RegularExpressions.Regex.IsMatch(stem, @"-441-resampled(?: \([0-9]+\))?$",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase))
            stem += "-441-resampled";
        name = stem + extension;
        var bytes = File.ReadAllBytes(student);
        for (var number = 1; ; number++) {
            var destination = Path.Combine(directory,
                number == 1 ? name : $"{stem} ({number}){extension}");
            if (File.Exists(destination)) {
                if (bytes.AsSpan().SequenceEqual(File.ReadAllBytes(destination)))
                    return destination;
                continue;
            }
            // CreateNew preserves existing exports, including an original imported here.
            using var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write);
            output.Write(bytes);
            return destination;
        }
    }
}
