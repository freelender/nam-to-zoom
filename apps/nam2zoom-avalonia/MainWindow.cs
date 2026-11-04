using System.Diagnostics;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using Nam2ZoomDesktop;

namespace Nam2Zoom;

public sealed partial class MainWindow : Window
{
    private readonly MainViewModel vm = new();
    private readonly ListBox models = new();
    private readonly NumericUpDown epochs = new EpochUpDown();
    private readonly ComboBox trainingDevice = new() { HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Stretch };
    private readonly ProgressBar progress = new() { Minimum = 0, Maximum = 100, Height = 10, Width = 270 };
    private readonly Button cancel = new() { Content = "Cancel all", IsEnabled = false };
    private readonly CheckBox autoScroll = new() { Content = "Auto scroll", IsChecked = true };
    private readonly TextBlock activity = Text("Ready to retrain", 12, true);
    private readonly TextBlock batchText = Text("Ready", 12);
    private readonly TextBlock modelCount = Text("0 NAM files", 12);
    private readonly CheckBox selectAll = new() { IsChecked = true };
    private readonly List<Control> busyControls = [];
    private readonly Dictionary<string, Button> navigation = [];
    private readonly Grid pageHost = new();
    private readonly ScrollViewer logScroll = new();
    private readonly SelectableTextBlock logText = new();
    private readonly StackPanel exportsPanel = new() { Spacing = 10 };
    private readonly TextBlock deviceDescription = Text("CPU", 14);
    private readonly BufferedActivityLog activityLog;
    private readonly DispatcherTimer logTimer = new() { Interval = TimeSpan.FromMilliseconds(100) };
    private readonly RetrainingQueue queue;
    private readonly TrainingProgressBuffer trainingProgress = new();
    private CancellationTokenSource? cancellation;
    private bool busy, deviceBusy, logClosed, changingDevice, changingSelection, preferencesLoaded;
    private bool closeRequested, logClosing;
    private string currentPage = "Retrain";
    private int batchCount, batchDone;
    private RetrainingItem[] trainingItems = [];
    private string ExportBase => ConvertedNam.ApplicationDirectory(AppContext.BaseDirectory);
    private string ExportFolder => Path.Combine(ExportBase, "Converted_NAM");
    private string PreferencesFile => Path.Combine(vm.Paths.Data, "studio-settings.json");

    public MainWindow()
    {
        Title = "nam2zoom";
        Width = 1710; Height = 950; MinWidth = 1280; MinHeight = 760;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Opened += (_, _) => {
            if (Screens.ScreenFromWindow(this) is not { } screen) return;
            Width = Math.Min(Width, Math.Max(MinWidth, screen.WorkingArea.Width / RenderScaling - 24));
            Height = Math.Min(Height, Math.Max(MinHeight, screen.WorkingArea.Height / RenderScaling - 24));
        };
        DataContext = vm;
        Directory.CreateDirectory(Path.Combine(vm.Paths.Data, "logs"));
        activityLog = new(Path.Combine(vm.Paths.Data, "logs", DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + ".log"));
        queue = new(vm.Conversions);
        LoadPreferences();
        logTimer.Tick += (_, _) => FlushActivity(); logTimer.Start();
        models.ItemsSource = vm.Models;
        BuildStudioLayout();
        vm.Models.CollectionChanged += (_, _) => RefreshCount();
        selectAll.IsCheckedChanged += (_, _) => {
            if (changingSelection) return;
            var selected = selectAll.IsChecked == true;
            foreach (var item in vm.Models) item.IsSelected = selected;
            RefreshCount();
        };
        epochs.ValueChanged += (_, _) => SavePreferences();
        autoScroll.IsCheckedChanged += (_, _) => { SavePreferences(); if (autoScroll.IsChecked == true) logScroll.ScrollToEnd(); };
        trainingDevice.SelectionChanged += async (_, _) => {
            if (!changingDevice && trainingDevice.SelectedItem is DeviceChoice choice)
                await Run(() => ChangeDevice(choice));
        };
        Opened += async (_, _) => { if (!App.SmokeGui) await LoadDevices(); };
        DragDrop.SetAllowDrop(this, true);
        AddHandler(DragDrop.DragOverEvent, (_, e) => e.DragEffects = busy ? DragDropEffects.None : DragDropEffects.Copy);
        AddHandler(DragDrop.DropEvent, async (_, e) => {
            if (!busy) await Run(() => Add(e.DataTransfer.TryGetFiles()?.Select(f => f.TryGetLocalPath()).OfType<string>() ?? []));
        });
        cancel.Click += (_, _) => { if (!deviceBusy) cancellation?.Cancel(); };
        Closing += async (_, e) => {
            if (deviceBusy) { e.Cancel = true; Report("Keep the app open and the pedal powered and connected until the transfer finishes."); }
            else if (busy) { e.Cancel = true; closeRequested = true; cancellation?.Cancel(); }
            else if (!logClosed) {
                e.Cancel = true;
                if (logClosing) return;
                logClosing = true; logTimer.Stop();
                try { await activityLog.DisposeAsync(); }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { Debug.WriteLine(ex); }
                logClosed = true; Close();
            }
        };
        RefreshCount();
        if (App.SmokeGui) ConfigureSmokePreview();
        Report("Zoom-ready exports: " + ExportFolder);
    }

