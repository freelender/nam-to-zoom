using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Data;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using Nam2ZoomDesktop;

namespace Nam2Zoom;

public sealed partial class MainWindow : Window
{
    private readonly MainViewModel vm = new();
    private readonly ListBox models = new();
    private readonly TextBox label = new() { PlaceholderText = "1–5 characters", MaxLength = 5 };
    private readonly TextBlock ir = new() { Text = "No Cab IR", TextWrapping = Avalonia.Media.TextWrapping.Wrap };
    private readonly ComboBox profile = new() { ItemsSource = new[] { "Compact", "Lite (use alone)" }, SelectedIndex = 0, HorizontalAlignment = HorizontalAlignment.Stretch };
    private readonly NumericUpDown epochs = new EpochUpDown();
    private readonly CheckBox backup = new() { Content = "Full backup before pedal changes", IsChecked = true };
    private readonly Grid controls = new() { RowDefinitions = new("*,Auto") };
    private readonly ProgressBar progress = new() { Height = 5, IsVisible = false };
    private readonly Button cancel = new() { Content = "Cancel build", IsEnabled = false };
    private CancellationTokenSource? cancellation;
    private bool busy, deviceBusy, editing, changingProfile;
    private readonly string logPath;
    private string Profile => profile.SelectedIndex == 1 ? "lite" : "compact";
    private ModelSelection? Selected => models.SelectedItem as ModelSelection;

    public MainWindow()
    {
        Title = "nam2zoom — N2Z Bank";
        Width = 1360; Height = 960; MinWidth = 1040; MinHeight = 740;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Opened += (_, _) => {
            if (Screens.ScreenFromWindow(this) is not { } screen) return;
            Width = Math.Min(Width, Math.Max(MinWidth, screen.WorkingArea.Width / RenderScaling - 40));
            Height = Math.Min(Height, Math.Max(MinHeight, screen.WorkingArea.Height / RenderScaling - 40));
            Position = new PixelPoint(screen.WorkingArea.X + (int)((screen.WorkingArea.Width - Width * RenderScaling) / 2),
                screen.WorkingArea.Y + (int)((screen.WorkingArea.Height - Height * RenderScaling) / 2));
        };
        DataContext = vm;
        Directory.CreateDirectory(Path.Combine(vm.Paths.Data, "logs"));
        logPath = Path.Combine(vm.Paths.Data, "logs", DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + ".log");
        models.ItemsSource = vm.Models;
        models.MinHeight = 180;
        models.SelectionChanged += (_, _) => Detail();
        label.TextChanged += (_, _) => {
            if (!editing && Selected is { } model) {
                var value = label.Text?.ToUpperInvariant() ?? "";
                // Avalonia can deliver TextChanged after Detail has finished.
                // Ignore that notification when the model already has this value.
                if (model.Label == value) return;
                model.Label = value;
            }
        };
        profile.SelectionChanged += async (_, _) => {
            if (changingProfile) return;
            if (!busy && vm.Models.Count > BankService.MaxModels(Profile)) {
                changingProfile = true;
                try { profile.SelectedIndex = 0; } finally { changingProfile = false; }
                SyncProfileChoices();
                await Run(async () => { await Dialog("Lite model limit", "Lite supports at most 3 NAMs. Remove models before switching to Lite.", false); });
                return;
            }
            SyncProfileChoices();
            if (IsInitialized && !busy) await Run(async () => {
                foreach (var model in vm.Models.ToArray()) await vm.Banks.InspectAsync(model, Profile);
                Refresh(Selected);
            });
        };

        BuildStudioLayout();
        Opened += (_, _) => StartPedalDetection();
        DragDrop.SetAllowDrop(this, true);
        AddHandler(DragDrop.DragOverEvent, (_, e) => e.DragEffects = busy ? DragDropEffects.None : DragDropEffects.Copy);
        AddHandler(DragDrop.DropEvent, async (_, e) => {
            if (!busy) await Run(() => Add(e.DataTransfer.TryGetFiles()?.Select(f => f.TryGetLocalPath()).OfType<string>() ?? []));
        });
        Closing += (_, e) => {
            if (deviceBusy) { e.Cancel = true; Report("Keep the app open and the pedal connected until the transfer finishes."); }
            else if (busy) { e.Cancel = true; cancellation?.Cancel(); }
        };
        Report("User data: " + vm.Paths.Data);
    }

