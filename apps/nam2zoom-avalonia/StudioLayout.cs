using Avalonia;

using Avalonia.Controls;

using Avalonia.Controls.Templates;

using Avalonia.Controls.Primitives;

using Avalonia.Data;

using Avalonia.Layout;

using Avalonia.Media;

using Avalonia.Platform.Storage;

using Nam2ZoomDesktop;



namespace Nam2Zoom;



public sealed partial class MainWindow

{

    private readonly List<Control> busyControls = [];

    private readonly ToggleButton compactChoice = new() { Content = "Compact", IsChecked = true, HorizontalAlignment = HorizontalAlignment.Stretch };

    private readonly ToggleButton liteChoice = new() { Content = "Lite", HorizontalAlignment = HorizontalAlignment.Stretch };

    private readonly TextBlock modelCount = Text("0 / 10 models", muted: true);

    private readonly TextBlock modelLimitHint = Text("One to ten models • .nam files", 12, true);

    private readonly TextBlock modelName = Text("No model selected", 17);

    private readonly StackPanel inspector = new() { Spacing = 14 };

    private readonly TextBlock emptyHint = Text("Your bank is empty", 20);

    private readonly TextBlock activity = Text("Ready to build", muted: true);



    private static TextBlock Text(string text, double size = 14, bool muted = false)

    {

        var block = new TextBlock { Text = text, FontSize = size, VerticalAlignment = VerticalAlignment.Center,

            TextWrapping = TextWrapping.Wrap };

        if (muted) block.Classes.Add("muted");

        return block;

    }



    private static Border Card(Control child, Thickness? padding = null) => new() {

        Background = Brush.Parse("#1A2126"), BorderBrush = Brush.Parse("#333E47"),

        BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(9),

        Padding = padding ?? new Thickness(20), Child = child

    };

    private static Border Rule() => new() { Height = 1, Background = Brush.Parse("#354049"), Margin = new Thickness(0, 4) };

    private static TextBlock Heading(string text) => new() { Text = text, FontSize = 20, FontWeight = FontWeight.SemiBold };

    private static void Place(Grid grid, Control child, int row = 0, int col = 0)

    { Grid.SetRow(child, row); Grid.SetColumn(child, col); grid.Children.Add(child); }

    private static Grid Field(string caption, Control value)

    {

        var row = new Grid { ColumnDefinitions = new("120,12,*"), MinHeight = 40 };

        Place(row, Text(caption)); Place(row, value, col: 2);

        return row;

    }



    private void BuildStudioLayout()

