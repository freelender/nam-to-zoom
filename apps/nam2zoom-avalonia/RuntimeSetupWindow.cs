using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Threading;
using Nam2ZoomDesktop;

namespace Nam2Zoom;

internal sealed class RuntimeSetupWindow : Window
{
    public RuntimeSetupWindow(RuntimeBootstrap bootstrap, string? previewArchive, Action start)
    {
        Title = "nam2zoom setup";
        Width = 500;
        SizeToContent = SizeToContent.Height;
        CanResize = false;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap };
        var progress = new ProgressBar { IsIndeterminate = true };
        var retry = new Button { Content = "Retry", IsVisible = false };
        var cancellation = new CancellationTokenSource();
        var localArchive = Environment.GetEnvironmentVariable("NAM2ZOOM_RUNTIME_ARCHIVE") ?? previewArchive;
        Content = new StackPanel {
            Margin = new Thickness(24), Spacing = 14,
            Children = {
                new TextBlock { Text = "Setting up nam2zoom", FontSize = 22 },
                new TextBlock {
                    Text = string.IsNullOrWhiteSpace(localArchive)
                        ? "First launch downloads Python and the packages for conversion and training. Setup is saved for future launches."
                        : "First launch installs Python and its dependencies from the local test archive. Setup is saved for future launches.",
                    TextWrapping = TextWrapping.Wrap
                },
                status, progress, retry
            }
        };
        Opened += async (_, _) => await Install();
        retry.Click += async (_, _) => await Install();
        Closing += (_, _) => cancellation.Cancel();

        async Task Install()
        {
            retry.IsVisible = false;
            progress.IsVisible = true;
            status.Text = "Preparing setup…";
            try {
                await Task.Run(() => bootstrap.InstallAsync(
                    message => Dispatcher.UIThread.Post(() => status.Text = message), cancellation.Token,
                    string.IsNullOrWhiteSpace(localArchive) ? null : localArchive));
                if (cancellation.IsCancellationRequested) return;
                start();
                Close();
            } catch (OperationCanceledException) when (cancellation.IsCancellationRequested) {
            } catch (Exception ex) {
                var hint = string.IsNullOrWhiteSpace(localArchive)
                    ? "Check your connection and retry."
                    : "Check that the local runtime archive is next to the app folder and retry.";
                status.Text = $"Setup failed. {hint}\n{ex.Message}";
                progress.IsVisible = false;
                retry.IsVisible = true;
            }
        }
    }
}
