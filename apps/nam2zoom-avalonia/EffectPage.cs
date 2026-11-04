using System.Text.Json;
using System.Text.RegularExpressions;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using Nam2ZoomDesktop;

namespace Nam2Zoom;

public sealed partial class MainWindow
{
    private sealed class EffectChoice(ModelSelection model) { public ModelSelection Model = model; public bool Selected; }
    private readonly List<EffectChoice> effectChoices = [];
    private readonly TextBlock effectSelection = Text("Select 1–5 retrained NAM files", 13, true);
    private readonly TextBlock buildDetails = Text("No effect built yet. Select retrained models and choose Build effect.", 13, true);
    private readonly TextBlock pedalDetails = Text("Pedal status not checked", 13, true);
    private readonly CheckBox effectBackup = new() { Content = new TextBlock { Text = "Full backup before install / uninstall", Margin = new Thickness(10,0,0,0), VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap }, IsChecked = true };
    private readonly CheckBox compactEffectMode = new() { Content = new TextBlock { Text = "Compact — lower DSP, more room for effects", Margin = new Thickness(10,0,0,0), VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap }, IsChecked = false };
    private readonly ComboBox effectSlotChoice = new() { ItemsSource = EffectSlot.All, SelectedIndex = 0, HorizontalAlignment = HorizontalAlignment.Stretch };
    private readonly TextBox effectName = new() { Text = "N2Z Bank", MaxLength = 8, PlaceholderText = "Effect name" };
    private readonly CheckBox effectNameArtwork = new() { Content = new TextBlock { Text = "Show effect name on amp artwork", Margin = new Thickness(10,0,0,0) }, IsChecked = true };
    private EffectSlot SelectedEffectSlot => (EffectSlot)effectSlotChoice.SelectedItem!;
    private Button buildEffectButton = null!, installEffectButton = null!, uninstallEffectButton = null!;
    private BankResult? builtEffect;
    private bool? bankInstalled, deviceSupported;
    private string EffectsFolder => Path.Combine(ExportBase, "Built_effects");

