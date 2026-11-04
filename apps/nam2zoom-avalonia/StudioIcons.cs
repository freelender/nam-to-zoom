using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Controls.Shapes;

namespace Nam2Zoom;

public sealed partial class MainWindow
{
    private static readonly IBrush Blue = Brush.Parse("#28ACFF");
    private static Control Glyph(string kind, double size = 23, IBrush? color = null)
    {
        var data = kind switch {
            "wave" => "M2,10 L2,18 M7,5 L7,23 M12,1 L12,27 M17,7 L17,21 M22,11 L22,17",
            "home" => "M2,12 L12,3 L22,12 M5,10 L5,22 L10,22 L10,15 L15,15 L15,22 L20,22 L20,10",
            "share" => "M8,13 L17,7 M8,15 L17,21 M7,14 A3,3 0 1 1 1,14 A3,3 0 1 1 7,14 M23,5 A3,3 0 1 1 17,5 A3,3 0 1 1 23,5 M23,23 A3,3 0 1 1 17,23 A3,3 0 1 1 23,23",
            "gear" => "M9,2 L15,2 L16,6 L20,5 L23,10 L20,13 L23,16 L20,21 L16,20 L15,24 L9,24 L8,20 L4,21 L1,16 L4,13 L1,10 L4,5 L8,6 Z M17,13 A5,5 0 1 1 7,13 A5,5 0 1 1 17,13",
            "info" => "M23,12 A11,11 0 1 1 1,12 A11,11 0 1 1 23,12 M12,10 L12,18 M12,6 L12,7",
            "database" => "M3,5 C3,1 23,1 23,5 C23,9 3,9 3,5 Z M3,5 L3,21 C3,26 23,26 23,21 L23,5 M3,13 C3,18 23,18 23,13",
            "folder" => "M2,5 L10,5 L13,8 L24,8 L24,22 L2,22 Z",
            "trash" => "M4,7 L22,7 M8,7 L8,3 L18,3 L18,7 M6,7 L7,24 L19,24 L20,7 M10,11 L10,20 M16,11 L16,20",
            "plus" => "M12,3 L12,23 M2,13 L22,13",
            "stop" => "M4,4 L21,4 L21,22 L4,22 Z",
            "download" => "M13,2 L13,18 M7,12 L13,18 L19,12 M3,18 L3,24 L23,24 L23,18",
            "external" => "M14,3 L23,3 L23,12 M23,3 L10,16 M11,4 L3,4 L3,23 L22,23 L22,15",
            "file" => "M5,2 L16,2 L23,9 L23,25 L5,25 Z M16,2 L16,9 L23,9 M9,14 L19,14 M9,19 L19,19",
            "spinner" => "M22,12 A10,10 0 1 1 12,2",
            "clock" => "M23,12 A11,11 0 1 1 1,12 A11,11 0 1 1 23,12 M12,5 L12,13 L18,16",
            "chip" => "M5,5 L21,5 L21,21 L5,21 Z M9,9 L17,9 L17,17 L9,17 Z M9,1 L9,5 M17,1 L17,5 M9,21 L9,25 M17,21 L17,25 M1,9 L5,9 M1,17 L5,17 M21,9 L25,9 M21,17 L25,17",
            "clear" => "M5,5 L21,21 M21,5 L5,21",
            _ => "M12,3 L12,5 M12,12 L12,14 M12,21 L12,23"
        };
        return new Avalonia.Controls.Shapes.Path { Data = Geometry.Parse(data), Stroke = color ?? Blue,
            StrokeThickness = kind == "wave" ? 2.8 : 1.7, StrokeLineCap = PenLineCap.Round, StrokeJoin = PenLineJoin.Round,
            Width = size, Height = size, Stretch = Stretch.Uniform, VerticalAlignment = VerticalAlignment.Center };
    }
    private static StackPanel Row(params Control[] children)
    {
        var panel = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10, VerticalAlignment = VerticalAlignment.Center };
        foreach (var child in children) panel.Children.Add(child);
        return panel;
    }
    private static TextBlock Text(string text, double size = 14, bool muted = false) => new() {
        Text = text, FontSize = size, Foreground = Brush.Parse(muted ? "#B0C0CF" : "#EDF4FC"),
        VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap };
    private static TextBlock Heading(string text, double size = 20) => new() { Text = text, FontSize = size, FontWeight = FontWeight.SemiBold };
    private static void Place(Grid grid, Control child, int row = 0, int col = 0)
    { Grid.SetRow(child, row); Grid.SetColumn(child, col); grid.Children.Add(child); }
    private static Border Card(Control child, double padding = 20) => new() {
        Background = new LinearGradientBrush { StartPoint = new RelativePoint(0,0,RelativeUnit.Relative), EndPoint = new RelativePoint(1,1,RelativeUnit.Relative),
            GradientStops = new GradientStops { new(Color.Parse("#15212B"),0), new(Color.Parse("#101A22"),1) } },
        BorderBrush = Brush.Parse("#2C414F"), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8),
        Padding = new Thickness(padding), Child = child };
    private static Button NewButton(string text, string icon, string? style = null)
    {
        var button = new Button { Content = Row(Glyph(icon, 18, style == "danger" ? Brush.Parse("#FF6D77") : Brush.Parse("#E5EEF8")), Text(text, 13)),
            HorizontalContentAlignment = HorizontalAlignment.Center };
        if (style is not null) button.Classes.Add(style);
        return button;
    }
    private static Control PedalArt()
    {
        var bitmap = new Avalonia.Media.Imaging.Bitmap(Avalonia.Platform.AssetLoader.Open(
            new Uri("avares://nam2zoom/Assets/nam-a2-pedal.png")));
        return new Image { Source = bitmap,
            Width = 156, Height = 224, Stretch = Stretch.Uniform, HorizontalAlignment = HorizontalAlignment.Center };
    }
}
