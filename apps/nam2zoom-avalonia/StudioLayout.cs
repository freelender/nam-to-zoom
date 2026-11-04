using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Templates;
using Avalonia.Data;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Input.Platform;
using Nam2ZoomDesktop;

namespace Nam2Zoom;

public sealed partial class MainWindow
{
    private readonly TextBlock emptyHint = Text("Add NAM files to your retraining queue", 18, true);
    private readonly TextBlock selectionText = Text("0 selected", 12, true);
    private readonly Grid retrainPage = new();
    private readonly Grid sharePage = new();
    private readonly Grid settingsPage = new();
    private readonly Grid aboutPage = new();
    private readonly StackPanel pedalCompatibility = new() { Spacing = 10, Margin = new Thickness(-18, 0, -14, 0), IsVisible = false };
    private readonly TextBlock outputFormatValue = Text("A2 Lite  ·  44.1 kHz  ·  Zoom-ready NAM", 12, true);
    private readonly TextBlock outputFormatHint = Text("Preserves a learned approximation of the capture’s sound", 11, true);
    private readonly TextBlock pageTitle = Heading("Retrain NAM files", 28);
    private readonly TextBlock pageSubtitle = Text("Convert your NAM captures into Zoom-ready models (A2 Lite, 44.1 kHz).", 14, true);

