using System.Text.Json;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Threading;

namespace Nam2Zoom;

public sealed partial class MainWindow
{
    private readonly TextBlock pedalStatus = Text("Checking for pedal…", muted: true);
    private readonly DispatcherTimer pedalTimer = new() { Interval = TimeSpan.FromSeconds(4) };
    private Task pedalProbe = Task.CompletedTask;
    private CancellationTokenSource? pedalProbeCancellation;
    private bool closed;

    private void StartPedalDetection()
    {
        if (App.SmokeGui) return; // CI GUI startup must never contact hardware.
        pedalTimer.Tick += (_, _) => QueuePedalProbe();
        Closed += (_, _) => {
            closed = true; pedalTimer.Stop(); pedalProbeCancellation?.Cancel();
        };
        pedalTimer.Start(); QueuePedalProbe();
    }

    private void QueuePedalProbe()
    {
        if (closed || busy || deviceBusy || !pedalProbe.IsCompleted) return;
        pedalProbe = CheckPedalAsync();
    }

    private async Task CheckPedalAsync()
    {
        using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        pedalProbeCancellation = cancellation;
        try {
            var result = await vm.Backend.ProbeDeviceAsync(cancellation.Token);
            result.RequireSuccess();
            using var document = JsonDocument.Parse(result.Output);
            var info = document.RootElement;
            var state = info.GetProperty("status").GetString();
            var message = info.GetProperty("message").GetString() ?? "Pedal unavailable";
            var detail = info.TryGetProperty("detail", out var reason) ? reason.GetString() : message;
            if (info.TryGetProperty("hardware_tested", out var tested) && !tested.GetBoolean())
                detail += " · Experimental hardware support";
            if (!busy && !closed) SetPedalStatus(message, state == "connected", detail);
        }
        catch (OperationCanceledException) {
            if (!busy && !closed) SetPedalStatus("Pedal check timed out", false, "Retrying automatically.");
        }
        catch (Exception ex) {
            if (!busy && !closed) SetPedalStatus("Pedal detection unavailable", false, ex.Message);
        }
        finally { if (pedalProbeCancellation == cancellation) pedalProbeCancellation = null; }
    }

    private void SetPedalStatus(string message, bool connected, string? detail)
    {
        var text = (connected ? "●  " : "○  ") + message;
        if (pedalStatus.Text != text) Report("Pedal: " + message);
        pedalStatus.Text = text;
        pedalStatus.Foreground = Brush.Parse(connected ? "#4DA3FF" : "#9BA8B5");
        ToolTip.SetTip(pedalStatus, detail);
    }
}
