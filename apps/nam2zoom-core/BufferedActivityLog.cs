using System.Text;
using System.Threading.Channels;

namespace Nam2ZoomDesktop;

/// <summary>Persists every line off the UI thread and exposes a bounded display tail.</summary>
public sealed class BufferedActivityLog : IAsyncDisposable
{
    public const int DisplayLimit = 16_000;
    private readonly object gate = new();
    private readonly StringBuilder tail = new();
    private readonly Channel<string> lines = Channel.CreateUnbounded<string>(new() { SingleReader = true });
    private readonly Task writer;
    private string lastLine = "";
    private bool changed;

    public BufferedActivityLog(string path)
    {
        writer = Task.Run(async () => {
            await using var file = new StreamWriter(path, append: true, encoding: new UTF8Encoding(false));
            var batch = new StringBuilder();
            while (await lines.Reader.WaitToReadAsync().ConfigureAwait(false)) {
                batch.Clear();
                for (var n = 0; n < 256 && lines.Reader.TryRead(out var line); n++) batch.AppendLine(line);
                await file.WriteAsync(batch.ToString()).ConfigureAwait(false);
                await file.FlushAsync().ConfigureAwait(false);
            }
        });
    }

    public void Report(string line)
    {
        lock (gate) {
            if (!lines.Writer.TryWrite(line)) return;
            tail.AppendLine(line);
            if (tail.Length > DisplayLimit) tail.Remove(0, tail.Length - DisplayLimit);
            lastLine = line;
            changed = true;
        }
    }

    public (string Text, string LastLine)? TakeUpdate()
    {
        // Surface disk errors to the UI rather than leaving a faulted writer unnoticed.
        if (writer.IsFaulted) writer.GetAwaiter().GetResult();
        lock (gate) {
            if (!changed) return null;
            changed = false;
            return (tail.ToString(), lastLine);
        }
    }

    public void ClearDisplay()
    {
        lock (gate) { tail.Clear(); lastLine = ""; changed = true; }
    }

    public async ValueTask DisposeAsync()
    {
        lock (gate) lines.Writer.TryComplete();
        await writer.ConfigureAwait(false);
    }
}