    {

        var root = new Grid { RowDefinitions = new("Auto,*,Auto"), Margin = new Thickness(20, 12, 20, 12) };

        var header = new Grid { ColumnDefinitions = new("*,Auto"), Margin = new Thickness(4, 0, 4, 20) };

        var branding = new Grid { ColumnDefinitions = new("28,12,Auto,20,1,16,Auto"), Height = 48 };

        var mark = new Avalonia.Controls.Shapes.Path {

            Data = Geometry.Parse("M 2,14 C 5,0 10,0 14,14 C 18,28 23,28 26,14"),

            Stroke = Brush.Parse("#4DA3FF"), StrokeThickness = 2.5,

            StrokeLineCap = PenLineCap.Round, Width = 28, Height = 24,

            Stretch = Stretch.Uniform, VerticalAlignment = VerticalAlignment.Center };

        Place(branding, mark);

        var appTitle = Text("nam2zoom", 30); appTitle.LineHeight = 36; appTitle.TextWrapping = TextWrapping.NoWrap;

        // Center the visible lettering, accounting for the font's descender space.

        appTitle.RenderTransform = new TranslateTransform(0, -4);

        Place(branding, appTitle, col: 2);

        Place(branding, new Border { Width = 1, Height = 20, Background = Brush.Parse("#657583"),

            VerticalAlignment = VerticalAlignment.Center }, col: 4);

        var subtitle = Text("Model bank builder", 16, true); subtitle.LineHeight = 20; subtitle.TextWrapping = TextWrapping.NoWrap;

        subtitle.RenderTransform = new TranslateTransform(0, -2);

        Place(branding, subtitle, col: 6);

        Place(header, branding);

        pedalStatus.MaxWidth = 420; pedalStatus.TextWrapping = TextWrapping.NoWrap; pedalStatus.TextTrimming = TextTrimming.CharacterEllipsis;

        Place(header, pedalStatus, col: 1);

        Place(root, header);



        var workspace = new Grid { ColumnDefinitions = new("3*,16,2*"), Margin = new Thickness(0, 0, 0, 14) };

        workspace.ColumnDefinitions[2].MinWidth = 400;

        var bank = new Grid { RowDefinitions = new("Auto,Auto,Auto,*,Auto") };

        var bankHeader = new Grid { ColumnDefinitions = new("*,Auto"), Margin = new Thickness(0, 0, 0, 16) };

        Place(bankHeader, Row(Heading("Model bank"), modelCount));

        Place(bank, bankHeader);

        var tools = new Grid { ColumnDefinitions = new("*,Auto") };

        Place(tools, Row(Button("Open list", OpenProject), Button("Save list", SaveProject)));

        Place(tools, Row(Button("Remove", () => {

            if (Selected is { } m) { vm.Models.Remove(m); Refresh(Selected); } return Task.CompletedTask;

        }), Button("↑", () => Move(-1)), Button("↓", () => Move(1))), col: 1);

        tools.Margin = new Thickness(0, 0, 0, 10); Place(bank, tools, 1);

        var tableHeader = new Grid { ColumnDefinitions = new("48,*,70,120"), Margin = new Thickness(15, 8, 15, 10) };

        Place(tableHeader, Text("Slot", 12, true)); Place(tableHeader, Text("Model", 12, true), col: 1);

        Place(tableHeader, Text("Label", 12, true), col: 2); Place(tableHeader, Text("Status", 12, true), col: 3);

        Place(bank, tableHeader, 2);

        models.ItemTemplate = new FuncDataTemplate<ModelSelection>((model, _) => {

            if (model is null) return new Border();

            var row = new Grid { ColumnDefinitions = new("48,*,70,120"), Margin = new Thickness(14, 0) };

            Place(row, Text((vm.Models.IndexOf(model) + 1).ToString("00"), muted: true));

            var name = Text(System.IO.Path.GetFileNameWithoutExtension(model.Path));

            name.TextWrapping = TextWrapping.NoWrap; name.TextTrimming = TextTrimming.CharacterEllipsis;

            ToolTip.SetTip(name, model.Path); Place(row, name, col: 1);

            var modelLabel = Text("");

            modelLabel.Bind(TextBlock.TextProperty, new Binding(nameof(ModelSelection.Label)) { Source = model });

            Place(row, modelLabel, col: 2);

            var status = Text(model.Status.Replace('_', ' '), 12, true);

            ToolTip.SetTip(status, $"{model.Status} • {model.SampleRate:N0} Hz"); Place(row, status, col: 3);

            return new Border { BorderBrush = Brush.Parse("#2C363E"), BorderThickness = new Thickness(0, 0, 0, 1), Child = row };

        });

        var listArea = new Grid(); listArea.Children.Add(models);

        emptyHint.HorizontalAlignment = HorizontalAlignment.Center; emptyHint.VerticalAlignment = VerticalAlignment.Center;

        listArea.Children.Add(emptyHint); Place(bank, listArea, 3);

        var add = Button("＋  Add NAMs", async () => {

            var files = await StorageProvider.OpenFilePickerAsync(new() { Title = "Select NAM models", AllowMultiple = true,

                FileTypeFilter = [new("Neural Amp Modeler") { Patterns = ["*.nam"] }] });

            await Add(files.Select(f => f.TryGetLocalPath()).OfType<string>());

        });

        var drop = new Grid { ColumnDefinitions = new("*,Auto"), Margin = new Thickness(0, 16, 0, 0) };

        Place(drop, new StackPanel { Spacing = 6, Children = { Text("Drop NAM files here", 16),

            modelLimitHint } });

        Place(drop, add, col: 1); Place(bank, drop, 4);

        Place(workspace, Card(bank));



        modelName.FontWeight = FontWeight.SemiBold;

        inspector.Spacing = 10;

        inspector.Children.Add(modelName); inspector.Children.Add(Rule());

        label.Height = 40;

        inspector.Children.Add(Field("Pedal label", label));

        ToolTip.SetTip(label, "Unique 1–5 character label: A–Z, 0–9, - or _");

        var irValue = new Border { Background = Brush.Parse("#11181D"), BorderBrush = Brush.Parse("#424E58"),

            BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(5), Padding = new Thickness(12, 8),

            MinHeight = 40, Child = ir };

        ir.TextWrapping = TextWrapping.NoWrap; ir.TextTrimming = TextTrimming.CharacterEllipsis;

        inspector.Children.Add(Field("Cabinet IR", irValue));

        inspector.Children.Add(Field("", Row(Button("Choose IR…", async () => {

            if (Selected is not { } model) return;

            var file = (await StorageProvider.OpenFilePickerAsync(new() { Title = "Mono cabinet impulse response",

                FileTypeFilter = [new("WAV") { Patterns = ["*.wav"] }] })).FirstOrDefault()?.TryGetLocalPath();

            if (file is not null) { model.IrPath = file; Refresh(model); }

        }), Button("Clear IR", () => { if (Selected is { } m) { m.IrPath = null; Refresh(m); } return Task.CompletedTask; }))));

        epochs.Width = double.NaN; epochs.Height = 40; epochs.HorizontalAlignment = HorizontalAlignment.Stretch;

        var epochRow = Field("Training epochs", epochs);

        var profiles = new Grid { ColumnDefinitions = new("*,8,*") };

        compactChoice.Classes.Add("profile"); liteChoice.Classes.Add("profile");

        compactChoice.Click += (_, _) => { profile.SelectedIndex = 0; SyncProfileChoices(); };

        liteChoice.Click += (_, _) => { profile.SelectedIndex = 1; SyncProfileChoices(); };

        Place(profiles, compactChoice); Place(profiles, liteChoice, col: 2);

        ToolTip.SetTip(epochs, "Compatible converted models are reused without retraining.");

        var settings = new StackPanel { Spacing = 10, Children = { Heading("Selected model"), inspector,

            Rule(), Heading("Bank settings"), Field("Bank profile", profiles),

            Text("Compact leaves room for other effects. Lite uses the full pedal DSP budget and must run alone.", 12, true),

            epochRow } };

        Place(workspace, Card(new ScrollViewer { Content = settings,

            VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled }), col: 2);



        var build = Button("⚙  Build effect", () => Build(false)); build.Classes.Add("primary");

        backup.Height = 40; backup.VerticalAlignment = VerticalAlignment.Top;

        var actions = new WrapPanel { Orientation = Orientation.Horizontal };

        foreach (var child in new Control[] { build, Button("Build & install…", () => Build(true)),

            Button("Uninstall bank…", Uninstall), backup }) {

            child.Margin = new Thickness(0, 0, 8, 8); actions.Children.Add(child);

        }

        var actionBody = new StackPanel { Spacing = 8, Children = { Heading("Build & install"), actions,

            Text("Firmware: MS-50G+ 1.40 • MS-70CDR+ 1.20 • MS-60B+ 1.20 experimental. macOS USB-MIDI verification pending.", 12, true) } };

        var actionCard = Card(actionBody);

        controls.RowDefinitions = new("*,Auto");

        Place(controls, workspace); Place(controls, actionCard, 1);

        busyControls.Add(workspace); busyControls.Add(actionCard);

        Place(root, controls, 1);

        var log = new TextBox { IsReadOnly = true, AcceptsReturn = true, Height = 170,

            TextWrapping = TextWrapping.Wrap, FontFamily = FontFamily.Parse("Cascadia Mono, Menlo, monospace"), FontSize = 12 };

        log.Bind(TextBox.TextProperty, new Binding(nameof(MainViewModel.Log)));

        var expander = new Expander { Header = "Activity log", Content = log, HorizontalAlignment = HorizontalAlignment.Stretch,

            Background = Brush.Parse("#1A2126"), BorderBrush = Brush.Parse("#333E47"), CornerRadius = new CornerRadius(6) };

        cancel.Click += (_, _) => cancellation?.Cancel();

        var footerRow = new Grid { ColumnDefinitions = new("Auto,10,Auto,20,*") };

        Place(footerRow, cancel);

        Place(footerRow, Button("Open user files", () => { OpenFolder(vm.Paths.Data); return Task.CompletedTask; }), col: 2);

        Place(footerRow, activity, col: 4);

        var footer = new StackPanel { Spacing = 8, Margin = new Thickness(0, 12, 0, 0), Children = {

            progress, expander, footerRow } };

        activity.MaxHeight = 40; activity.TextTrimming = TextTrimming.CharacterEllipsis;

        Place(root, footer, 2);

        // Keep the main panels usable on smaller screens and when the log is expanded.

        // A bounded root gives the model list its own scrolling; the outer viewer

        // only scrolls when the available window is shorter than the workspace.

        void FitWorkspace() => root.Height = Math.Max(expander.IsExpanded ? 1060 : 880, ClientSize.Height - 24);

        SizeChanged += (_, _) => FitWorkspace();

        expander.PropertyChanged += (_, change) => {

            if (change.Property == Expander.IsExpandedProperty) FitWorkspace();

        };

        FitWorkspace();

        Content = new ScrollViewer { Content = root, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled };

        vm.Models.CollectionChanged += (_, _) => {

            UpdateModelLimit(); emptyHint.IsVisible = vm.Models.Count == 0;

        };

        Detail();

    }



    private void UpdateModelLimit()

    {

        modelCount.Text = $"{vm.Models.Count} / {BankService.MaxModels(Profile)} models";

        modelLimitHint.Text = Profile == "lite" ? "One to three models • .nam files" : "One to ten models • .nam files";

    }



    private void SyncProfileChoices()

    {

        UpdateModelLimit();

        compactChoice.IsChecked = profile.SelectedIndex == 0;

        liteChoice.IsChecked = profile.SelectedIndex == 1;

    }

}

