namespace Nam2ZoomDesktop;

public sealed class BuildWorkspace(string output)
{
    public string Output { get; } = Path.GetFullPath(output);
    public string StagedPreviews => Output + "-preview";

    public static BuildWorkspace Create(string parent) => new(Path.Combine(parent,
        "n2z-bank-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N")[..8]));

    public string? StagePreviews(IEnumerable<(string Label, string Directory)> previews)
    {
        var copied = false;
        foreach (var (label, source) in previews) {
            var destination = Path.Combine(StagedPreviews, label);
            Directory.CreateDirectory(destination);
            foreach (var name in new[] { "original.wav", "converted.wav" })
                File.Copy(Path.Combine(source, name), Path.Combine(destination, name));
            copied = true;
        }
        return copied ? StagedPreviews : null;
    }

    public string? CompletePreviews()
    {
        if (!Directory.Exists(StagedPreviews)) return null;
        if (!Directory.Exists(Output))
            throw new DirectoryNotFoundException("The effect build output is missing.");
        var destination = Path.Combine(Output, "preview");
        Directory.Move(StagedPreviews, destination);
        return destination;
    }
}
