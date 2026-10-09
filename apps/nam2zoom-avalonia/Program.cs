using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Themes.Fluent;
using Nam2ZoomDesktop;

namespace Nam2Zoom;

internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        if (args.Contains("--smoke-test")) {
            var paths = new AppPaths();
            var service = new BackendService(paths);
            paths.TrainingDi();
            var result = service.ExecuteAsync(paths.Python, ["-B", "-c",
                "import nam.cli, torch, numpy, scipy, soundfile, mido, rtmidi, construct; from nam2zoom.template import fill_template; print('Bundled runtime imports OK')"], Console.WriteLine).GetAwaiter().GetResult();
            result.RequireSuccess();
            return 0;
        }
        App.SmokeGui = args.Contains("--gui-smoke-test");
        AppBuilder.Configure<App>().UsePlatformDetect().StartWithClassicDesktopLifetime(args);
        return 0;
    }
}

public sealed class App : Application
{
    public static bool SmokeGui { get; set; }
    public override void Initialize()
    {
        var theme = new FluentTheme();
        theme.Palettes[Avalonia.Styling.ThemeVariant.Dark] = new ColorPaletteResources {
            Accent = Avalonia.Media.Color.Parse("#4DA3FF") };
        Styles.Add(theme);
        Styles.Add(new Avalonia.Markup.Xaml.Styling.StyleInclude(new Uri("avares://nam2zoom/")) {
            Source = new Uri("avares://nam2zoom/Studio.axaml") });
        RequestedThemeVariant = Avalonia.Styling.ThemeVariant.Dark;
    }
    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop) {
            desktop.MainWindow = new MainWindow();
            if (SmokeGui) desktop.MainWindow.Opened += async (_, _) => {
                await Task.Delay(1000);
                desktop.Shutdown();
            };
        }
        base.OnFrameworkInitializationCompleted();
    }
}
