namespace Nam2ZoomDesktop;

internal static class ConvertedNam
{
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