    private static StackPanel Row(params Control[] children)
    {
        var panel = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10 };
        foreach (var child in children) panel.Children.Add(child);
        return panel;
    }
    private Button Button(string text, Func<Task> action)
    {
        var button = new Button { Content = text };
        button.Click += async (_, _) => await Run(action);
        return button;
    }
    private async Task Run(Func<Task> action)
    {
        if (busy) return;
        busy = true; foreach (var control in busyControls) control.IsEnabled = false;
        // Release detection's MIDI handles before any operation can acquire them.
        pedalProbeCancellation?.Cancel();
        await pedalProbe;
        progress.IsVisible = true; progress.IsIndeterminate = true;
        try { await action(); }
        catch (OperationCanceledException) { Report("Build cancelled. Cached conversions retained."); }
        catch (Exception ex) { Report(ex.ToString()); await Dialog("Operation stopped", ex.Message
            + (deviceBusy ? "\nKeep the pedal powered and connected. Read the recovery log before retrying." : ""), false); }
        finally { busy = false; deviceBusy = false; foreach (var control in busyControls) control.IsEnabled = true; progress.IsVisible = false; cancel.IsEnabled = false;
            cancellation?.Dispose(); cancellation = null; }
    }
    private void Report(string line) => Dispatcher.UIThread.Post(() => {
        vm.Log += line + Environment.NewLine;
        vm.Status = line;
        activity.Text = line;
        File.AppendAllText(logPath, line + Environment.NewLine);
        var match = Regex.Match(line, @"^(Patch|File) (\d+)/(\d+):");
        if (match.Success && int.TryParse(match.Groups[2].Value, out var current)
            && int.TryParse(match.Groups[3].Value, out var total) && total > 0) {
            progress.IsIndeterminate = false; progress.Value = 100.0 * current / total;
        } else progress.IsIndeterminate = true;
    });
    private async Task Add(IEnumerable<string> paths)
    {
        foreach (var path in paths) {
            if (!path.EndsWith(".nam", StringComparison.OrdinalIgnoreCase)) continue;
            if (vm.Models.Any(m => Path.GetFullPath(m.Path) == Path.GetFullPath(path))) continue;
            if (vm.Models.Count >= BankService.MaxModels(Profile))
                throw new InvalidDataException($"{Profile} supports at most {BankService.MaxModels(Profile)} NAMs.");
            var stem = Regex.Replace(Path.GetFileNameWithoutExtension(path).ToUpperInvariant(), "[^A-Z0-9]", "");
            var name = stem.Length == 0 ? "AMP" : stem[..Math.Min(5, stem.Length)];
            for (var n = 1; vm.Models.Any(m => m.Label == name); n++) name = "M" + n;
            var model = new ModelSelection { Path = Path.GetFullPath(path), Label = name, ModelProfile = Profile };
            await vm.Banks.InspectAsync(model, Profile);
            vm.Models.Add(model); models.SelectedItem = model;
        }
    }
    private void Detail()
    {
        editing = true; label.Text = Selected?.Label ?? ""; editing = false;
        ir.Text = Selected?.IrPath is { } irPath ? Path.GetFileName(irPath) : "No cabinet IR";
        ToolTip.SetTip(ir, Selected?.IrPath);
        inspector.IsEnabled = Selected is not null;
        modelName.Text = Selected is { } current ? Path.GetFileName(current.Path) : "No model selected";
        ToolTip.SetTip(modelName, Selected?.Path ?? "Add a NAM file to get started.");
    }
    private void Refresh(ModelSelection? selected)
    {
        models.ItemsSource = null; models.ItemsSource = vm.Models; models.SelectedItem = selected; Detail();
    }
    private Task Move(int direction)
    {
        var index = models.SelectedIndex;
        if (index >= 0 && index + direction >= 0 && index + direction < vm.Models.Count) {
            var selected = Selected; vm.Models.Move(index, index + direction); Refresh(selected);
        }
        return Task.CompletedTask;
    }
    private async Task SaveProject()
    {
        BankService.Validate(vm.Models.ToArray(), Profile);
        foreach (var m in vm.Models) m.ModelProfile = Profile;
        var file = await StorageProvider.SaveFilePickerAsync(new() { SuggestedFileName = "models.n2zbank.json" });
        if (file?.TryGetLocalPath() is { } path)
            await File.WriteAllTextAsync(path, JsonSerializer.Serialize(vm.Models, new JsonSerializerOptions { WriteIndented = true }));
    }
    private async Task OpenProject()
    {
        var path = (await StorageProvider.OpenFilePickerAsync(new() { FileTypeFilter = [new("Bank list") { Patterns = ["*.json"] }] }))
            .FirstOrDefault()?.TryGetLocalPath();
        if (path is null) return;
        var entries = JsonSerializer.Deserialize<List<ModelSelection>>(await File.ReadAllTextAsync(path))
            ?? throw new InvalidDataException("Empty bank list");
        BankService.Validate(entries);
        if (entries.Any(m => !File.Exists(m.Path) || (m.IrPath is not null && (!File.Exists(m.IrPath)
                || !m.IrPath.EndsWith(".wav", StringComparison.OrdinalIgnoreCase)))))
            throw new InvalidDataException("List contains a missing NAM or invalid cab IR WAV.");
        if (entries.Any(m => m.ModelProfile is not ("compact" or "lite")) || entries.Select(m => m.ModelProfile).Distinct().Count() != 1)
            throw new InvalidDataException("All list entries must use the same Compact/Lite profile.");
        var selectedProfile = entries[0].ModelProfile;
        foreach (var entry in entries) await vm.Banks.InspectAsync(entry, selectedProfile);
        profile.SelectedIndex = selectedProfile == "lite" ? 1 : 0;
        vm.Models.Clear(); foreach (var entry in entries) vm.Models.Add(entry);
        models.SelectedIndex = 0;
    }
    private async Task Build(bool install)
    {
        BankService.Validate(vm.Models.ToArray(), Profile);
        var folder = (await StorageProvider.OpenFolderPickerAsync(new() { Title = "Choose build output folder" })).FirstOrDefault()?.TryGetLocalPath();
        if (folder is null) return;
        cancellation = new(); cancel.IsEnabled = true;
        var result = await vm.Banks.BuildAsync(vm.Models.ToArray(), folder, Profile, (int)(epochs.Value ?? 100),
            async (warnings, path) => {
                if (path is not null) OpenFolder(path);
                return await Dialog("Review conversion quality", warnings + "\n\nESR lower is closer; correlation should be at least 0.95. Listen to the A/B preview. Use these conversions? Declining keeps previews and cached models.", true);
            }, Report, cancellation.Token);
        cancel.IsEnabled = false;
        if (result is null) return;
        Report("Offline build complete: " + result.Directory);
        if (!install) { await Dialog("Build complete", "Effect built in " + result.Directory
            + (Profile == "lite" ? "\nLite must run alone. Do not save Lite patches: a startup freeze has been reported." : ""), false); return; }
        if (!await Dialog("Approve exact pedal install", SafetyText()
                + $"\n\nZD2 SHA-256: {result.EffectHash}\nZIC SHA-256: {result.IconHash}\n\nInstall this exact pair?", true)) return;
        deviceBusy = true;
        await vm.Banks.InstallAsync(result, backup.IsChecked == true, Report);
        Report("Installed and independently verified. Audition in an unsaved patch first.");
        await Dialog("Installation complete", "Readback verified. Real-time audio, saved-patch and reboot behavior need separate testing."
            + (Profile == "lite" ? "\nDo not save Lite patches: a startup freeze has been reported." : ""), false);
    }
    private async Task Uninstall()
    {
        if (!await Dialog("Approve bank removal", SafetyText() + "\n\nRemove N2Z Bank?", true)) return;
        deviceBusy = true;
        await vm.Banks.UninstallAsync(backup.IsChecked == true, Report);
        await Dialog("Removal complete", "Removal finished; see the log for verification or an already-absent bank.", false);
    }
    private string SafetyText() => "This replaces/removes the entire N2Z Bank effect. "
        + (backup.IsChecked == true ? "A full device backup will be saved in " + vm.Paths.Backup + ". "
            : "No full backup will be saved; only the current effect list and bank recovery files are retained. ")
        + "Autosave OFF, supported identity/firmware and stock-only current and saved patches are required. "
        + "An existing bank is uninstalled first. The transfer cannot be cancelled: keep the pedal powered, connected, and this app open. "
        + "A custom effect can crackle, freeze or permanently disable the device. Use an unsaved patch for initial audition. "
        + "Lite must run alone. Do not save Lite patches: they can prevent startup. MS-60B+ is experimental; all macOS hardware verification is pending. "
        + "Saved-patch and reboot behavior of this build is unverified.";
    private static void OpenFolder(string path) => Process.Start(new ProcessStartInfo(
        OperatingSystem.IsMacOS() ? "/usr/bin/open" : "explorer.exe") { UseShellExecute = false, ArgumentList = { path } });
    private async Task<bool> Dialog(string title, string message, bool question)
    {
        var window = new Window { Title = title, Width = 700, MaxHeight = 650, SizeToContent = SizeToContent.Height,
            WindowStartupLocation = WindowStartupLocation.CenterOwner, CanResize = false };
        var no = new Button { Content = question ? "Cancel" : "OK", IsDefault = true, IsCancel = true };
        no.Click += (_, _) => window.Close(false);
        var buttons = Row(no);
        if (question) { var yes = new Button { Content = "Approve" }; yes.Click += (_, _) => window.Close(true); buttons.Children.Add(yes); }
        window.Content = new StackPanel { Margin = new Thickness(20), Spacing = 18, Children = {
            new ScrollViewer { MaxHeight = 480, Content = new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap } }, buttons } };
        return await window.ShowDialog<bool>(this);
    }
}
