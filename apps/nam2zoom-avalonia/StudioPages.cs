using Avalonia;
using Avalonia.Controls;
using Avalonia.Data;
using Avalonia.Layout;
using Avalonia.Media;
using Nam2ZoomDesktop;

namespace Nam2Zoom;

public sealed partial class MainWindow
{
    private void Navigate(string page)
    {
        currentPage = page;
        pedalCompatibility.IsVisible = page == "Build effect";
        outputFormatValue.Text = page == "Build effect" ? "N2Z Bank  ·  ZD2 effect + ZIC icon" : "A2 Lite  ·  44.1 kHz  ·  Zoom-ready NAM";
        outputFormatHint.Text = page == "Build effect" ? "Built from retrained A2 Lite 44.1 kHz NAMs" : "Preserves a learned approximation of the capture’s sound";
        retrainPage.IsVisible = page == "Retrain"; sharePage.IsVisible = page == "Build effect";
        settingsPage.IsVisible = page == "Settings"; aboutPage.IsVisible = page == "About";
        foreach (var (name, button) in navigation) button.Classes.Set("navactive", name == page);
        pageTitle.Text = page switch { "Retrain" => "Retrain NAM files", "Build effect" => "Build effect", "Settings" => "Settings", _ => "About nam2zoom" };
        pageSubtitle.Text = page switch {
            "Retrain" => "Convert your NAM captures into Zoom-ready models (A2 Lite, 44.1 kHz).",
            "Build effect" => "Build N2Z Bank from retrained NAMs, then install or remove it on your pedal.",
            "Settings" => "Training preferences, saved queues and application folders.",
            _ => "Local NAM retraining, built for collaboration." };
        if (page == "Build effect") RefreshExports();
    }
    private void BuildSecondaryPages()
    {
        BuildEffectPage();

        var settings = new StackPanel { Spacing = 18 };
        settings.Children.Add(Row(Glyph("gear"), Heading("Training preferences")));
        var defaultEpochs = new EpochUpDown();
        defaultEpochs.Bind(NumericUpDown.ValueProperty, new Binding(nameof(NumericUpDown.Value)) { Source = epochs, Mode = BindingMode.TwoWay });
        var device = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch };
        device.Bind(ItemsControl.ItemsSourceProperty, new Binding(nameof(ItemsControl.ItemsSource)) { Source = trainingDevice });
        device.Bind(ComboBox.SelectedIndexProperty, new Binding(nameof(ComboBox.SelectedIndex)) { Source = trainingDevice, Mode = BindingMode.TwoWay });
        settings.Children.Add(Text("Default training epochs", 13, true)); settings.Children.Add(defaultEpochs);
        settings.Children.Add(Text("Training device", 13, true)); settings.Children.Add(device);
        settings.Children.Add(Text("GPU setup verifies an actual CUDA allocation before activating the saved preference. CPU training remains available.", 13, true));
        var scrolling = new CheckBox { Content = "Auto-scroll the retraining log" };
        scrolling.Bind(CheckBox.IsCheckedProperty, new Binding(nameof(CheckBox.IsChecked)) { Source = autoScroll, Mode = BindingMode.TwoWay });
        settings.Children.Add(scrolling);
        settings.Children.Add(Heading("Saved queues", 18));
        var queueActions = Row(ActionButton("Open queue", "folder", OpenProject), ActionButton("Save queue", "file", SaveProject));
        busyControls.Add(queueActions); settings.Children.Add(queueActions);
        settings.Children.Add(Text("Queue files store source paths. The original captures must remain available when reopening a queue.", 12, true));
        busyControls.Add(defaultEpochs); busyControls.Add(device);
        var folders = new StackPanel { Spacing = 14, Children = {
            Row(Glyph("folder"), Heading("Application folders")),
            Text("Output files", 13), Text(ExportFolder, 12, true),
            UtilityButton("Open output folder", "folder", OpenExports),
            Text("Training cache, previews, preferences and logs", 13), Text(vm.Paths.Data, 12, true),
            UtilityButton("Open user-data folder", "folder", () => { Directory.CreateDirectory(vm.Paths.Data); OpenFolder(vm.Paths.Data); }),
            Text("Exports stay in Converted_NAM beside the Windows executable or macOS .app. Existing NAM files and completed exports are preserved.", 13, true) } };
        var settingsGrid = new Grid { ColumnDefinitions = new("*,16,*") };
        Place(settingsGrid, Card(new ScrollViewer { Content = settings })); Place(settingsGrid, Card(new ScrollViewer { Content = folders }), col: 2);
        settingsPage.Children.Add(settingsGrid); settingsPage.Margin = new Thickness(0,0,0,14);
        var version = typeof(MainWindow).Assembly.GetName().Version;
        aboutPage.Children.Add(Card(new ScrollViewer { Content = new StackPanel { Spacing = 20, MaxWidth = 900, HorizontalAlignment = HorizontalAlignment.Left, Children = {
            Row(Glyph("wave", 50), Heading("nam2zoom", 32)), Text($"Version {version?.Major}.{version?.Minor}.{version?.Build}", 14, true),
            Text("Retrain supported NAM captures into A2 Lite models at 44.1 kHz. Conversion runs locally using CPU or supported NVIDIA CUDA training.", 16),
            Text("Share your converted NAM files with other users without repeating the retraining. Share models you have permission to redistribute.", 14, true),
            Heading("Loading onto Zoom pedals", 20),
            Text("Use the NAM loader at sym.bios.is to load files onto compatible Zoom pedals. sym.bios.is does not host or share retrained NAM models. Follow the loader’s current model and firmware requirements. The Build effect page also provides guarded N2Z Bank installation and removal on supported pedals.", 14, true),
            UtilityButton("Open sym.bios.is", "external", OpenLoader),
            Text("Training approximates the sound of the original capture. Quality is checked using separate test audio, with A/B review for results below the quality limits.", 14, true),
            Text("MS-50G+ product photo: Zoom Corporation (zoomcorp.com).", 12, true),
            Text("Project code: MIT License · Aleksandar Vukasinovic. Bundled third-party components retain their own licenses. User captures are not included with the app.", 12, true) } } }));
        aboutPage.Margin = new Thickness(0,0,0,14);
    }
    private void RefreshExports() => RefreshEffectModels();
}
