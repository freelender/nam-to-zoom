using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Themes.Fluent;
using Nam2ZoomDesktop;

namespace Nam2Zoom;

internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--install-runtime") {
            var bootstrap = new AppPaths().Bootstrap
                ?? throw new InvalidOperationException("This package already bundles Python.");
            bootstrap.InstallAsync(Console.WriteLine, default, args[1]).GetAwaiter().GetResult();
            return 0;
        }
        if (args.Length == 2 && args[0] == "--effect-slots-smoke-test") {
            var paths = new AppPaths();
            var service = new ReadyEffectService(paths, new BackendService(paths));
            var models = Enumerable.Range(1,ReadyEffectService.MaximumModels).Select(n => new ModelSelection { Path = args[1], Label = "MODEL" + n, ModelProfile = "lite" }).ToArray();
            foreach (var slot in EffectSlot.All) foreach (var compact in new[] { false, true }) {
                var name = $"NAM AMP{slot.Number}";
                var bank = service.BuildAsync(models, Path.Combine(paths.Data, $"slots-smoke-{slot.Number}-{compact}"), Console.WriteLine, default,
                    compactEffect: compact, effectSlot: slot.Number, effectName: name).GetAwaiter().GetResult();
                if (ReadyEffectService.SlotFor(bank) != slot || ReadyEffectService.NameFor(bank) != name)
                    throw new InvalidDataException("Effect slot identity or name was lost.");
            }
            return 0;
        }
        if (args.Length == 2 && args[0] is "--effect-smoke-test" or "--effect-compact-smoke-test") {
            var paths = new AppPaths();
            var service = new ReadyEffectService(paths, new BackendService(paths));
            var models = Enumerable.Range(1,ReadyEffectService.MaximumModels).Select(n => new ModelSelection { Path = args[1], Label = "MODEL" + n, ModelProfile = "lite" }).ToArray();
            var compact = args[0] == "--effect-compact-smoke-test";
            var bank = service.BuildAsync(models, Path.Combine(paths.Data, compact ? "effect-compact-smoke" : "effect-smoke"), Console.WriteLine, default, compact).GetAwaiter().GetResult();
            if (!File.Exists(bank.Effect) || !File.Exists(bank.Icon)) throw new InvalidDataException("Effect smoke build missing.");
            return 0;
        }
        if (args.Length == 2 && args[0] == "--export-smoke-test") {
            var paths = new AppPaths();
            var service = new ConversionService(paths, new BackendService(paths));
            var model = new ModelSelection { Path = args[1] };
            service.InspectAsync(model).GetAwaiter().GetResult();
            if (model.Status != "direct") throw new InvalidDataException("Smoke export requires an already Zoom-ready NAM.");
            var result = service.ConvertAsync([model], ConvertedNam.ApplicationDirectory(AppContext.BaseDirectory), 1,
                (_, _) => throw new InvalidOperationException("A ready NAM should not need retraining or review."), Console.WriteLine, default).GetAwaiter().GetResult();
            if (result.Files.Count != 1) throw new InvalidDataException("Smoke export missing.");
            return 0;
        }
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
            var paths = new AppPaths();
            var bootstrap = paths.Bootstrap;
            if (bootstrap is { IsReady: false }) {
                var setup = new RuntimeSetupWindow(bootstrap, paths.LocalRuntimeArchive, () => {
                    var main = new MainWindow();
                    desktop.MainWindow = main;
                    main.Show();
                });
                desktop.MainWindow = setup;
            } else {
                desktop.MainWindow = new MainWindow();
            }
            if (SmokeGui && Environment.GetEnvironmentVariable("NAM2ZOOM_GUI_CANCEL_PYTHON") is null) desktop.MainWindow.Opened += async (_, _) => {
                await Task.Delay(1000);
                if (Environment.GetEnvironmentVariable("NAM2ZOOM_GUI_SCREENSHOT") is { Length: > 0 } screenshot) {
                    var window = desktop.MainWindow!;
                    using var bitmap = new Avalonia.Media.Imaging.RenderTargetBitmap(
                        new PixelSize((int)window.ClientSize.Width, (int)window.ClientSize.Height), new Vector(96, 96));
                    bitmap.Render(window);
                    bitmap.Save(screenshot, new Avalonia.Media.Imaging.PngBitmapEncoderOptions());
                }
                desktop.Shutdown();
            };
        }
        base.OnFrameworkInitializationCompleted();
    }
}
