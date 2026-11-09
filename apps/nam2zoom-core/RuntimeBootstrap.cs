using System.Formats.Tar;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace Nam2ZoomDesktop;

public sealed class RuntimeBootstrap
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromMinutes(30) };
    private readonly Uri url;
    private readonly string checksum;
    private readonly long size;
    public string PythonHome { get; }
    public bool IsReady => File.Exists(AppPaths.PythonAt(PythonHome, false));

    private RuntimeBootstrap(Uri url, string checksum, long size, string data)
    {
        this.url = url;
        this.checksum = checksum;
        this.size = size;
        PythonHome = Path.Combine(data, "runtime", checksum.ToLowerInvariant(), "python");
    }

    internal static RuntimeBootstrap Load(string manifest, string data)
    {
        using var json = JsonDocument.Parse(File.ReadAllText(manifest));
        var root = json.RootElement;
        var checksum = root.GetProperty("sha256").GetString();
        var size = root.GetProperty("size").GetInt64();
        if (checksum is not { Length: 64 } || !checksum.All(Uri.IsHexDigit) || size <= 0 ||
            !Uri.TryCreate(root.GetProperty("url").GetString(), UriKind.Absolute, out var url) ||
            url.Scheme != Uri.UriSchemeHttps)
            throw new InvalidDataException("Invalid Python runtime download manifest.");
        return new RuntimeBootstrap(url, checksum, size, data);
    }

    public async Task InstallAsync(Action<string> report, CancellationToken token, string? localArchive = null)
    {
        if (IsReady) return;
        var target = Path.GetDirectoryName(PythonHome)!;
        var cache = Path.GetDirectoryName(target)!;
        Directory.CreateDirectory(cache);
        using var lease = await AcquireLockAsync(target + ".lock", token);
        if (IsReady) return;
        var staging = Directory.CreateDirectory(Path.Combine(cache, ".install-" + Guid.NewGuid()));
        try {
            var extraction = staging.CreateSubdirectory("extracted");
            var archive = localArchive ?? Path.Combine(staging.FullName, "python.tar.gz");
            if (localArchive is null) {
                report($"Downloading Python and dependencies ({size / 1_000_000:N0} MB)...");
                using var response = await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, token);
                response.EnsureSuccessStatusCode();
                await using var source = await response.Content.ReadAsStreamAsync(token);
                await using var destination = File.Create(archive);
                var buffer = new byte[128 * 1024];
                long received = 0;
                var lastPercent = -1;
                while (await source.ReadAsync(buffer, token) is var count && count > 0) {
                    received += count;
                    if (received > size) throw new InvalidDataException("Python runtime download exceeded the expected size.");
                    await destination.WriteAsync(buffer.AsMemory(0, count), token);
                    var percent = (int)(100.0 * received / size);
                    if (percent != lastPercent) report($"Downloading Python and dependencies… {percent}%");
                    lastPercent = percent;
                }
            }
            report("Verifying the runtime archive…");
            await using var input = File.OpenRead(archive);
            if (input.Length != size ||
                !Convert.ToHexString(await SHA256.HashDataAsync(input, token)).Equals(checksum, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Python runtime archive failed verification. Retry setup.");
            input.Position = 0;
            report("Installing Python and dependencies…");
            await using var gzip = new GZipStream(input, CompressionMode.Decompress);
            await TarFile.ExtractToDirectoryAsync(gzip, extraction.FullName, overwriteFiles: false, token);
            if (!File.Exists(AppPaths.PythonAt(Path.Combine(extraction.FullName, "python"), false)))
                throw new InvalidDataException("Python executable missing from the runtime archive.");
            token.ThrowIfCancellationRequested();
            if (Directory.Exists(target)) Directory.Delete(target, recursive: true);
            Directory.Move(extraction.FullName, target);
        } finally {
            staging.Delete(recursive: true);
        }
    }

    private static async Task<FileStream> AcquireLockAsync(string path, CancellationToken token)
    {
        while (true) {
            token.ThrowIfCancellationRequested();
            try {
                return new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            } catch (IOException ex) when ((ex.HResult & 0xffff) is 11 or 32 or 33 or 35) {
                await Task.Delay(250, token);
            }
        }
    }
}