    private async Task Run(Func<Task> action)
    {
        if (busy) return;
        busy = true; cancellation = new(); cancel.IsEnabled = true; progress.IsIndeterminate = true; progress.Value = 0;
        foreach (var control in busyControls) control.IsEnabled = false;
        try { await action(); }
        catch (OperationCanceledException) { Report("Cancelled. Completed exports and cached conversions retained."); }
        catch (Exception ex) {
            Report(ex.Message);
            if (App.SmokeGui) throw;
            if (!closeRequested) await Dialog("Operation stopped", ex is UnauthorizedAccessException
                ? "Cannot write a required folder. Move the extracted app folder or macOS .app to a writable location. Exports belong in: " + ExportFolder : ex.Message + (deviceBusy ? "\n\nKeep the pedal powered and connected. Review the session/recovery logs before retrying." : ""), false);
        }
        finally {
            busy = false; deviceBusy = false; progress.IsIndeterminate = false;
            foreach (var control in busyControls) control.IsEnabled = true;
            cancel.IsEnabled = false; cancellation.Dispose(); cancellation = null;
            RefreshCount(); RefreshExports(); UpdateEffectActions();
            trainingProgress.TakeUpdate();
            if (closeRequested) Close();
        }
    }
    private Button ActionButton(string text, string icon, Func<Task> action, string? style = null)
    {
        var button = NewButton(text, icon, style);
        button.Click += async (_, _) => await Run(action);
        return button;
    }
    private Button UtilityButton(string text, string icon, Action action)
    {
        var button = NewButton(text, icon);
        button.Click += async (_, _) => { try { action(); } catch (Exception ex) { await Dialog("Action stopped", ex.Message, false); } };
        return button;
    }
    private void Report(string line) => activityLog.Report($"[{DateTime.Now:HH:mm:ss}] {line}");
    private void FlushActivity()
    {
        if (trainingProgress.TakeUpdate() is { } update && ReferenceEquals(queue.Current, update.Item)) {
            var item = update.Item;
            if (update.State is not null) item.State = update.State;
            item.Progress = Math.Max(item.Progress, update.Progress);
            var index = Array.IndexOf(trainingItems, item);
            batchText.Text = $"Training {index + 1} of {batchCount}";
            progress.Value = (Math.Max(0, index) + item.Progress / 100) * 100 / Math.Max(1, batchCount);
            activity.Text = $"{item.Name} ({item.Progress:0}%)";
            if (index >= 0) models.SelectedItem = item;
        }
        try {
            if (activityLog.TakeUpdate() is not { } logUpdate) return;
            vm.Log = logUpdate.Text; logText.Text = logUpdate.Text;
            if (autoScroll.IsChecked == true) logScroll.ScrollToEnd();
        } catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) {
            logTimer.Stop(); activity.Text = "Log could not be saved: " + ex.Message;
        }
    }
    private async Task Add(IEnumerable<string> inputs)
    {
        var added = 0; var rejected = 0;
        foreach (var input in inputs) {
            var paths = Directory.Exists(input)
                ? Directory.EnumerateFiles(input, "*", new EnumerationOptions { RecurseSubdirectories = true, IgnoreInaccessible = true, AttributesToSkip = FileAttributes.ReparsePoint })
                : [input];
            foreach (var path in paths) {
                cancellation!.Token.ThrowIfCancellationRequested();
                if (!path.EndsWith(".nam", StringComparison.OrdinalIgnoreCase)) continue;
                if (vm.Models.Any(m => string.Equals(m.Model.Path, Path.GetFullPath(path),
                    OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))) continue;
                try {
                    var model = new ModelSelection { Path = Path.GetFullPath(path), Label = Path.GetFileNameWithoutExtension(path), ModelProfile = "lite" };
                    await vm.Conversions.InspectAsync(model, cancellation.Token);
                    var item = new RetrainingItem(model);
                    item.PropertyChanged += (_, e) => { if (e.PropertyName == nameof(RetrainingItem.IsSelected)) RefreshCount(); };
                    vm.Models.Add(item); added++;
                } catch (OperationCanceledException) { throw; }
                catch (Exception ex) { rejected++; Report("Skipped " + Path.GetFileName(path) + ": " + ex.Message); }
            }
        }
        Report($"Added {added} NAM file(s); skipped {rejected} unsupported or unreadable file(s).");
        if (rejected > 0) await Dialog("Import complete", $"Added {added} NAM file(s). {rejected} file(s) were skipped. See the retraining log for details.", false);
    }
    private void RefreshCount()
    {
        var selected = vm.Models.Count(i => i.IsSelected);
        modelCount.Text = $"{vm.Models.Count} NAM files";
        selectionText.Text = $"{selected} selected";
        changingSelection = true;
        selectAll.IsChecked = selected == vm.Models.Count && selected > 0 ? true : selected == 0 ? false : null;
        changingSelection = false;
        for (var n = 0; n < vm.Models.Count; n++) vm.Models[n].Number = n + 1;
        emptyHint.IsVisible = vm.Models.Count == 0;
    }
    private async Task PickFiles()
    {
        var files = await StorageProvider.OpenFilePickerAsync(new() { Title = "Add NAM files", AllowMultiple = true,
            FileTypeFilter = [new("Neural Amp Modeler") { Patterns = ["*.nam"] }] });
        await Add(files.Select(f => f.TryGetLocalPath()).OfType<string>());
    }
    private async Task PickFolder()
    {
        var folder = (await StorageProvider.OpenFolderPickerAsync(new() { Title = "Add a folder of NAM captures" })).FirstOrDefault()?.TryGetLocalPath();
        if (folder is not null) await Add([folder]);
    }
    private async Task Convert(IReadOnlyList<RetrainingItem>? single = null)
    {
        var items = single ?? vm.Models.Where(i => i.IsSelected).ToArray();
        if (items.Count == 0) throw new InvalidDataException("Select NAM files first.");
        cancel.IsEnabled = true;
        trainingItems = items.ToArray();
        batchCount = items.Count; batchDone = 0; progress.IsIndeterminate = false; progress.Value = 0;
        foreach (var item in items) await vm.Conversions.InspectAsync(item.Model, cancellation!.Token);
        if (items.Any(i => i.Model.Status != "direct") && OperatingSystem.IsWindows()) {
            var runtime = new TrainingRuntime(vm.Paths, vm.Backend);
            if (!runtime.HasPreference) await runtime.SelectAsync(false, Report, cancellation!.Token);
            await runtime.VerifyAsync(Report, cancellation!.Token);
        }
        Report($"Found {items.Count} selected NAM files in queue");
        Report("Using device: " + (trainingDevice.SelectedItem?.ToString() ?? vm.Paths.TrainingDevice));
        var trainingEpochs = (int)(epochs.Value ?? 100);
        var result = await queue.RunAsync(items, ExportBase, trainingEpochs,
            async (warning, preview) => {
                OpenFolder(preview);
                return await Dialog("Review conversion quality", warning + "\n\nListen to original.wav and converted.wav. Export this conversion? Declining keeps cached models and previews.", true);
            }, (item, line) => {
                Report(line);
                trainingProgress.Report(item, line, trainingEpochs);
            }, cancellation!.Token);
        batchDone = result.Exported + result.Declined + result.Cancelled + result.Failed;
        progress.Value = batchDone == batchCount ? 100 : progress.Value;
        batchText.Text = "Batch finished";
        activity.Text = $"{result.Exported} exported · {result.Declined} declined · {result.Cancelled} cancelled · {result.Failed} failed";
        Report(activity.Text);
        RefreshExports();
    }
    private record DeviceChoice(string Label, bool Cuda) { public override string ToString() => Label; }
    private async Task LoadDevices()
    {
        var gpu = "NVIDIA GPU (CUDA setup)";
        try {
            var result = await vm.Backend.ExecuteAsync(vm.Paths.DefaultTrainer, ["-c",
                "import subprocess; r=subprocess.run(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],capture_output=True,text=True,timeout=5); print(r.stdout.splitlines()[0] if r.returncode==0 and r.stdout.strip() else '')"]);
            if (result.Exit == 0 && result.Output.Trim() is { Length: > 0 } name) gpu = name.Split('\n')[0].Trim() + " (CUDA)";
        } catch (Exception ex) { Debug.WriteLine(ex.Message); }
        changingDevice = true;
        trainingDevice.ItemsSource = OperatingSystem.IsWindows()
            ? new[] { new DeviceChoice("CPU", false), new DeviceChoice(gpu, true) } : [new DeviceChoice("CPU", false)];
        trainingDevice.SelectedIndex = vm.Paths.TrainingDevice == "cuda" ? 1 : 0;
        deviceDescription.Text = trainingDevice.SelectedItem?.ToString() ?? "CPU";
        changingDevice = false;
    }
    private async Task ChangeDevice(DeviceChoice choice)
    {
        var oldCuda = vm.Paths.TrainingDevice == "cuda";
        try {
            if (choice.Cuda && !oldCuda && !await Dialog("Enable NVIDIA GPU training", "NVIDIA setup downloads several GB of CUDA training packages. A compatible NVIDIA driver and internet connection are required. Enable GPU training?", true)) return;
            cancel.IsEnabled = true;
            await new TrainingRuntime(vm.Paths, vm.Backend).SelectAsync(choice.Cuda, Report, cancellation!.Token);
            deviceDescription.Text = choice.Label;
        } finally {
            changingDevice = true; trainingDevice.SelectedIndex = vm.Paths.TrainingDevice == "cuda" ? 1 : 0; changingDevice = false;
        }
    }
    private void LoadPreferences()
    {
        try {
            if (File.Exists(PreferencesFile)) {
                using var doc = JsonDocument.Parse(File.ReadAllText(PreferencesFile));
                epochs.Value = Math.Clamp(doc.RootElement.GetProperty("epochs").GetInt32(), 1, 300);
                autoScroll.IsChecked = doc.RootElement.GetProperty("autoScroll").GetBoolean();
            }
        } catch (Exception ex) when (ex is IOException or JsonException or KeyNotFoundException or InvalidOperationException) { Debug.WriteLine(ex.Message); }
        preferencesLoaded = true;
    }
    private void SavePreferences()
    {
        if (!preferencesLoaded) return;
        try { Directory.CreateDirectory(vm.Paths.Data); File.WriteAllText(PreferencesFile, JsonSerializer.Serialize(new { epochs = (int)(epochs.Value ?? 100), autoScroll = autoScroll.IsChecked == true })); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { Report("Settings could not be saved: " + ex.Message); }
    }
    private async Task SaveProject()
    {
        var file = await StorageProvider.SaveFilePickerAsync(new() { SuggestedFileName = "models.n2zqueue.json" });
        if (file?.TryGetLocalPath() is { } path) await File.WriteAllTextAsync(path, JsonSerializer.Serialize(vm.Models.Select(i => i.Model.Path).ToArray()));
    }
    private async Task OpenProject()
    {
        var path = (await StorageProvider.OpenFilePickerAsync(new() { FileTypeFilter = [new("Retraining queue") { Patterns = ["*.n2zqueue.json"] }] })).FirstOrDefault()?.TryGetLocalPath();
        if (path is not null) await Add(JsonSerializer.Deserialize<string[]>(await File.ReadAllTextAsync(path)) ?? []);
    }
    private static void OpenFolder(string path) => Process.Start(new ProcessStartInfo(OperatingSystem.IsMacOS() ? "/usr/bin/open" : "explorer.exe") { UseShellExecute = false, ArgumentList = { path } });
    private static void OpenLoader() => Process.Start(new ProcessStartInfo(ConversionService.LoaderUrl) { UseShellExecute = true });
    private void OpenExports() { Directory.CreateDirectory(ExportFolder); OpenFolder(ExportFolder); }
    private async Task<bool> Dialog(string title, string message, bool question)
    {
        var window = new Window { Title = title, Width = 660, MaxHeight = 650, SizeToContent = SizeToContent.Height, WindowStartupLocation = WindowStartupLocation.CenterOwner, CanResize = false };
        var no = new Button { Content = question ? "Cancel" : "OK", IsDefault = true, IsCancel = true }; no.Click += (_, _) => window.Close(false);
        var buttons = Row(no);
        if (question) { var yes = new Button { Content = "Continue" }; yes.Click += (_, _) => window.Close(true); buttons.Children.Add(yes); }
        window.Content = new StackPanel { Margin = new Thickness(24), Spacing = 18, Children = {
            new ScrollViewer { MaxHeight = 480, Content = Text(message) }, buttons } };
        return await window.ShowDialog<bool>(this);
    }
}
