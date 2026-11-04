using Nam2ZoomDesktop;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using System.Diagnostics;

namespace Nam2Zoom;

public sealed partial class MainWindow
{
    // Deterministic visual-test fixtures, never enabled during normal application startup.
    private void ConfigureSmokePreview()
    {
        if (Environment.GetEnvironmentVariable("NAM2ZOOM_GUI_CANCEL_PYTHON") is { Length: > 0 } python)
            Opened += async (_, _) => await CheckCancellationSmoke(python);
        if (Environment.GetEnvironmentVariable("NAM2ZOOM_GUI_DEMO") == "1") {
            var names = new[] { "JCM800.nam", "MESA.nam", "VOX30.nam", "MARK.nam", "TWINR.nam", "45.nam", "PLEXI.nam", "DELUXE.nam", "ORANGE.nam", "BASSMAN.nam" };
            foreach (var name in names) vm.Models.Add(new RetrainingItem(new() { Path = Path.Combine("Visual test fixtures", name), SampleRate = 48000, Status = "adaptable", ModelProfile = "lite" }) { IsSelected = vm.Models.Count < 3 });
            selectAll.IsChecked = true;
            if (vm.Models.Any(i => !i.IsSelected)) throw new InvalidOperationException("Select-all did not select every queue item.");
            selectAll.IsChecked = false;
            if (vm.Models.Any(i => i.IsSelected)) throw new InvalidOperationException("Select-all did not clear every queue item.");
            for (var n = 0; n < vm.Models.Count; n++) vm.Models[n].IsSelected = n < 3;
            RefreshCount();
            vm.Models[0].State = "Retraining…"; vm.Models[0].Progress = 65;
            models.SelectedItem = vm.Models[0];
            changingDevice = true;
            trainingDevice.ItemsSource = new[] { new DeviceChoice("CPU", false), new DeviceChoice("NVIDIA GeForce RTX 3060 (CUDA)", true) };
            trainingDevice.SelectedIndex = 1; changingDevice = false;
            batchText.Text = "Training 1 of 10"; progress.Value = 6.5; activity.Text = "JCM800.nam (65%)"; cancel.IsEnabled = true;
            Report("Visual test fixture — no training or device operation is running.");
            var fixtures = Path.Combine(vm.Paths.Data,"visual-effect-fixtures"); Directory.CreateDirectory(fixtures);
            foreach (var name in names.Take(3)) {
                var path = Path.Combine(fixtures,name); File.WriteAllText(path,"Visual fixture only — not a NAM model."); AddEffectChoice(path);
            }
            foreach (var choice in effectChoices) choice.Selected = true;
            RenderEffectModels();
            Report("Found 10 NAM files in queue"); Report("Epoch 10/100 — loss: 0.2314");
        }
        if (Environment.GetEnvironmentVariable("NAM2ZOOM_GUI_PAGE") is { } page && navigation.ContainsKey(page)) Navigate(page);
        if (navigation.Count != 4) throw new InvalidOperationException("Studio navigation missing.");
    }

    private async Task CheckCancellationSmoke(string python)
    {
        var resultPath = Environment.GetEnvironmentVariable("NAM2ZOOM_GUI_CANCEL_RESULT")
            ?? throw new InvalidOperationException("Cancellation smoke result path missing.");
        var ticks = 0;
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(20) };
        timer.Tick += (_, _) => ticks++;
        timer.Start();
        try {
            foreach (var close in new[] { false, true }) {
                var ready = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                var workerId = 0;
                var cancelled = false;
                // Run the actual venv launcher and a CUDA worker with verbose progress.
                var workerScript = "import torch,time; x=torch.randn(1024,1024,device='cuda'); print('CUDA_READY',flush=True); "
                    + "exec(\"while True:\\n x=x @ x; torch.cuda.synchronize(); time.sleep(.005)\")";
                var script = "import subprocess,sys; "
                    + "p=subprocess.Popen([sys.executable,'-u','-c'," + System.Text.Json.JsonSerializer.Serialize(workerScript) + "]); "
                    + "print('WORKER='+str(p.pid),flush=True); p.wait()";
                await Run(async () => {
                    var running = vm.Backend.ExecuteAsync(python, ["-u", "-c", script], line => {
                        Report(line);
                        if (line.StartsWith("WORKER=")) workerId = int.Parse(line[7..]);
                        if (line == "CUDA_READY") ready.TrySetResult();
                    }, cancellation!.Token);
                    var first = await Task.WhenAny(ready.Task, running).WaitAsync(TimeSpan.FromSeconds(60));
                    if (first == running) { (await running).RequireSuccess(); throw new Exception("CUDA worker exited before ready."); }
                    var fixture = new RetrainingItem(new() { Path = "Cancellation fixture.nam" });
                    await Task.Run(() => {
                        for (var n = 0; n < 20000; n++) {
                            var line = $"Epoch {n % 100}/100";
                            Report(line); trainingProgress.Report(fixture, line, 100);
                        }
                    });
                    var before = ticks;
                    await Task.Delay(200);
                    if (ticks == before) throw new Exception("UI heartbeat stopped during GPU workload.");
                    var elapsed = Stopwatch.StartNew();
                    if (close) Close();
                    else cancel.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    if (elapsed.ElapsedMilliseconds > 200) throw new Exception("Cancel/close blocked UI thread.");
                    try { await running.WaitAsync(TimeSpan.FromSeconds(5)); }
                    catch (OperationCanceledException) { cancelled = true; }
                });
                if (!cancelled || busy) throw new Exception("GPU cancellation did not finish.");
                try {
                    using var worker = Process.GetProcessById(workerId);
                    await worker.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(5));
                } catch (ArgumentException) { }
                if (close && !closeRequested) throw new Exception("Window did not request close.");
            }
            File.WriteAllText(resultPath, "PASS: CUDA worker stopped by Cancel and window close; UI heartbeat survived 20,000 progress lines per run.");
        } catch (Exception ex) {
            File.WriteAllText(resultPath, "FAIL: " + ex);
            cancellation?.Cancel(); Close();
        } finally { timer.Stop(); }
    }
}