    private void BuildStudioLayout()
    {
        var shell = new Grid { ColumnDefinitions = new("238,*"), Background = Brush.Parse("#0C151D") };
        Place(shell, BuildSidebar());
        var main = new Grid { RowDefinitions = new("Auto,*,160,Auto"), Margin = new Thickness(16, 18, 16, 0) };
        var top = new Grid { ColumnDefinitions = new("*,380"), Margin = new Thickness(4, 0, 0, 18) };
        Place(top, Row(Glyph("wave", 40), new StackPanel { Spacing = 5, Children = { pageTitle, pageSubtitle } }));
        Place(top, Card(Row(Glyph("database", 30), new StackPanel { Spacing = 5, Children = {
            Text("Output format", 13), outputFormatValue, outputFormatHint } }), 15), col: 1);
        Place(main, top);
        BuildRetrainPage(); BuildSecondaryPages();
        pageHost.Children.Add(retrainPage); pageHost.Children.Add(sharePage); pageHost.Children.Add(settingsPage); pageHost.Children.Add(aboutPage);
        Place(main, pageHost, 1);
        Place(main, BuildLog(), 2);
        var footer = new Grid { ColumnDefinitions = new("Auto,18,270,18,*,Auto"), MinHeight = 48, Margin = new Thickness(12, 0, 4, 0) };
        activity.TextWrapping = TextWrapping.NoWrap; activity.TextTrimming = TextTrimming.CharacterEllipsis;
        Place(footer, batchText); Place(footer, progress, col: 2); Place(footer, activity, col: 4);
        cancel.Content = Row(Glyph("stop", 16, Brush.Parse("#FF707A")), Text("Cancel all", 13)); cancel.Classes.Add("danger");
        Place(footer, cancel, col: 5); Place(main, footer, 3);
        Place(shell, main, col: 1);
        Content = shell;
        Navigate("Retrain");
        changingDevice = true;
        trainingDevice.ItemsSource = OperatingSystem.IsWindows()
            ? new[] { new DeviceChoice("CPU", false), new DeviceChoice("NVIDIA GPU (CUDA)", true) } : [new DeviceChoice("CPU", false)];
        trainingDevice.SelectedIndex = vm.Paths.TrainingDevice == "cuda" ? 1 : 0;
        changingDevice = false;
    }
    private Control BuildSidebar()
    {
        var sidebar = new Grid { RowDefinitions = new("Auto,Auto,*,Auto"), Margin = new Thickness(18, 26, 14, 26) };
        var logoText = Row(Text("nam2", 28), new TextBlock { Text = "zoom", FontSize = 28, Foreground = Brush.Parse("#2C8CFF"), VerticalAlignment = VerticalAlignment.Center }); logoText.Spacing = 0;
        Place(sidebar, Row(Glyph("wave", 36), logoText));
        var nav = new StackPanel { Spacing = 12, Margin = new Thickness(0, 50, 0, 0) };
        foreach (var (name, icon) in new[] { ("Retrain","home"), ("Build effect","database"), ("Settings","gear"), ("About","info") }) {
            var button = NewButton(name, icon); button.Classes.Add("nav");
            button.HorizontalAlignment = HorizontalAlignment.Stretch; button.HorizontalContentAlignment = HorizontalAlignment.Left;
            button.Click += (_, _) => Navigate(name); navigation[name] = button; nav.Children.Add(button);
        }
        Place(sidebar, nav, 1);
        pedalCompatibility.Children.Add(PedalArt());
        pedalCompatibility.Children.Add(new StackPanel { Spacing = 10, Margin = new Thickness(36, 0, 18, 0), Children = {
            Text("Compatible with", 12, true), Text("Zoom MS-50G+", 13, true),
            Text("Zoom MS-70CDR+", 13, true), Text("Zoom MS-60B+", 13, true) } });
        Place(sidebar, pedalCompatibility, 3);
        return new Border { Background = Brush.Parse("#0E1821"), BorderBrush = Brush.Parse("#243643"), BorderThickness = new Thickness(0,0,1,0), Child = sidebar };
    }
    private void BuildRetrainPage()
    {
        retrainPage.RowDefinitions = new("*,Auto");
        var workspace = new Grid { ColumnDefinitions = new("*,16,350"), Margin = new Thickness(0,0,0,14) };
        Place(workspace, BuildQueue()); Place(workspace, BuildTrainingSettings(), col: 2);
        Place(retrainPage, workspace); Place(retrainPage, BuildShareCard(), 1);
        retrainPage.Margin = new Thickness(0,0,0,14);
    }
    private Control BuildQueue()
    {
        var queueBody = new Grid { RowDefinitions = new("Auto,Auto,*") };
        var title = Row(Glyph("database", 27), Heading("Retraining queue"), new Border { CornerRadius = new CornerRadius(12), BorderBrush = Brush.Parse("#45647C"), BorderThickness = new Thickness(1), Padding = new Thickness(8,2), Child = modelCount });
        var header = new Grid { ColumnDefinitions = new("*,Auto"), RowDefinitions = new("Auto,Auto"), Margin = new Thickness(0,0,0,14) };
        Place(header, title);
        var tools = new WrapPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        foreach (var button in new[] { ActionButton("Add NAM files", "plus", PickFiles, "primary"), ActionButton("Add folder", "folder", PickFolder),
            ActionButton("Remove", "trash", () => { foreach (var item in vm.Models.Where(i=>i.IsSelected).ToArray()) vm.Models.Remove(item); return Task.CompletedTask; }),
            ActionButton("Clear", "clear", () => { vm.Models.Clear(); return Task.CompletedTask; }, "danger") }) {
            button.Margin = new Thickness(6,0,0,4); tools.Children.Add(button);
        }
        busyControls.Add(tools); Place(header, tools, col: 1);
        header.SizeChanged += (_,_) => {
            var narrow = header.Bounds.Width < 860;
            Grid.SetRow(tools, narrow ? 1 : 0); Grid.SetColumn(tools, narrow ? 0 : 1); Grid.SetColumnSpan(tools, narrow ? 2 : 1);
            tools.Margin = new Thickness(0,narrow?10:0,0,0);
        };
        Place(queueBody, header);
        Place(queueBody, Row(Text("Add NAM files and convert them one by one. Each file is retrained separately.", 12, true), selectionText), 1);
        var table = new Grid { RowDefinitions = new("42,*"), Margin = new Thickness(0,14,0,0) };
        var columns = new Grid { ColumnDefinitions = new("30,36,1.4*,1*,1.3*,1.5*,1.1*"), Margin = new Thickness(10,0) };
        selectAll.IsThreeState = true;
        Place(columns, selectAll); Place(columns, Text("#", 12, true), col: 1); Place(columns, Text("NAM file", 12, true), col: 2);
        Place(columns, Text("Input rate", 12, true), col: 3); Place(columns, Text("Status", 12, true), col: 4);
        Place(columns, Text("Progress", 12, true), col: 5); Place(columns, Text("Actions", 12, true), col: 6);
        Place(table, columns);
        models.ItemTemplate = new FuncDataTemplate<RetrainingItem>((item, _) => item is null ? new Border() : BuildQueueRow(item));
        var list = new Grid(); list.Children.Add(models);
        emptyHint.HorizontalAlignment = HorizontalAlignment.Center; emptyHint.VerticalAlignment = VerticalAlignment.Center; list.Children.Add(emptyHint);
        Place(table, list, 1);
        Place(queueBody, new Border { BorderBrush = Brush.Parse("#283A49"), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(7), ClipToBounds = true, Child = table }, 2);
        return Card(queueBody, 16);
    }
    private Control BuildQueueRow(RetrainingItem item)
    {
        var row = new Grid { ColumnDefinitions = new("30,36,1.4*,1*,1.3*,1.5*,1.1*"), MinHeight = 44, Margin = new Thickness(10,0) };
        var check = new CheckBox(); check.Bind(CheckBox.IsCheckedProperty, new Binding(nameof(RetrainingItem.IsSelected)) { Source = item, Mode = BindingMode.TwoWay });
        Place(row, check);
        var number = Text("", 12, true); number.Bind(TextBlock.TextProperty, new Binding(nameof(RetrainingItem.Number)) { Source = item }); Place(row, number, col: 1);
        var name = Text(item.Name, 13); name.TextWrapping = TextWrapping.NoWrap; name.TextTrimming = TextTrimming.CharacterEllipsis;
        ToolTip.SetTip(name, item.Model.Path); Place(row, name, col: 2);
        Place(row, Text(item.InputRate, 12), col: 3);
        var state = Text("", 12); state.Foreground = item.IsRunning ? Blue : Brush.Parse("#EDF4FC"); state.Bind(TextBlock.TextProperty, new Binding(nameof(RetrainingItem.State)) { Source = item });
        var stateIcon = Glyph(item.IsRunning ? "spinner" : "clock", 17, item.IsRunning ? Blue : Brush.Parse("#B9CADA")); Place(row, Row(stateIcon, state), col: 4);
        var bar = new ProgressBar { MinWidth = 0, Height = 13, Minimum = 0, Maximum = 100, HorizontalAlignment = HorizontalAlignment.Stretch };
        bar.Bind(ProgressBar.ValueProperty, new Binding(nameof(RetrainingItem.Progress)) { Source = item });
        var percent = Text("", 11, true); percent.Bind(TextBlock.TextProperty, new Binding(nameof(RetrainingItem.ProgressText)) { Source = item });
        var meter = new Grid { ColumnDefinitions = new("*,36"), Margin = new Thickness(0,0,12,0) };
        percent.Margin = new Thickness(8,0,0,0); Place(meter, bar); Place(meter, percent, col: 1); Place(row, meter, col: 5);
        var stop = NewButton("Cancel", "stop", "danger"); stop.Content = Row(Glyph("stop", 13, Brush.Parse("#FF707A")), Text("Cancel", 11)); stop.Padding = new Thickness(5,3); stop.Height = 29; stop.MinHeight = 29;
        stop.Bind(IsVisibleProperty, new Binding(nameof(RetrainingItem.IsRunning)) { Source = item }); stop.Click += (_,_) => queue.Cancel(item);
        var menu = new Button { Content = "⋮", FontSize = 22, Padding = new Thickness(6,0), Height = 30, MinHeight = 30, Background = Brushes.Transparent, BorderThickness = new Thickness(0) };
        var options = new ContextMenu();
        MenuItem AsyncOption(string label, Func<Task> action) { var entry = new MenuItem { Header = label }; entry.Click += async (_,_) => { try { await action(); } catch (Exception ex) { await Dialog("Action stopped", ex.Message, false); } }; options.Items.Add(entry); return entry; }
        MenuItem Option(string label, Action action) => AsyncOption(label, () => { action(); return Task.CompletedTask; });
        Option("Open source folder", () => OpenFolder(Path.GetDirectoryName(item.Model.Path)!));
        Option("Open exported NAM folder", () => { if (item.OutputPath is { } path && File.Exists(path)) OpenFolder(Path.GetDirectoryName(path)!); else OpenExports(); });
        AsyncOption("Open A/B preview", async () => { if (item.PreviewPath is { } path && Directory.Exists(path)) OpenFolder(path); else await Dialog("A/B preview", "A preview is available after a conversion reaches quality review. Cached previews are retained in the user-data folder.", false); });
        AsyncOption("Copy source path", async () => { if (Clipboard is { } clipboard) await clipboard.SetTextAsync(item.Model.Path); });
        var skip = Option("Cancel / skip this file", () => queue.Cancel(item)); skip.Bind(IsEnabledProperty, new Binding(nameof(RetrainingItem.CanCancel)) { Source = item });
        var retry = AsyncOption("Retrain this file", async () => { if (!busy) { item.IsSelected = true; await Run(() => Convert([item])); } });
        var remove = Option("Remove from queue", () => { if (!busy) vm.Models.Remove(item); });
        menu.Click += (_,_) => { retry.IsEnabled = !busy; remove.IsEnabled = !busy; options.Open(menu); };
        var rowActions = new Grid { ColumnDefinitions = new("*,26") };
        stop.HorizontalAlignment = HorizontalAlignment.Right; Place(rowActions, stop); Place(rowActions, menu, col: 1);
        Place(row, rowActions, col: 6);
        item.PropertyChanged += (_, e) => {
            if (e.PropertyName == nameof(RetrainingItem.State)) {
                ((Avalonia.Controls.Shapes.Path)stateIcon).Stroke = item.IsRunning ? Blue : Brush.Parse(item.State=="Failed"?"#FF737F":"#B9CADA");
                ((Avalonia.Controls.Shapes.Path)stateIcon).Data = Geometry.Parse(item.IsRunning ? "M22,12 A10,10 0 1 1 12,2" : "M23,12 A11,11 0 1 1 1,12 A11,11 0 1 1 23,12 M12,5 L12,13 L18,16");
                state.Foreground = item.IsRunning ? Blue : Brush.Parse("#EDF4FC");
                ToolTip.SetTip(state, item.Error ?? item.State);
            }
        };
        return new Border { BorderBrush = Brush.Parse("#243540"), BorderThickness = new Thickness(0,0,0,1), Child = row };
    }
    private Control BuildTrainingSettings()
    {
        epochs.Height = 40; epochs.HorizontalAlignment = HorizontalAlignment.Stretch;
        trainingDevice.Height = 40;
        ToolTip.SetTip(epochs, "An epoch is one pass through the training audio. More epochs take longer and may improve fidelity. Compatible cached conversions are reused.");
        var settings = new StackPanel { Spacing = 16, Children = {
            Row(Glyph("gear"), Heading("Retraining settings")),
            Text("Training epochs", 13, true), epochs, Text("Training device", 13, true), trainingDevice,
            new Border { BorderBrush = Brush.Parse("#255982"), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(6), Padding = new Thickness(14), Background = Brush.Parse("#142638"),
                Child = new Grid { ColumnDefinitions = new("24,12,*"), Children = { } } } } };
        var note = (Grid)((Border)settings.Children[^1]).Child!;
        Place(note, Glyph("info", 21));
        Place(note, new StackPanel { Spacing = 14, Children = {
            Text("Conversion quality is measured using separate test audio. If a result falls below the quality limits, listen to the A/B preview before choosing whether to export it.", 12, true),
            Text("Already compatible 44.1 kHz files are exported without retraining.", 12, true) } }, col: 2);
        busyControls.Add(epochs); busyControls.Add(trainingDevice);
        return Card(new ScrollViewer { Content = settings, HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled }, 20);
    }
    private Control BuildShareCard()
    {
        var panel = new Grid { ColumnDefinitions = new("*,20,440") };
        Place(panel, Row(Glyph("share", 30), new StackPanel { Spacing = 10, Children = {
            Heading("Share your Zoom-ready NAM files"),
            Text("These Zoom-ready NAM files (A2 Lite at 44.1 kHz) can be shared with others without retraining again.", 12, true),
            Text("Share models you have permission to redistribute. To load one onto a compatible Zoom pedal, use https://sym.bios.is/?open=nam. sym.bios.is does not host or share retrained NAM models.", 12, true) } }));
        var actions = new Grid { ColumnDefinitions = new("*,12,*"), RowDefinitions = new("44,10,40") };
        var convert = ActionButton("Retrain & export NAMs", "download", () => Convert(), "primary");
        var folder = UtilityButton("Open output folder", "folder", OpenExports);
        var loader = UtilityButton("Load NAMs at sym.bios.is ↗", "external", OpenLoader);
        busyControls.Add(convert);
        Place(actions, convert); Place(actions, folder, col: 2); Place(actions, loader, 2); Grid.SetColumnSpan(loader, 3);
        Place(panel, actions, col: 2);
        return Card(panel, 18);
    }
    private Control BuildLog()
    {
        var grid = new Grid { RowDefinitions = new("Auto,*") };
        var header = new Grid { ColumnDefinitions = new("*,Auto,12,Auto"), Margin = new Thickness(0,0,0,8) };
        Place(header, Row(Glyph("file", 21), Heading("Retraining log", 16)));
        autoScroll.Content = new TextBlock { Text = "Auto scroll", FontSize = 12, Margin = new Thickness(8,0,0,0) };
        Place(header, autoScroll, col: 1);
        var clear = NewButton("Clear log", "trash"); clear.Height = 29; clear.MinHeight = 29; clear.Padding = new Thickness(10,3);
        clear.Click += (_,_) => { activityLog.ClearDisplay(); vm.Log = ""; logText.Text = ""; };
        Place(header, clear, col: 3); Place(grid, header);
        logText.FontFamily = FontFamily.Parse("Cascadia Mono, Consolas, Menlo, monospace"); logText.FontSize = 11;
        logText.TextWrapping = TextWrapping.NoWrap;
        logScroll.Content = logText; logScroll.HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto;
        Place(grid, logScroll, 1);
        return Card(grid, 14);
    }
}