    private void BuildEffectPage()
    {
        sharePage.Margin = new Thickness(0,0,0,14);
        var workspace = new Grid { ColumnDefinitions = new("3*,16,2*") };
        var modelsPanel = new Grid { RowDefinitions = new("Auto,Auto,Auto,*") };
        Place(modelsPanel, Row(Glyph("database", 26), Heading("Models for N2Z Bank")));
        var tools = new WrapPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0,14,0,10) };
        foreach (var button in new[] {
            ActionButton("Add retrained NAMs", "plus", AddEffectModels),
            ActionButton("Refresh Converted_NAM", "folder", () => { RefreshEffectModels(); return Task.CompletedTask; }),
            UtilityButton("Open Converted_NAM", "folder", OpenExports) }) {
            button.Margin = new Thickness(0,0,8,6); tools.Children.Add(button);
        }
        busyControls.Add(tools); Place(modelsPanel, tools, 1);
        Place(modelsPanel, new StackPanel { Spacing = 8, Children = {
            Text("Choose up to five A2 Lite 44.1 kHz models. Give each a unique 1–6 character label for the pedal’s Model control. Building does not retrain or write to a pedal.", 13, true),
            effectSelection } }, 2);
        Place(modelsPanel, new ScrollViewer { Content = exportsPanel, Margin = new Thickness(0,16,0,0) }, 3);
        busyControls.Add(exportsPanel);
        Place(workspace, Card(modelsPanel));

        buildEffectButton = ActionButton("Build effect", "database", BuildSelectedEffect, "primary");
        installEffectButton = ActionButton("Install built effect", "download", InstallBuiltEffect, "primary");
        uninstallEffectButton = ActionButton("Uninstall selected slot", "trash", UninstallEffect, "danger");
        compactEffectMode.IsCheckedChanged += (_,_) => { InvalidateBuiltEffect(); UpdateEffectActions(); };
        effectSlotChoice.SelectionChanged += (_,_) => {
            InvalidateBuiltEffect(); bankInstalled = null;
            effectName.Text = SelectedEffectSlot.DefaultName;
            pedalDetails.Text = "Check pedal for " + SelectedEffectSlot;
            UpdateEffectActions();
        };
        effectName.TextChanged += (_,_) => { InvalidateBuiltEffect(); UpdateEffectActions(); };
        effectNameArtwork.IsCheckedChanged += (_,_) => { InvalidateBuiltEffect(); UpdateEffectActions(); };
        var actions = new StackPanel { Spacing = 14, Children = {
            Row(Glyph("gear"), Heading("Build & install")),
            Text("N2Z Bank · full A2 Lite · 44.1 kHz · 1–5 models", 15),
            Text("Effect slot", 13, true), effectSlotChoice,
            Text("Effect name (1–8 letters, digits, spaces, - or _)", 13, true), effectName, effectNameArtwork,
            Text("Each slot has its own effect ID and filename. Install or replace only that slot; the other two stay installed. Multiple active NAM effects still share the pedal’s DSP budget.", 12, true),
            compactEffectMode,
            Text("Compact lowers DSP demand to leave more room for other effects. Tone and dynamics may change; it adds about 1.45 ms latency. Retrained NAM files stay full A2 Lite at 44.1 kHz. Unchecked uses Full fidelity.", 13, true),
            buildEffectButton, installEffectButton, uninstallEffectButton,
            Row(ActionButton("Load built effect…", "folder", LoadBuiltEffect), UtilityButton("Open build folder", "folder", () => { Directory.CreateDirectory(EffectsFolder); OpenFolder(builtEffect?.Directory ?? EffectsFolder); })),
            new Border { Height = 1, Background = Brush.Parse("#2C414F"), Margin = new Thickness(0,8) },
            Row(Glyph("chip"), Heading("Pedal", 18)), pedalDetails,
            ActionButton("Check pedal / installed bank", "info", CheckEffectPedal), effectBackup,
            buildDetails,
            Text("Direct installation profiles: MS-50G+ 1.40, MS-70CDR+ 1.20, and MS-60B+ 1.20. New control layouts require pedal audio testing.", 12, true),
            Text("Installation replaces only the selected slot. Before install or removal, remove that slot from saved patches and select a stock-only current patch. Autosave, patch checks, backups and readback verification remain enforced.", 12, true) } };
        busyControls.Add(effectSlotChoice); busyControls.Add(effectName); busyControls.Add(effectNameArtwork);
        busyControls.Add(buildEffectButton); busyControls.Add(installEffectButton); busyControls.Add(uninstallEffectButton); busyControls.Add(effectBackup); busyControls.Add(compactEffectMode);
        Place(workspace, Card(new ScrollViewer { Content = actions }), col: 2);
        sharePage.Children.Add(workspace);
        RefreshEffectModels();
    }
    private void RefreshEffectModels()
    {
        if (buildEffectButton is null) return;
        try {
            var paths = Directory.Exists(ExportFolder) ? Directory.EnumerateFiles(ExportFolder, "*", SearchOption.TopDirectoryOnly)
                .Where(p => p.EndsWith(".nam", StringComparison.OrdinalIgnoreCase)).OrderBy(p => p).ToArray() : [];
            foreach (var path in paths) AddEffectChoice(path);
            if (effectChoices.RemoveAll(c => !File.Exists(c.Model.Path)) > 0) InvalidateBuiltEffect();
            RenderEffectModels();
        } catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) {
            Report("Converted_NAM could not be read: " + ex.Message);
        }
    }
    private void AddEffectChoice(string path)
    {
        path = Path.GetFullPath(path);
        if (effectChoices.Any(c => string.Equals(c.Model.Path, path, OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))) return;
        var stem = Regex.Replace(Path.GetFileNameWithoutExtension(path).ToUpperInvariant(), "[^A-Z0-9]", "");
        var label = stem.Length == 0 ? "AMP" : stem[..Math.Min(6, stem.Length)];
        var basis = label;
        for (var n = 1; effectChoices.Any(c => c.Model.Label == label); n++) {
            var suffix = n.ToString(System.Globalization.CultureInfo.InvariantCulture);
            label = basis[..Math.Min(basis.Length, Math.Max(0,6-suffix.Length))] + suffix;
        }
        effectChoices.Add(new(new() { Path = path, Label = label, ModelProfile = "lite", SampleRate = 44100 }));
    }
    private void RenderEffectModels()
    {
        exportsPanel.Children.Clear();
        if (effectChoices.Count == 0) exportsPanel.Children.Add(Text("Retrain models first, or add existing retrained NAM files. Converted_NAM files appear here automatically.", 14, true));
        foreach (var choice in effectChoices) {
            var row = new Grid { ColumnDefinitions = new("32,*,92,84"), Margin = new Thickness(0,2) };
            var check = new CheckBox { IsChecked = choice.Selected, VerticalAlignment = VerticalAlignment.Center };
            check.IsCheckedChanged += (_,_) => { if (choice.Selected != (check.IsChecked == true)) { choice.Selected = check.IsChecked == true; InvalidateBuiltEffect(); } UpdateEffectActions(); };
            Place(row, check);
            var title = new StackPanel { Spacing = 4, Children = { Text(Path.GetFileName(choice.Model.Path), 14), Text(choice.Model.Path, 11, true) } };
            Place(row, title, col: 1);
            var label = new TextBox { Text = choice.Model.Label, MaxLength = 6, PlaceholderText = "Label", Margin = new Thickness(6,0), VerticalAlignment = VerticalAlignment.Center };
            label.TextChanged += (_,_) => {
                var normalized = Regex.Replace(label.Text ?? "", "[^A-Za-z0-9_-]", "").ToUpperInvariant();
                if (choice.Model.Label == normalized) return;
                choice.Model.Label = normalized; if (label.Text != normalized) label.Text = normalized;
                InvalidateBuiltEffect(); UpdateEffectActions();
            };
            ToolTip.SetTip(label, "Unique label shown in the pedal’s Model selector (1–6 characters).");
            Place(row, label, col: 2);
            var up = NewButton("Move model up", "plus"); up.Content = "↑";
            var down = NewButton("Move model down", "plus"); down.Content = "↓";
            foreach (var button in new[] { up, down }) {
                button.Width = button.Height = button.MinWidth = button.MinHeight = 34;
                button.Padding = new Thickness(0);
                button.HorizontalContentAlignment = HorizontalAlignment.Center;
                button.VerticalContentAlignment = VerticalAlignment.Center;
                button.FontSize = 18;
            }
            up.IsEnabled = effectChoices.IndexOf(choice) > 0;
            down.IsEnabled = effectChoices.IndexOf(choice) < effectChoices.Count - 1;
            ToolTip.SetTip(up, "Move model up"); ToolTip.SetTip(down, "Move model down");
            up.Click += (_,_) => MoveEffectChoice(choice, -1); down.Click += (_,_) => MoveEffectChoice(choice, 1);
            Place(row, new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, Children = { up, down } }, col: 3);
            exportsPanel.Children.Add(Card(row, 12));
        }
        UpdateEffectActions();
    }
    private void MoveEffectChoice(EffectChoice choice, int direction)
    {
        if (busy) return;
        var index = effectChoices.IndexOf(choice); var target = index + direction;
        if (target < 0 || target >= effectChoices.Count) return;
        (effectChoices[index], effectChoices[target]) = (effectChoices[target], effectChoices[index]);
        InvalidateBuiltEffect(); RenderEffectModels();
    }
    private void InvalidateBuiltEffect()
    {
        if (builtEffect is not null) buildDetails.Text = "Models, labels or build mode changed. Build again, or load a previously built effect.";
        builtEffect = null;
    }
    private void UpdateEffectActions()
    {
        if (buildEffectButton is null) return;
        var selected = effectChoices.Where(c=>c.Selected).Select(c=>c.Model).ToArray();
        var validLabels = selected.All(m => Regex.IsMatch(m.Label, "^[A-Z0-9_-]{1,6}$")) && selected.Select(m=>m.Label).Distinct().Count() == selected.Length;
        effectSelection.Text = $"{selected.Length} / {ReadyEffectService.MaximumModels} selected" + (validLabels ? " · labels become pedal model names" : " · use unique 1–6 character labels");
        buildEffectButton.IsEnabled = !busy && selected.Length >= 1 && selected.Length <= ReadyEffectService.MaximumModels && validLabels && Regex.IsMatch(effectName.Text ?? "", "^[A-Za-z0-9 _-]{1,8}$") && effectName.Text == effectName.Text?.Trim();
        installEffectButton.IsEnabled = !busy && builtEffect is not null && deviceSupported != false;
        uninstallEffectButton.IsEnabled = !busy && bankInstalled == true && deviceSupported == true;
    }
    private async Task AddEffectModels()
    {
        var files = await StorageProvider.OpenFilePickerAsync(new() { Title = "Choose retrained A2 Lite 44.1 kHz NAM files", AllowMultiple = true,
            FileTypeFilter = [new("Neural Amp Modeler") { Patterns = ["*.nam"] }] });
        foreach (var file in files) {
            if (file.TryGetLocalPath() is not { } path) continue;
            var model = new ModelSelection { Path = path };
            await vm.Conversions.InspectAsync(model, cancellation!.Token);
            if (model.Status != "direct") throw new InvalidDataException(Path.GetFileName(path) + " needs retraining. Use the Retrain page first.");
            AddEffectChoice(path);
        }
        RenderEffectModels();
    }
    private async Task BuildSelectedEffect()
    {
        var selected = effectChoices.Where(c=>c.Selected).Select(c=>c.Model).ToArray();
        builtEffect = null; buildDetails.Text = "Building effect…";
        batchText.Text = "Building effect"; activity.Text = "Packaging retrained models";
        try { builtEffect = await vm.Effects.BuildAsync(selected, EffectsFolder, Report, cancellation!.Token, compactEffectMode.IsChecked == true, SelectedEffectSlot.Number, effectName.Text, effectNameArtwork.IsChecked == true); }
        catch { buildDetails.Text = "Build did not complete. See the activity log."; batchText.Text = "Build stopped"; activity.Text = "No new effect built"; throw; }
        progress.Value = 100;
        ShowBuiltEffect();
        Report("Effect built: " + builtEffect.Effect);
        activity.Text = "Effect built and ready for installation";
    }
    private void ShowBuiltEffect()
    {
        if (builtEffect is null) return;
        buildDetails.Text = $"{ReadyEffectService.NameFor(builtEffect)} · {ReadyEffectService.SlotFor(builtEffect)}\n\nBuilt effect:\n" + builtEffect.Effect + "\n\nCompanion icon:\n" + builtEffect.Icon;
        try {
            var reportPath = Path.Combine(builtEffect.Directory, "engine-report.json");
            if (File.Exists(reportPath)) {
                using var document = JsonDocument.Parse(File.ReadAllText(reportPath));
                var root = document.RootElement;
                if (root.TryGetProperty("effectMode", out var mode) && root.TryGetProperty("declaredDspLoad", out var load))
                    buildDetails.Text = $"Built mode: {(mode.GetString() == "compact" ? "Compact" : "Full")} · declared load {load.GetInt32()} / 270\n\n" + buildDetails.Text;
            }
        } catch (Exception ex) when (ex is IOException or JsonException or InvalidOperationException) { }
        UpdateEffectActions();
    }
    private async Task LoadBuiltEffect()
    {
        var file = (await StorageProvider.OpenFilePickerAsync(new() { Title = "Choose a built NAM slot ZD2 with its companion ZIC",
            FileTypeFilter = [new("Zoom effect") { Patterns = ["*.ZD2", "*.zd2"] }] })).FirstOrDefault()?.TryGetLocalPath();
        if (file is null) return;
        var loaded = ReadyEffectService.Load(file);
        effectSlotChoice.SelectedIndex = ReadyEffectService.SlotFor(loaded).Number - 1;
        effectName.Text = ReadyEffectService.NameFor(loaded);
        builtEffect = loaded; bankInstalled = null; ShowBuiltEffect();
        Report("Loaded built effect for approval: " + builtEffect.Effect);
    }
    private async Task CheckEffectPedal()
    {
        batchText.Text = "Checking pedal";
        var probe = await vm.Backend.ProbeDeviceAsync(cancellation!.Token); probe.RequireSuccess();
        using var document = JsonDocument.Parse(probe.Output);
        var info = document.RootElement;
        deviceSupported = info.GetProperty("status").GetString() == "connected";
        pedalDetails.Text = info.GetProperty("message").GetString() ?? "Pedal unavailable";
        bankInstalled = null;
        if (deviceSupported == true) {
            var files = await vm.Backend.ExecuteAsync(vm.Paths.Python, ["-B", Path.Combine(vm.Paths.Resources,"tools","msplus.py"), "--timeout", "3", "list-files"], token: cancellation.Token);
            files.RequireSuccess();
            bankInstalled = files.Output.Split('\n').Any(line => line.Trim().Equals(SelectedEffectSlot.Filename, StringComparison.OrdinalIgnoreCase));
            pedalDetails.Text += bankInstalled == true ? $"\n{SelectedEffectSlot.Filename} detected; catalogue is verified before writes" : $"\n{SelectedEffectSlot.Filename} not found";
        }
        batchText.Text = "Pedal check complete"; activity.Text = pedalDetails.Text;
        Report(pedalDetails.Text); UpdateEffectActions();
    }
    private string EffectSafetyText() => $"This changes {SelectedEffectSlot.Filename} ({SelectedEffectSlot}) on the pedal. "
        + (effectBackup.IsChecked == true ? "A full backup will be saved in " + vm.Paths.Backup + ". " : "Only effect-list and bank recovery files will be retained. ")
        + "Remove the selected slot from saved patches and select a stock-only patch before continuing. Other NAM slots in saved patches may remain. "
        + "The backend verifies the supported identity, autosave OFF, target-slot patch checks and uploaded readback. "
        + "Custom effects can crackle, freeze or permanently disable a pedal. "
        + "Keep the app open and the pedal powered and connected; transfer cannot be cancelled. "
        + "New Full builds declare 260 / 270; Compact builds declare 190 / 270. These are admission reservations, not measured DSP percentages. Compact can change tone and dynamics. Test the built effect before saving a patch.";
    private async Task InstallBuiltEffect()
    {
        var approved = builtEffect ?? throw new InvalidDataException("Build or load an effect first.");
        if (!await Dialog("Approve built effect installation", EffectSafetyText()
            + "\n\nOnly the selected slot will be replaced if present.\n\nZD2 SHA-256:\n" + approved.EffectHash
            + "\n\nZIC SHA-256:\n" + approved.IconHash + "\n\nInstall this exact effect and icon?", true)) return;
        deviceBusy = true; cancel.IsEnabled = false; batchText.Text = "Installing effect";
        try { await vm.Effects.InstallAsync(approved, effectBackup.IsChecked == true, Report); }
        catch { deviceSupported = false; bankInstalled = null; pedalDetails.Text = "Installation stopped. Review recovery/session logs before retrying."; batchText.Text = "Install stopped"; throw; }
        progress.Value = 100;
        bankInstalled = true; deviceSupported = true;
        pedalDetails.Text = $"{ReadyEffectService.NameFor(approved)} ({ReadyEffectService.SlotFor(approved)}) installed and readback verified";
        activity.Text = "Installation verified"; Report(pedalDetails.Text);
        await Dialog("Installation complete", $"{ReadyEffectService.NameFor(approved)} ({ReadyEffectService.SlotFor(approved)}) is installed and verified, or was already installed with identical bytes. Test in an unsaved patch; add effects gradually and listen for glitches. Declared load is not measured DSP usage.", false);
    }
    private async Task UninstallEffect()
    {
        if (!await Dialog("Approve selected NAM slot removal", EffectSafetyText() + "\n\nRemove only the selected NAM slot?", true)) return;
        deviceBusy = true; cancel.IsEnabled = false; batchText.Text = "Removing effect";
        try { await vm.Effects.UninstallAsync(effectBackup.IsChecked == true, Report, SelectedEffectSlot.Number); }
        catch { deviceSupported = false; bankInstalled = null; pedalDetails.Text = "Removal stopped. Review recovery/session logs before retrying."; batchText.Text = "Removal stopped"; throw; }
        progress.Value = 100;
        bankInstalled = false; pedalDetails.Text = $"{SelectedEffectSlot.Filename} removed or already absent; other slots unchanged";
        activity.Text = "Removal finished"; Report(pedalDetails.Text);
        await Dialog("Removal complete", pedalDetails.Text, false);
    }
}
