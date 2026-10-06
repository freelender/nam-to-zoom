using System.Diagnostics;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace Nam2ZoomDesktop;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        try {
            Application.Run(new MainForm());
        } catch (Exception exception) {
            MessageBox.Show("Could not start nam2zoom: " + exception.Message
                + "\n\nFor a portable release, extract the entire ZIP to a writable folder.",
                "nam2zoom", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}

internal sealed class ModelEntry
{
    public string Path { get; set; } = "";
    public string Label { get; set; } = "";
    public string? IrPath { get; set; }
    public string Status { get; set; } = "Checking";
    public int SampleRate { get; set; }
}

internal sealed class CardPanel : Panel
{
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color BorderColor { get; set; } = Color.Transparent;
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public int CornerRadius { get; set; } = 10;

    public CardPanel()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer
            | ControlStyles.ResizeRedraw | ControlStyles.UserPaint, true);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        if (Width < 2 || Height < 2) return;
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var path = RoundedRectangle(new Rectangle(0, 0, Width - 1, Height - 1), CornerRadius);
        using var pen = new Pen(BorderColor);
        e.Graphics.DrawPath(pen, path);
    }

    internal static GraphicsPath RoundedRectangle(Rectangle bounds, int radius)
    {
        var path = new GraphicsPath();
        var diameter = Math.Min(radius * 2, Math.Min(bounds.Width, bounds.Height));
        var arc = new Rectangle(bounds.X, bounds.Y, diameter, diameter);
        path.AddArc(arc, 180, 90);
        arc.X = bounds.Right - diameter;
        path.AddArc(arc, 270, 90);
        arc.Y = bounds.Bottom - diameter;
        path.AddArc(arc, 0, 90);
        arc.X = bounds.Left;
        path.AddArc(arc, 90, 90);
        path.CloseFigure();
        return path;
    }
}

internal sealed class WaveMark : Control
{
    public WaveMark()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer
            | ControlStyles.ResizeRedraw | ControlStyles.UserPaint, true);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var pen = new Pen(Color.FromArgb(57, 207, 203), 3.2f) {
            StartCap = LineCap.Round, EndCap = LineCap.Round, LineJoin = LineJoin.Round
        };
        var center = Height / 2f - 1;
        var points = new[] {
            new PointF(3, center + 3), new PointF(8, center + 3),
            new PointF(13, center - 7), new PointF(18, center + 12),
            new PointF(23, center - 1), new PointF(28, center - 15),
            new PointF(33, center + 14), new PointF(39, center - 4),
            new PointF(45, center + 3), new PointF(50, center + 3)
        };
        e.Graphics.DrawLines(pen, points);
        TextRenderer.DrawText(e.Graphics, Text, Font,
            new Rectangle(66, -6, Math.Max(0, Width - 66), Height), ForeColor,
            TextFormatFlags.Left | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine
            | TextFormatFlags.NoPadding);
    }
}

internal enum WindowButtonKind { Minimize, Maximize, Close }

internal sealed class WindowButton : Button
{
    public WindowButtonKind Kind { get; }
    private bool pointerOver;

    public WindowButton(WindowButtonKind kind)
    {
        Kind = kind;
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer
            | ControlStyles.ResizeRedraw | ControlStyles.UserPaint, true);
        FlatStyle = FlatStyle.Flat;
        FlatAppearance.BorderSize = 0;
        TabStop = false;
    }

    protected override void OnMouseEnter(EventArgs e)
    {
        pointerOver = true;
        Invalidate();
        base.OnMouseEnter(e);
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        pointerOver = false;
        Invalidate();
        base.OnMouseLeave(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.Clear(BackColor);
        if (pointerOver) {
            using var hover = new SolidBrush(Kind == WindowButtonKind.Close
                ? Color.FromArgb(95, 38, 45) : Color.FromArgb(39, 53, 66));
            e.Graphics.FillRectangle(hover, ClientRectangle);
        }
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var pen = new Pen(ForeColor, 1.25f);
        var cx = Width / 2f;
        var cy = Height / 2f;
        if (Kind == WindowButtonKind.Minimize) {
            e.Graphics.DrawLine(pen, cx - 4, cy, cx + 4, cy);
        } else if (Kind == WindowButtonKind.Maximize) {
            e.Graphics.DrawRectangle(pen, cx - 4.5f, cy - 4.5f, 9, 9);
        } else {
            e.Graphics.DrawLine(pen, cx - 4, cy - 4, cx + 4, cy + 4);
            e.Graphics.DrawLine(pen, cx + 4, cy - 4, cx - 4, cy + 4);
        }
    }
}

internal sealed class RoundedButton : Button
{
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color HoverColor { get; set; }
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color ButtonBorderColor { get; set; } = Color.Transparent;

    private bool pointerOver;

    public RoundedButton()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer
            | ControlStyles.ResizeRedraw | ControlStyles.UserPaint, true);
        FlatStyle = FlatStyle.Flat;
        FlatAppearance.BorderSize = 0;
    }

    protected override void OnMouseEnter(EventArgs e)
    {
        pointerOver = true;
        Invalidate();
        base.OnMouseEnter(e);
    }

    protected override void OnMouseLeave(EventArgs e)
    {
        pointerOver = false;
        Invalidate();
        base.OnMouseLeave(e);
    }

    protected override void OnEnabledChanged(EventArgs e)
    {
        Invalidate();
        base.OnEnabledChanged(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        e.Graphics.Clear(Parent?.BackColor ?? Color.FromArgb(27, 38, 49));
        var fill = !Enabled ? Color.FromArgb(31, 44, 55)
            : pointerOver && HoverColor != Color.Empty ? HoverColor : BackColor;
        var text = Enabled ? ForeColor : Color.FromArgb(103, 120, 133);
        using var path = CardPanel.RoundedRectangle(new Rectangle(0, 0, Width - 1, Height - 1), 7);
        using var brush = new SolidBrush(fill);
        e.Graphics.FillPath(brush, path);
        if (ButtonBorderColor != Color.Transparent) {
            using var pen = new Pen(Enabled ? ButtonBorderColor : Color.FromArgb(48, 63, 75));
            e.Graphics.DrawPath(pen, path);
        }
        TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, text,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter
            | TextFormatFlags.SingleLine | TextFormatFlags.EndEllipsis);
        if (Focused && ShowFocusCues) {
            var focus = Rectangle.Inflate(ClientRectangle, -4, -4);
            ControlPaint.DrawFocusRectangle(e.Graphics, focus, text, fill);
        }
    }
}

internal sealed class MainForm : Form
{
    private readonly List<ModelEntry> models = [];
    private readonly DataGridView grid = new();
    private readonly TextBox log = new();
    private readonly Label status = new();
    private readonly Label selectedFile = new();
    private readonly Label selectedPath = new();
    private readonly Label selectedCompatibility = new();
    private readonly Label selectedRate = new();
    private readonly Label selectedSize = new();
    private readonly Label selectedIr = new();
    private readonly Label labelCount = new();
    private readonly TextBox pedalLabel = new();
    private readonly ProgressBar progress = new();
    private readonly Button removeButton = new RoundedButton();
    private readonly Button moveUpButton = new RoundedButton();
    private readonly Button moveDownButton = new RoundedButton();
    private readonly Button buildButton = new RoundedButton();
    private readonly Button installButton = new RoundedButton();
    private readonly Button uninstallButton = new RoundedButton();
    private readonly CheckBox backupCheck = new();
    private readonly CheckBox bestEffortCheck = new();
    private readonly NumericUpDown epochsInput = new();
    private readonly Button previewButton = new RoundedButton();
    private readonly Button chooseIrButton = new RoundedButton();
    private readonly Button clearIrButton = new RoundedButton();
    private readonly Button cancelButton = new RoundedButton();
    private bool busy;
    private bool deviceBusy;
    private string lastAction = "Ready";
    private CancellationTokenSource? jobCancellation;
    private readonly string root;
    private readonly string python;
    private readonly string trainingPython;
    private bool updatingLabel;
    private bool determinateProgress;
    private string? previewRoot;
    private const string BundledDiSha256 = "F27F5EA4A1BC4245AF5C4DFF5DE5B75FB7AEF71C1B10E196B35EA5EF41122153";

    private static readonly Color Background = Color.FromArgb(18, 26, 34);
    private static readonly Color Surface = Color.FromArgb(27, 38, 49);
    private static readonly Color SurfaceRaised = Color.FromArgb(35, 49, 61);
    private static readonly Color Border = Color.FromArgb(62, 82, 95);
    private static readonly Color Foreground = Color.FromArgb(238, 245, 247);
    private static readonly Color Muted = Color.FromArgb(169, 188, 198);
    private static readonly Color Accent = Color.FromArgb(67, 196, 177);
    private static readonly Color Blue = Color.FromArgb(39, 139, 246);
    private static readonly Color Success = Color.FromArgb(83, 220, 132);
    private static readonly Color Danger = Color.FromArgb(241, 83, 87);

    public MainForm()
    {
        root = FindRoot();
        PortableRuntime.Prepare(root);
        python = PortableRuntime.IsPortable(root)
            ? System.IO.Path.Combine(root, "runtime", "python313", "python.exe")
            : System.IO.Path.Combine(root, ".tooling", "stomphacks", ".venv", "Scripts", "python.exe");
        trainingPython = System.IO.Path.Combine(root, ".tooling", "nam-train-venv", "Scripts", "python.exe");
        Text = $"nam2zoom v{Application.ProductVersion}";
        var executableIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        if (executableIcon is not null) Icon = executableIcon;
        MinimumSize = new Size(1080, 720);
        Size = new Size(1380, 900);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Background;
        ForeColor = Foreground;
        Font = new Font("Segoe UI", 10);
        AllowDrop = true;
        FormBorderStyle = FormBorderStyle.None;
        Padding = new Padding(1);

        var layout = new TableLayoutPanel {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3,
            Margin = Padding.Empty, Padding = Padding.Empty, BackColor = Background
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 50));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 182));
        Controls.Add(layout);

        var header = new Panel { Dock = DockStyle.Fill, BackColor = Color.FromArgb(20, 32, 44) };
        header.MouseDown += (_, e) => BeginWindowDrag(e);
        header.DoubleClick += (_, _) => ToggleMaximize();
        var mark = new WaveMark {
            Text = "nam2zoom", Font = new Font("Segoe UI", 20, FontStyle.Bold),
            ForeColor = Foreground, BackColor = Color.FromArgb(20, 32, 44)
        };
        mark.SetBounds(20, 0, 360, 50);
        mark.MouseDown += (_, e) => BeginWindowDrag(e);
        header.Controls.Add(mark);
        var minimize = MakeWindowButton(WindowButtonKind.Minimize,
            (_, _) => WindowState = FormWindowState.Minimized);
        var maximize = MakeWindowButton(WindowButtonKind.Maximize, (_, _) => ToggleMaximize());
        var close = MakeWindowButton(WindowButtonKind.Close, (_, _) => Close());
        header.Controls.Add(minimize);
        header.Controls.Add(maximize);
        header.Controls.Add(close);
        void PositionHeaderControls()
        {
            close.Left = header.ClientSize.Width - 47;
            maximize.Left = close.Left - 46;
            minimize.Left = maximize.Left - 46;
        }
        header.Resize += (_, _) => PositionHeaderControls();
        PositionHeaderControls();
        layout.Controls.Add(header, 0, 0);

        var content = new TableLayoutPanel {
            Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1,
            Padding = new Padding(14, 10, 14, 10), BackColor = Background
        };
        content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 71));
        content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 29));
        layout.Controls.Add(content, 0, 1);

        var workspaceCard = new CardPanel {
            Dock = DockStyle.Fill, BackColor = Surface, BorderColor = Border,
            Margin = new Padding(0, 0, 10, 0), Padding = new Padding(20, 14, 20, 12)
        };
        content.Controls.Add(workspaceCard, 0, 0);
        var workspace = new TableLayoutPanel {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 4,
            Padding = Padding.Empty, Margin = Padding.Empty, BackColor = Surface
        };
        workspace.RowStyles.Add(new RowStyle(SizeType.Absolute, 68));
        workspace.RowStyles.Add(new RowStyle(SizeType.Absolute, 58));
        workspace.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        workspace.RowStyles.Add(new RowStyle(SizeType.Absolute, 98));
        workspaceCard.Controls.Add(workspace);
        var heading = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 2, BackColor = Surface };
        heading.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        heading.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
        heading.Controls.Add(MakeLabel("Model workspace", 18, FontStyle.Bold), 0, 0);
        heading.Controls.Add(MakeLabel("Add NAM models, organize your slots, then build a custom pedal effect.",
            9, FontStyle.Regular, Muted), 0, 1);
        workspace.Controls.Add(heading, 0, 0);

        var commands = new FlowLayoutPanel {
            Dock = DockStyle.Fill, WrapContents = false, AutoScroll = true,
            Padding = Padding.Empty, BackColor = Surface
        };
        workspace.Controls.Add(commands, 0, 1);
        AddButton(commands, "+  Add model", (_, _) => _ = AddFromDialogAsync(), primary: true);
        AddButton(commands, "Open list", (_, _) => _ = OpenProjectAsync());
        AddButton(commands, "Save list", (_, _) => SaveProject());
        ConfigureButton(moveUpButton, "Move up");
        moveUpButton.Click += (_, _) => MoveSelected(-1);
        commands.Controls.Add(moveUpButton);
        ConfigureButton(moveDownButton, "Move down");
        moveDownButton.Click += (_, _) => MoveSelected(1);
        commands.Controls.Add(moveDownButton);
        ConfigureButton(removeButton, "Remove", danger: true);
        removeButton.Click += (_, _) => RemoveSelected();
        commands.Controls.Add(removeButton);

        buildButton.Text = "Build effect";
        ConfigureButton(buildButton, "Build effect", primary: true);
        buildButton.Click += async (_, _) => await BuildAsync(false);
        ConfigureButton(installButton, "Build + Install", blue: true);
        installButton.Click += async (_, _) => await BuildAsync(true);
        ConfigureButton(uninstallButton, "Uninstall from pedal");
        uninstallButton.Click += async (_, _) => await UninstallAsync();
        var buildArea = new TableLayoutPanel {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2,
            Margin = Padding.Empty, Padding = Padding.Empty, BackColor = Surface
        };
        buildArea.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        buildArea.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        var buildOptions = new FlowLayoutPanel {
            Dock = DockStyle.Fill, WrapContents = false, AutoScroll = true,
            Margin = Padding.Empty, BackColor = Surface
        };
        var epochsLabel = new Label {
            Text = "Epochs", AutoSize = true, ForeColor = Muted,
            Margin = new Padding(0, 11, 8, 0)
        };
        buildOptions.Controls.Add(epochsLabel);
        epochsInput.Minimum = 1;
        epochsInput.Maximum = 300;
        epochsInput.Value = 100;
        epochsInput.Width = 72;
        epochsInput.BackColor = SurfaceRaised;
        epochsInput.ForeColor = Foreground;
        epochsInput.TextAlign = HorizontalAlignment.Center;
        epochsInput.Margin = new Padding(0, 6, 14, 0);
        epochsInput.AccessibleDescription =
            "PC training epochs for NAM models that need adaptation, from 1 to 300";
        buildOptions.Controls.Add(epochsInput);
        var buildCommands = new FlowLayoutPanel {
            Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft,
            WrapContents = false, AutoScroll = true, BackColor = Surface
        };
        buildCommands.Controls.Add(installButton);
        buildCommands.Controls.Add(uninstallButton);
        buildCommands.Controls.Add(buildButton);
        ConfigureButton(previewButton, "Open A/B");
        previewButton.Click += (_, _) => OpenPreview();
        buildCommands.Controls.Add(previewButton);
        bestEffortCheck.Text = "Best effort";
        bestEffortCheck.AutoSize = true;
        bestEffortCheck.ForeColor = Muted;
        bestEffortCheck.Margin = new Padding(8, 11, 12, 0);
        bestEffortCheck.Cursor = Cursors.Hand;
        bestEffortCheck.AccessibleDescription =
            "Allow lower-fidelity NAM conversions after training; device safety checks remain required";
        buildOptions.Controls.Add(bestEffortCheck);
        backupCheck.Text = "Back up device";
        backupCheck.Checked = true;
        backupCheck.AutoSize = true;
        backupCheck.ForeColor = Muted;
        backupCheck.Margin = new Padding(8, 11, 12, 0);
        backupCheck.Cursor = Cursors.Hand;
        backupCheck.AccessibleDescription = "Save a full pedal backup before installing or uninstalling";
        buildOptions.Controls.Add(backupCheck);
        buildArea.Controls.Add(buildOptions, 0, 0);
        buildArea.Controls.Add(buildCommands, 0, 1);
        workspace.Controls.Add(buildArea, 0, 3);

        ConfigureButton(cancelButton, "Cancel build");
        cancelButton.Click += (_, _) => { cancelButton.Enabled = false; jobCancellation?.Cancel(); };

        grid.Dock = DockStyle.Fill;
        grid.AllowUserToAddRows = false;
        grid.AllowUserToDeleteRows = false;
        grid.AllowUserToResizeRows = false;
        grid.ReadOnly = true;
        grid.MultiSelect = false;
        grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        grid.RowHeadersVisible = false;
        grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill;
        grid.BackgroundColor = Color.FromArgb(19, 31, 42);
        grid.BorderStyle = BorderStyle.None;
        grid.GridColor = Border;
        grid.EnableHeadersVisualStyles = false;
        grid.ColumnHeadersHeight = 42;
        grid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(31, 48, 62);
        grid.ColumnHeadersDefaultCellStyle.ForeColor = Muted;
        grid.ColumnHeadersDefaultCellStyle.Font = new Font("Segoe UI", 9, FontStyle.Regular);
        grid.ColumnHeadersDefaultCellStyle.Padding = new Padding(8, 0, 8, 0);
        grid.DefaultCellStyle.BackColor = Color.FromArgb(20, 34, 46);
        grid.DefaultCellStyle.ForeColor = Foreground;
        grid.DefaultCellStyle.SelectionBackColor = Color.FromArgb(31, 72, 77);
        grid.DefaultCellStyle.SelectionForeColor = Foreground;
        grid.DefaultCellStyle.Padding = new Padding(8, 0, 8, 0);
        grid.DefaultCellStyle.Font = new Font("Segoe UI", 9.5f);
        grid.RowTemplate.Height = 46;
        grid.CellBorderStyle = DataGridViewCellBorderStyle.SingleHorizontal;
        grid.AllowDrop = true;
        grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "#", FillWeight = 9 });
        grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "Pedal label", FillWeight = 19 });
        grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "NAM model", FillWeight = 52 });
        grid.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = "Compatibility", FillWeight = 20 });
        grid.SelectionChanged += (_, _) => UpdateDetail();
        grid.CellFormatting += (_, e) => {
            if (e.ColumnIndex != 3 || e.Value is not string value) return;
            e.CellStyle.ForeColor = value is "Ready" or "Adapt" ? Success :
                value == "Unsupported" ? Danger : Muted;
            e.Value = value switch {
                "Ready" => "Compatible", "Adapt" => "Conversion needed", _ => value
            };
            e.FormattingApplied = true;
        };
        grid.KeyDown += (_, e) => {
            if (e.KeyCode == Keys.Delete) { RemoveSelected(); e.Handled = true; }
            if (e.Control && e.KeyCode == Keys.Up) { MoveSelected(-1); e.Handled = true; }
            if (e.Control && e.KeyCode == Keys.Down) { MoveSelected(1); e.Handled = true; }
        };
        workspace.Controls.Add(grid, 0, 2);

        var detailsCard = new CardPanel {
            Dock = DockStyle.Fill, BackColor = Surface, BorderColor = Border,
            Margin = Padding.Empty, Padding = new Padding(20, 14, 20, 12)
        };
        content.Controls.Add(detailsCard, 1, 0);
        var details = new TableLayoutPanel {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 14,
            Padding = Padding.Empty, BackColor = Surface,
            AutoScroll = true
        };
        foreach (var height in new[] { 42, 22, 36, 34, 22, 40, 20, 24, 46, 34, 60, 46, 46 })
            details.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
        details.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        detailsCard.Controls.Add(details);
        details.Controls.Add(MakeLabel("Selected model", 14, FontStyle.Bold), 0, 0);
        details.Controls.Add(MakeLabel("NAM file", 9, FontStyle.Regular, Muted), 0, 1);
        selectedFile.Dock = DockStyle.Fill;
        selectedFile.ForeColor = Foreground;
        selectedFile.Font = new Font("Segoe UI", 10.5f, FontStyle.Bold);
        selectedFile.AutoEllipsis = true;
        details.Controls.Add(selectedFile, 0, 2);
        selectedPath.Dock = DockStyle.Fill;
        selectedPath.ForeColor = Muted;
        selectedPath.Font = new Font("Segoe UI", 8.5f);
        selectedPath.AutoEllipsis = true;
        details.Controls.Add(selectedPath, 0, 3);
        details.Controls.Add(MakeLabel("Pedal label", 9, FontStyle.Regular, Muted), 0, 4);
        pedalLabel.Dock = DockStyle.Top;
        pedalLabel.MaxLength = 5;
        pedalLabel.Font = new Font("Segoe UI", 11);
        pedalLabel.BackColor = SurfaceRaised;
        pedalLabel.ForeColor = Foreground;
        pedalLabel.BorderStyle = BorderStyle.FixedSingle;
        pedalLabel.TextChanged += (_, _) => PedalLabelChanged();
        details.Controls.Add(pedalLabel, 0, 5);
        labelCount.Dock = DockStyle.Fill;
        labelCount.ForeColor = Muted;
        labelCount.TextAlign = ContentAlignment.MiddleRight;
        details.Controls.Add(labelCount, 0, 6);
        selectedCompatibility.Dock = DockStyle.Fill;
        selectedCompatibility.ForeColor = Foreground;
        details.Controls.Add(selectedCompatibility, 0, 10);
        selectedRate.Dock = DockStyle.Fill;
        selectedRate.ForeColor = Foreground;
        details.Controls.Add(selectedRate, 0, 11);
        selectedSize.Dock = DockStyle.Fill;
        selectedSize.ForeColor = Foreground;
        details.Controls.Add(selectedSize, 0, 12);
        details.Controls.Add(MakeLabel("Cab IR (optional)", 9, FontStyle.Regular, Muted), 0, 7);
        var irControls = new FlowLayoutPanel {
            Dock = DockStyle.Fill, WrapContents = false, AutoScroll = true,
            Margin = Padding.Empty, BackColor = Surface
        };
        ConfigureButton(chooseIrButton, "Choose WAV");
        chooseIrButton.Click += (_, _) => ChooseIr();
        irControls.Controls.Add(chooseIrButton);
        ConfigureButton(clearIrButton, "Clear");
        clearIrButton.Click += (_, _) => ClearIr();
        irControls.Controls.Add(clearIrButton);
        details.Controls.Add(irControls, 0, 8);
        selectedIr.Dock = DockStyle.Fill;
        selectedIr.ForeColor = Muted;
        selectedIr.AutoEllipsis = true;
        details.Controls.Add(selectedIr, 0, 9);

        var activityCard = new CardPanel {
            Dock = DockStyle.Fill, BackColor = Surface, BorderColor = Border,
            Margin = new Padding(14, 4, 14, 10), Padding = new Padding(18, 8, 18, 10)
        };
        layout.Controls.Add(activityCard, 0, 2);
        var activity = new TableLayoutPanel {
            Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3,
            Padding = Padding.Empty, BackColor = Surface
        };
        activity.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        activity.RowStyles.Add(new RowStyle(SizeType.Absolute, 8));
        activity.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        activityCard.Controls.Add(activity);
        var activityHeader = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 4 };
        activityHeader.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        activityHeader.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        activityHeader.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        activityHeader.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 140));
        activityHeader.Controls.Add(MakeLabel("Activity", 13, FontStyle.Bold), 0, 0);
        status.Dock = DockStyle.Fill;
        status.ForeColor = Muted;
        status.TextAlign = ContentAlignment.MiddleLeft;
        activityHeader.Controls.Add(status, 1, 0);
        var clearLog = new RoundedButton();
        ConfigureButton(clearLog, "Clear log");
        clearLog.Click += (_, _) => log.Clear();
        activityHeader.Controls.Add(clearLog, 2, 0);
        activityHeader.Controls.Add(cancelButton, 3, 0);
        activity.Controls.Add(activityHeader, 0, 0);
        progress.Dock = DockStyle.Fill;
        progress.Style = ProgressBarStyle.Blocks;
        progress.Minimum = 0;
        progress.Maximum = 100;
        activity.Controls.Add(progress, 0, 1);
        log.Dock = DockStyle.Fill;
        log.Multiline = true;
        log.ReadOnly = true;
        log.ScrollBars = ScrollBars.Vertical;
        log.Font = new Font("Consolas", 9);
        log.BackColor = Color.FromArgb(9, 21, 31);
        log.ForeColor = Muted;
        log.BorderStyle = BorderStyle.FixedSingle;
        log.WordWrap = false;
        activity.Controls.Add(log, 0, 2);

        DragEnter += HandleDragEnter;
        DragDrop += async (_, e) => await HandleDropAsync(e);
        grid.DragEnter += HandleDragEnter;
        grid.DragDrop += async (_, e) => await HandleDropAsync(e);
        FormClosing += (_, e) => {
            if (!busy) return;
            e.Cancel = true;
            MessageBox.Show(this, deviceBusy
                ? "A pedal operation is running. Keep the app and pedal powered until it finishes."
                : "A build is running. Cancel it or wait for it to finish before closing the app.",
                deviceBusy ? "Pedal operation in progress" : "Build in progress",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        };
        UpdateDetail();
    }

    private static string FindRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null) {
            if (File.Exists(System.IO.Path.Combine(directory.FullName, "tools", "nam2zoom", "__main__.py")))
                return directory.FullName;
            directory = directory.Parent;
        }
        throw new InvalidOperationException("Repository tools not found next to this app.");
    }

    private static Label MakeLabel(string text, float size, FontStyle style = FontStyle.Regular,
        Color? color = null)
    {
        return new Label {
            Text = text, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", size, style), ForeColor = color ?? Foreground,
            BackColor = Color.Transparent
        };
    }

    private static void ConfigureButton(Button button, string text, bool primary = false,
        bool blue = false, bool danger = false)
    {
        button.Text = text;
        button.AutoSize = true;
        button.MinimumSize = new Size(0, 38);
        button.Margin = new Padding(0, 4, 8, 0);
        button.Padding = new Padding(13, 0, 13, 0);
        button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = primary || blue ? 0 : 1;
        button.FlatAppearance.BorderColor = danger ? Color.FromArgb(108, 50, 58) : Border;
        button.FlatAppearance.MouseOverBackColor = primary ? Color.FromArgb(83, 217, 196)
            : blue ? Color.FromArgb(65, 157, 250)
            : danger ? Color.FromArgb(67, 39, 47) : Color.FromArgb(48, 65, 79);
        button.BackColor = primary ? Accent : blue ? Blue
            : danger ? Color.FromArgb(48, 35, 43) : SurfaceRaised;
        button.ForeColor = primary || blue ? Color.FromArgb(7, 22, 29)
            : danger ? Danger : Foreground;
        button.Font = new Font("Segoe UI", 9, FontStyle.Bold);
        button.UseVisualStyleBackColor = false;
        button.Cursor = Cursors.Hand;
        if (button is RoundedButton rounded) {
            rounded.HoverColor = button.FlatAppearance.MouseOverBackColor;
            rounded.ButtonBorderColor = primary || blue ? Color.Transparent
                : danger ? Color.FromArgb(108, 50, 58) : Border;
        }
    }

    private static void AddButton(FlowLayoutPanel toolbar, string text, EventHandler click,
        bool primary = false)
    {
        var button = new RoundedButton();
        ConfigureButton(button, text, primary);
        button.Click += click;
        toolbar.Controls.Add(button);
    }

    private Button MakeWindowButton(WindowButtonKind kind, EventHandler click)
    {
        var button = new WindowButton(kind) {
            Size = new Size(46, 46), Top = 2,
            BackColor = Color.FromArgb(20, 32, 44),
            ForeColor = kind == WindowButtonKind.Close ? Danger : Muted,
            Anchor = AnchorStyles.Top | AnchorStyles.Right
        };
        button.Click += click;
        return button;
    }

    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr handle, int message, IntPtr wParam, IntPtr lParam);

    private void BeginWindowDrag(MouseEventArgs e)
    {
        if (e.Button != MouseButtons.Left || WindowState == FormWindowState.Maximized) return;
        ReleaseCapture();
        SendMessage(Handle, 0xA1, (IntPtr)2, IntPtr.Zero);
    }

    private void ToggleMaximize()
    {
        WindowState = WindowState == FormWindowState.Maximized
            ? FormWindowState.Normal : FormWindowState.Maximized;
    }

    protected override void WndProc(ref Message message)
    {
        const int wmNcHitTest = 0x84;
        const int grip = 7;
        if (message.Msg == wmNcHitTest && WindowState == FormWindowState.Normal) {
            base.WndProc(ref message);
            var point = PointToClient(new Point((short)(message.LParam.ToInt64() & 0xffff),
                (short)((message.LParam.ToInt64() >> 16) & 0xffff)));
            if (point.Y <= grip) message.Result = (IntPtr)(point.X <= grip ? 13
                : point.X >= ClientSize.Width - grip ? 14 : 12);
            else if (point.Y >= ClientSize.Height - grip) message.Result = (IntPtr)(point.X <= grip ? 16
                : point.X >= ClientSize.Width - grip ? 17 : 15);
            else if (point.X <= grip) message.Result = (IntPtr)10;
            else if (point.X >= ClientSize.Width - grip) message.Result = (IntPtr)11;
            return;
        }
        base.WndProc(ref message);
    }

    private void UpdateActions()
    {
        buildButton.Enabled = !busy && models.Count > 0
            && models.All(m => m.Status is "Ready" or "Adapt")
            && LabelsValid();
        installButton.Enabled = buildButton.Enabled;
        uninstallButton.Enabled = !busy;
        backupCheck.Enabled = !busy;
        bestEffortCheck.Enabled = !busy;
        epochsInput.Enabled = !busy;
        previewButton.Enabled = !busy && previewRoot is not null && Directory.Exists(previewRoot);
        removeButton.Enabled = !busy && SelectedIndex >= 0;
        moveUpButton.Enabled = !busy && SelectedIndex > 0;
        moveDownButton.Enabled = !busy && SelectedIndex >= 0 && SelectedIndex < models.Count - 1;
        pedalLabel.Enabled = !busy && SelectedIndex >= 0;
        chooseIrButton.Enabled = !busy && SelectedIndex >= 0;
        clearIrButton.Enabled = !busy && SelectedIndex >= 0
            && models[SelectedIndex].IrPath is not null;
        cancelButton.Enabled = busy && !deviceBusy && jobCancellation is not null &&
            !jobCancellation.IsCancellationRequested;
        status.Text = deviceBusy ? "Pedal operation in progress - do not disconnect" :
            busy ? "Building..." : $"{models.Count}/5 models  |  {lastAction}";
        if (!busy) {
            determinateProgress = false;
            progress.Style = ProgressBarStyle.Blocks;
            progress.Value = 0;
        } else if (!determinateProgress) {
            progress.Style = ProgressBarStyle.Marquee;
        }
    }

    private bool LabelsValid() => models.All(m => m.Label.Length is >= 1 and <= 5
        && m.Label.All(c => c <= 127 && (char.IsLetterOrDigit(c) || c is '-' or '_')))
        && models.Select(m => m.Label.ToUpperInvariant()).Distinct().Count() == models.Count;

    private int SelectedIndex => grid.SelectedRows.Count == 1 ? grid.SelectedRows[0].Index : -1;

    private void RefreshGrid(int select = -1)
    {
        grid.Rows.Clear();
        for (int i = 0; i < models.Count; i++)
            grid.Rows.Add((i + 1).ToString("00"), models[i].Label,
                System.IO.Path.GetFileName(models[i].Path), models[i].Status);
        grid.ClearSelection();
        if (select >= 0 && select < grid.Rows.Count) grid.Rows[select].Selected = true;
        UpdateDetail();
        UpdateActions();
    }

    private void UpdateDetail()
    {
        var index = SelectedIndex;
        updatingLabel = true;
        if (index < 0 || index >= models.Count) {
            selectedFile.Text = "No model selected";
            selectedPath.Text = "Select a model from the list to view its details and settings.";
            selectedCompatibility.Text = "Compatibility\r\n-";
            selectedRate.Text = "Sample rate\r\n-";
            selectedSize.Text = "File size\r\n-";
            selectedIr.Text = "No IR selected";
            pedalLabel.Text = "";
        } else {
            var model = models[index];
            selectedFile.Text = System.IO.Path.GetFileName(model.Path);
            selectedPath.Text = model.Path;
            selectedCompatibility.Text = $"Compatibility\r\n{model.Status}";
            selectedCompatibility.ForeColor = model.Status is "Ready" or "Adapt" ? Success
                : model.Status == "Unsupported" ? Danger : Foreground;
            selectedRate.Text = model.SampleRate == 0 ? "Sample rate\r\nUnknown" :
                $"Sample rate\r\n{model.SampleRate / 1000.0:0.0} kHz";
            selectedSize.Text = File.Exists(model.Path) ?
                $"File size\r\n{new FileInfo(model.Path).Length / 1024.0:0.0} KB" :
                "File size\r\nMissing file";
            selectedIr.Text = model.IrPath ?? "No IR selected";
            selectedIr.AccessibleDescription = selectedIr.Text;
            pedalLabel.Text = model.Label;
        }
        if (index < 0 || index >= models.Count) selectedCompatibility.ForeColor = Foreground;
        labelCount.Text = $"{pedalLabel.Text.Length}/5";
        pedalLabel.BackColor = LabelsValid() ? SurfaceRaised : Color.FromArgb(83, 47, 52);
        updatingLabel = false;
        UpdateActions();
    }

    private void PedalLabelChanged()
    {
        if (updatingLabel || SelectedIndex < 0 || busy) return;
        var cleaned = new string(pedalLabel.Text.ToUpperInvariant()
            .Where(c => c <= 127 && (char.IsLetterOrDigit(c) || c is '-' or '_'))
            .Take(5).ToArray());
        if (pedalLabel.Text != cleaned) {
            var caret = Math.Min(pedalLabel.SelectionStart, cleaned.Length);
            updatingLabel = true;
            pedalLabel.Text = cleaned;
            pedalLabel.SelectionStart = caret;
            updatingLabel = false;
        }
        models[SelectedIndex].Label = cleaned;
        grid.Rows[SelectedIndex].Cells[1].Value = cleaned;
        labelCount.Text = $"{cleaned.Length}/5";
        pedalLabel.BackColor = LabelsValid() ? SurfaceRaised : Color.FromArgb(83, 47, 52);
        UpdateActions();
    }

    private void ChooseIr()
    {
        if (busy || SelectedIndex < 0) return;
        using var dialog = new OpenFileDialog {
            Filter = "WAV impulse responses (*.wav)|*.wav", Title = "Choose a mono cab IR"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        models[SelectedIndex].IrPath = dialog.FileName;
        previewRoot = null;
        UpdateDetail();
    }

    private void ClearIr()
    {
        if (busy || SelectedIndex < 0) return;
        models[SelectedIndex].IrPath = null;
        previewRoot = null;
        UpdateDetail();
    }

    private async Task AddFromDialogAsync()
    {
        using var dialog = new OpenFileDialog {
            Filter = "NAM models (*.nam)|*.nam", Multiselect = true, Title = "Add NAM models"
        };
        if (dialog.ShowDialog(this) == DialogResult.OK) await AddPathsAsync(dialog.FileNames);
    }

    private void HandleDragEnter(object? sender, DragEventArgs e)
    {
        e.Effect = e.Data?.GetDataPresent(DataFormats.FileDrop) == true
            ? DragDropEffects.Copy : DragDropEffects.None;
    }

    private async Task HandleDropAsync(DragEventArgs e)
    {
        if (e.Data?.GetData(DataFormats.FileDrop) is string[] paths) await AddPathsAsync(paths);
    }

    private string NewLabel(string path)
    {
        var stem = new string(System.IO.Path.GetFileNameWithoutExtension(path).ToUpperInvariant()
            .Where(c => c <= 127 && char.IsLetterOrDigit(c)).Take(5).ToArray());
        if (stem.Length == 0) stem = "NAM";
        if (models.All(m => !string.Equals(m.Label, stem, StringComparison.OrdinalIgnoreCase))) return stem;
        for (int suffix = 2; suffix <= 9; suffix++) {
            var candidate = stem[..Math.Min(4, stem.Length)] + suffix;
            if (models.All(m => !string.Equals(m.Label, candidate, StringComparison.OrdinalIgnoreCase)))
                return candidate;
        }
        return "NAM";
    }

    private async Task AddPathsAsync(IEnumerable<string> paths)
    {
        if (busy) return;
        var candidates = paths.Where(p => p.EndsWith(".nam", StringComparison.OrdinalIgnoreCase)).ToArray();
        if (candidates.Length == 0) { MessageBox.Show(this, "Drop .nam files only."); return; }
        var selected = candidates
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Where(p => models.All(m => !string.Equals(m.Path, p, StringComparison.OrdinalIgnoreCase)))
            .ToArray();
        if (selected.Length == 0) return;
        if (models.Count + selected.Length > 5) {
            MessageBox.Show(this, "The current bank supports at most five models."); return;
        }
        busy = true;
        UpdateActions();
        try {
            foreach (var path in selected) {
                if (models.Any(m => string.Equals(m.Path, path, StringComparison.OrdinalIgnoreCase))) continue;
                var entry = new ModelEntry { Path = path, Label = NewLabel(path) };
                models.Add(entry);
                RefreshGrid(models.Count - 1);
                var (exit, output) = await RunPythonAsync(["inspect-hybrid", path]);
                if (exit == 0) {
                    try {
                        var result = JsonDocument.Parse(output).RootElement;
                        entry.Status = result.GetProperty("status").GetString() switch {
                            "direct" => "Ready", "adaptable" => "Adapt", _ => "Unsupported"
                        };
                        if (result.TryGetProperty("sample_rate", out var rate)
                            && rate.ValueKind == JsonValueKind.Number)
                            entry.SampleRate = rate.GetInt32();
                        if (entry.Status == "Unsupported")
                            log.AppendText($"{System.IO.Path.GetFileName(path)}: "
                                + result.GetProperty("reason").GetString() + "\r\n");
                    } catch (JsonException) { entry.Status = "Unsupported"; }
                } else {
                    entry.Status = "Unsupported";
                    log.AppendText($"{System.IO.Path.GetFileName(path)}: {output.Trim()}\r\n");
                }
                RefreshGrid(models.Count - 1);
            }
        } catch (Exception ex) {
            log.AppendText($"Validation failed: {ex.Message}\r\n");
        } finally {
            busy = false;
            UpdateActions();
        }
    }

    private void RemoveSelected()
    {
        if (busy || SelectedIndex < 0) return;
        var index = SelectedIndex;
        models.RemoveAt(index);
        RefreshGrid(Math.Min(index, models.Count - 1));
    }

    private void MoveSelected(int direction)
    {
        if (busy) return;
        var index = SelectedIndex;
        var destination = index + direction;
        if (index < 0 || destination < 0 || destination >= models.Count) return;
        (models[index], models[destination]) = (models[destination], models[index]);
        RefreshGrid(destination);
    }

    private void SaveProject()
    {
        if (busy || models.Count == 0) return;
        using var dialog = new SaveFileDialog {
            Filter = "nam2zoom list (*.n2zbank.json)|*.n2zbank.json",
            FileName = "models.n2zbank.json"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try {
            var entries = models.Select(m => new { m.Path, m.Label, m.IrPath }).ToArray();
            File.WriteAllText(dialog.FileName, JsonSerializer.Serialize(entries,
                new JsonSerializerOptions { WriteIndented = true }));
            log.AppendText($"Saved {dialog.FileName}\r\n");
        } catch (Exception ex) { MessageBox.Show(this, ex.Message, "Save failed"); }
    }

    private async Task OpenProjectAsync()
    {
        if (busy) return;
        using var dialog = new OpenFileDialog {
            Filter = "nam2zoom list (*.n2zbank.json)|*.n2zbank.json"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try {
            var entries = JsonSerializer.Deserialize<List<ModelEntry>>(File.ReadAllText(dialog.FileName))
                ?? throw new InvalidDataException("Empty list");
            if (entries.Count > 5 || entries.Any(m => !File.Exists(m.Path)))
                throw new InvalidDataException("List exceeds five models or contains missing files");
            if (entries.Any(m => m.IrPath is not null
                && (!File.Exists(m.IrPath)
                    || !m.IrPath.EndsWith(".wav", StringComparison.OrdinalIgnoreCase))))
                throw new InvalidDataException("List contains a missing or invalid cab IR WAV");
            if (entries.Select(m => m.Path).Distinct(StringComparer.OrdinalIgnoreCase).Count() != entries.Count)
                throw new InvalidDataException("List contains the same NAM file more than once");
            if (entries.Any(m => m.Label.Length is < 1 or > 5 ||
                !m.Label.All(c => c <= 127 && (char.IsLetterOrDigit(c) || c is '-' or '_')))
                || entries.Select(m => m.Label.ToUpperInvariant()).Distinct().Count() != entries.Count)
                throw new InvalidDataException("List contains invalid or duplicate pedal labels");
            models.Clear();
            RefreshGrid();
            await AddProjectEntriesAsync(entries);
        } catch (Exception ex) { MessageBox.Show(this, ex.Message, "Open failed"); }
    }

    private async Task AddProjectEntriesAsync(List<ModelEntry> entries)
    {
        await AddPathsAsync(entries.Select(e => e.Path));
        for (int i = 0; i < Math.Min(entries.Count, models.Count); i++) {
            models[i].Label = entries[i].Label;
            models[i].IrPath = entries[i].IrPath;
        }
        RefreshGrid();
    }

    private static string EnsureBundledTrainingDi()
    {
        var folder = System.IO.Path.Combine(Environment.GetFolderPath(
            Environment.SpecialFolder.LocalApplicationData), "nam2zoom", "training");
        Directory.CreateDirectory(folder);
        var target = System.IO.Path.Combine(folder, "TRAINING_DI.wav");
        if (File.Exists(target) && Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(target)))
            == BundledDiSha256) return target;
        var temporary = target + ".tmp";
        try {
            using var resource = typeof(MainForm).Assembly.GetManifestResourceStream(
                "Nam2ZoomDesktop.TRAINING_DI.wav")
                ?? throw new FileNotFoundException("Bundled training DI is missing from the app");
            using (var destination = File.Create(temporary)) resource.CopyTo(destination);
            if (Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(temporary))) != BundledDiSha256)
                throw new InvalidDataException("Bundled training DI failed its SHA-256 check");
            File.Move(temporary, target, true);
            return target;
        } finally {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }

    private void OpenPreview()
    {
        if (previewRoot is null || !Directory.Exists(previewRoot)) return;
        try {
            Process.Start(new ProcessStartInfo(previewRoot) { UseShellExecute = true });
        } catch (Exception ex) {
            MessageBox.Show(this, ex.Message, "Could not open A/B folder");
        }
    }

    private async Task UninstallAsync()
    {
        if (!uninstallButton.Enabled) return;
        var fullBackup = backupCheck.Checked;
        var confirmation = MessageBox.Show(this,
            "Remove N2Z Bank from the connected supported MS Plus pedal? The app will verify the pedal, "
            + "autosave setting, all saved patches, and the installed effect before writing. "
            + (fullBackup
                ? "A full device backup will be saved beside the app EXE. "
                : "No full device backup will be saved; only the prior effect list and bank files "
                  + "will be retained in a local session. ")
            + "Keep a stock patch selected, autosave OFF, and the pedal powered and connected. "
            + "Do not disconnect during removal. A failed transfer could leave the pedal unusable.\n\n"
            + "Approve uninstalling N2Z Bank?",
            "Approve pedal uninstall", MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2);
        if (confirmation != DialogResult.Yes) return;

        busy = true;
        deviceBusy = true;
        UpdateActions();
        log.AppendText(fullBackup
            ? "Starting guarded pedal backup and uninstall. Do not disconnect.\r\n"
            : "Starting guarded uninstall without full backup. Do not disconnect.\r\n");
        try {
            var sessionRoot = fullBackup
                ? System.IO.Path.Combine(AppContext.BaseDirectory, "Backup")
                : System.IO.Path.Combine(Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData), "nam2zoom", "sessions");
            var args = new List<string> {
                "uninstall-bank", "--session", System.IO.Path.Combine(sessionRoot,
                    DateTime.Now.ToString("yyyyMMdd-HHmmss-fff")), "--ack-risk"
            };
            if (!fullBackup) args.Add("--no-backup");
            var (exit, output) = await RunPythonAsync(args, stream: true);
            if (exit != 0) throw new InvalidOperationException(
                "Pedal operation stopped. Keep the pedal powered; read the log before reconnecting or retrying.");
            var absent = output.Contains("N2Z Bank is not installed;", StringComparison.Ordinal);
            lastAction = absent ? "N2Z Bank was not installed" : "N2Z Bank uninstalled and verified";
            MessageBox.Show(this, absent ? "N2Z Bank is not installed; no pedal files were changed."
                : "N2Z Bank was uninstalled and verified.", "Pedal uninstall complete");
        } catch (Exception ex) {
            log.AppendText($"Operation stopped: {ex.Message}\r\n");
            lastAction = "Pedal operation stopped - see log";
            MessageBox.Show(this, ex.Message, "Pedal operation stopped");
        } finally {
            deviceBusy = false;
            busy = false;
            UpdateActions();
        }
    }

    private async Task BuildAsync(bool installAfterBuild)
    {
        grid.EndEdit();
        if (!LabelsValid()) { MessageBox.Show(this, "Use unique 1-5 character pedal labels."); return; }
        if (!(installAfterBuild ? installButton.Enabled : buildButton.Enabled)) return;
        var fullBackup = backupCheck.Checked;
        var bestEffort = bestEffortCheck.Checked;
        var epochs = (int)epochsInput.Value;
        using var dialog = new FolderBrowserDialog { Description = "Choose a folder for the build" };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        var output = System.IO.Path.Combine(dialog.SelectedPath,
            "n2z-bank-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"));
        jobCancellation = new CancellationTokenSource();
        busy = true;
        previewRoot = null;
        UpdateActions();
        log.AppendText($"Building {models.Count} model(s) -> {output}\r\n");
        if (models.Any(m => m.Status == "Adapt" || m.IrPath is not null))
            log.AppendText($"PC adaptation: {epochs} epochs\r\n");
        try {
            var trainingDi = models.Any(m => m.Status == "Adapt" || m.IrPath is not null)
                ? EnsureBundledTrainingDi() : null;
            var resolved = new List<string>();
            var previews = new List<(string Label, string Directory)>();
            var lowFidelity = new List<string>();
            var irLevelChanges = new List<string>();
            foreach (var model in models) {
                if (model.Status == "Ready" && model.IrPath is null) {
                    resolved.Add(model.Path);
                    continue;
                }
                var cache = System.IO.Path.Combine(Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData), "nam2zoom", "adapt-cache");
                log.AppendText($"Adapting {System.IO.Path.GetFileName(model.Path)}"
                    + (model.IrPath is null ? "" : $" with {System.IO.Path.GetFileName(model.IrPath)}")
                    + "\r\n");
                var adaptArgs = new List<string> {
                    "adapt", model.Path, "--training-di", trainingDi!, "--cache", cache,
                    "--epochs", epochs.ToString(System.Globalization.CultureInfo.InvariantCulture)
                };
                if (bestEffort) adaptArgs.Add("--best-effort");
                if (model.IrPath is not null) {
                    adaptArgs.Add("--ir");
                    adaptArgs.Add(model.IrPath);
                }
                var (adaptExit, adaptOutput) = await RunPythonAsync(adaptArgs,
                    training: true, stream: true, cancellationToken: jobCancellation.Token);
                var marker = adaptOutput.Split('\n').Select(line => line.Trim())
                    .LastOrDefault(line => line.StartsWith("READY_MODEL=", StringComparison.Ordinal));
                if (adaptExit != 0 || marker is null || !File.Exists(marker[12..]))
                    throw new InvalidOperationException($"Adaptation failed for {model.Label}; see the build log.");
                resolved.Add(marker[12..]);
                var qualityLine = adaptOutput.Split('\n').Select(line => line.Trim())
                    .LastOrDefault(line => line.StartsWith("QUALITY_RESULT=", StringComparison.Ordinal));
                if (qualityLine is null)
                    throw new InvalidDataException($"Adaptation produced no quality result for {model.Label}");
                using (var quality = JsonDocument.Parse(qualityLine[15..])) {
                    if (quality.RootElement.GetProperty("status").GetString() == "best-effort") {
                        lowFidelity.Add($"{model.Label}: ESR "
                            + quality.RootElement.GetProperty("esr").GetDouble().ToString("0.0000")
                            + ", correlation "
                            + quality.RootElement.GetProperty("correlation").GetDouble().ToString("0.0000"));
                    }
                    if (quality.RootElement.TryGetProperty("ir_gain_db", out var irGain)
                        && irGain.GetDouble() < -0.1) {
                        irLevelChanges.Add($"{model.Label}: "
                            + irGain.GetDouble().ToString("0.00") + " dB");
                    }
                }
                var previewLine = adaptOutput.Split('\n').Select(line => line.Trim())
                    .LastOrDefault(line => line.StartsWith("PREVIEW_DIR=", StringComparison.Ordinal));
                if (previewLine is null || !Directory.Exists(previewLine[12..]))
                    throw new InvalidDataException($"Adaptation produced no A/B preview for {model.Label}");
                previews.Add((model.Label, previewLine[12..]));
                var converted = ConvertedNam.Save(marker[12..], model.Path, AppContext.BaseDirectory);
                log.AppendText($"Converted NAM saved: {converted}\r\n");
            }
            var args = new List<string> { "build-bank" };
            args.AddRange(resolved);
            foreach (var model in models) { args.Add("--label"); args.Add(model.Label); }
            args.Add("--output"); args.Add(output);
            var (exit, _) = await RunPythonAsync(args, stream: true,
                cancellationToken: jobCancellation.Token);
            if (exit != 0) throw new InvalidOperationException("Effect build failed; see the log.");
            jobCancellation.Token.ThrowIfCancellationRequested();
            var effect = System.IO.Path.Combine(output, "build", "N2ZBANK.ZD2");
            var icon = System.IO.Path.Combine(output, "build", "N2ZBANK.ZIC");
            if (!File.Exists(effect) || !File.Exists(icon))
                throw new FileNotFoundException("Build did not produce the effect and icon pair.");
            if (previews.Count > 0) {
                previewRoot = System.IO.Path.Combine(output, "preview");
                foreach (var (label, source) in previews) {
                    var destination = System.IO.Path.Combine(previewRoot, label);
                    Directory.CreateDirectory(destination);
                    foreach (var name in new[] { "original.wav", "converted.wav" })
                        File.Copy(System.IO.Path.Combine(source, name),
                            System.IO.Path.Combine(destination, name));
                }
            }
            lastAction = lowFidelity.Count > 0 ? "Best-effort build complete" : "Offline build complete";
            if (!installAfterBuild) {
                var warning = lowFidelity.Count == 0 ? "" :
                    "\n\nLower-fidelity conversion:\n" + string.Join("\n", lowFidelity)
                    + "\nListen using Open A/B before installing.";
                if (irLevelChanges.Count > 0)
                    warning += "\n\nCab IR output was attenuated to avoid clipping:\n"
                        + string.Join("\n", irLevelChanges)
                        + "\nExpect a lower level; listen to the A/B preview.";
                MessageBox.Show(this, $"Offline effect built in:\n{System.IO.Path.Combine(output, "build")}" + warning,
                    "Build complete");
                return;
            }
            if (lowFidelity.Count > 0) {
                OpenPreview();
                var continueInstall = MessageBox.Show(this,
                    "This bank contains a lower-fidelity conversion:\n"
                    + string.Join("\n", lowFidelity)
                    + "\n\nThe A/B preview folder has been opened. Listen to the original and "
                    + "converted clips before deciding. Continue to the separate pedal install approval?",
                    "Review conversion", MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
                    MessageBoxDefaultButton.Button2);
                if (continueInstall != DialogResult.Yes) {
                    log.AppendText("Install declined; best-effort offline build remains available.\r\n");
                    return;
                }
            }
            var effectHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(effect)));
            var iconHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(icon)));
            var confirmation = MessageBox.Show(this,
                (fullBackup
                    ? "The app will save a full device backup before replacing N2Z Bank. "
                    : "No full device backup will be saved. The app will still inspect all saved patches "
                      + "and retain the current effect list and bank files for recovery. "
                      + "If installation fails, there will be no complete pedal backup. ")
                + "An existing N2Z Bank will be uninstalled first. "
                + "It will refuse if the current or any saved patch contains a non-stock effect.\n\n"
                + "Supported targets are MS-50G+ firmware 1.40, MS-70CDR+ firmware 1.20, and MS-60B+ firmware 1.20. "
                + "The bank has been hardware-tested on MS-50G+ and MS-70CDR+; MS-60B+ support is experimental.\n\n"
                + (irLevelChanges.Count > 0
                    ? "Cab IR level reduction to avoid clipping: "
                      + string.Join(", ", irLevelChanges) + ". Expect a lower output level.\n\n"
                    : "")
                + "The 14-layer, 3-channel optimized bank declares 150 load. "
                + "One exact build passed saved-patch boot tests with ZNR, RackComp, TS Drive, Hall REV, and LowPassFL. "
                + "A saved patch with FD B-MAN showed PROCESS OVERFLOW on N2Z after reboot. "
                + "This newly built binary has not passed a saved-patch test. "
                + "Do not save it in a patch until separately tested. "
                + (lowFidelity.Count > 0 ? "It contains a lower-fidelity NAM conversion. " : "")
                + "Its memory use and real-time load are unverified. "
                + "It could slow, crackle, freeze, or permanently disable the device. "
                + "Keep the pedal powered and connected. "
                + "Use it as the sole effect for initial audition.\n\n"
                + $"N2ZBANK.ZD2 SHA-256: {effectHash}\nN2ZBANK.ZIC SHA-256: {iconHash}\n\n"
                + "Do you approve installing this exact pair?",
                "Approve pedal install", MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
                MessageBoxDefaultButton.Button2);
            if (confirmation != DialogResult.Yes) {
                log.AppendText("Install declined; offline build remains available.\r\n");
                return;
            }
            deviceBusy = true;
            UpdateActions();
            log.AppendText(fullBackup
                ? "Starting guarded pedal backup and install. Do not disconnect.\r\n"
                : "Starting guarded install without full backup. Do not disconnect.\r\n");
            var sessionRoot = fullBackup
                ? System.IO.Path.Combine(AppContext.BaseDirectory, "Backup")
                : System.IO.Path.Combine(Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData), "nam2zoom", "sessions");
            var installArgs = new List<string> {
                "install-bank", effect, "--session", System.IO.Path.Combine(sessionRoot,
                    DateTime.Now.ToString("yyyyMMdd-HHmmss-fff")),
                "--approved-zd2-sha256", effectHash, "--approved-zic-sha256", iconHash,
                "--ack-risk"
            };
            if (!fullBackup) installArgs.Add("--no-backup");
            var (installExit, _) = await RunPythonAsync(installArgs, stream: true);
            if (installExit != 0) throw new InvalidOperationException(
                "Pedal operation stopped. Keep the pedal powered; read the log before reconnecting or retrying.");
            lastAction = "N2Z Bank installed and verified";
            MessageBox.Show(this, "N2Z Bank is installed and verified. "
                + "Test this build first in an unsaved patch; its saved-patch boot behavior is unverified.",
                "Install complete");
        } catch (OperationCanceledException) {
            log.AppendText("Build cancelled. No pedal files were changed.\r\n");
            lastAction = "Build cancelled";
        } catch (Exception ex) {
            log.AppendText($"Operation stopped: {ex.Message}\r\n");
            lastAction = deviceBusy ? "Pedal operation stopped - see log" : "Build failed";
            MessageBox.Show(this, ex.Message, deviceBusy ? "Pedal operation stopped" : "Build failed");
        } finally {
            deviceBusy = false;
            jobCancellation.Dispose();
            jobCancellation = null;
            busy = false;
            UpdateActions();
        }
    }

    private async Task<(int Exit, string Output)> RunPythonAsync(
        IEnumerable<string> command, bool training = false, bool stream = false,
        CancellationToken cancellationToken = default)
    {
        if (PortableRuntime.IsPortable(root) && !PortableRuntime.VisualCppReady()) {
            var approval = MessageBox.Show(this,
                "The Microsoft Visual C++ x64 runtime is needed for native Python/training libraries. "
                + "Download it from Microsoft and run its signed installer? Windows will request administrator approval. "
                + "No pedal changes will be made during setup.",
                "Install Windows prerequisite", MessageBoxButtons.YesNo,
                MessageBoxIcon.Question, MessageBoxDefaultButton.Button2);
            if (approval != DialogResult.Yes) throw new OperationCanceledException("Microsoft runtime setup declined");
            await PortableRuntime.EnsureVisualCppAsync(root,
                line => { if (!IsDisposed && IsHandleCreated) BeginInvoke(() => log.AppendText(line + "\r\n")); },
                cancellationToken);
        }
        if (training && PortableRuntime.IsPortable(root) && !PortableRuntime.TrainingReady(root)) {
            var answer = MessageBox.Show(this,
                "Conversion needs a one-time download of Python training packages, which can use several GB. "
                + "Packages stay inside this extracted app folder. No developer tools are needed.\n\n"
                + "Use NVIDIA GPU acceleration? Yes: CUDA packages (compatible NVIDIA driver required). "
                + "No: CPU packages (slower conversion). Cancel: stop this build.",
                "Set up model conversion", MessageBoxButtons.YesNoCancel,
                MessageBoxIcon.Question, MessageBoxDefaultButton.Button2);
            if (answer == DialogResult.Cancel) throw new OperationCanceledException("Training setup cancelled");
            status.Text = "Setting up conversion dependencies";
            await PortableRuntime.EnsureTrainingAsync(root, answer == DialogResult.Yes,
                line => { if (!IsDisposed && IsHandleCreated) BeginInvoke(() => log.AppendText(line + "\r\n")); },
                cancellationToken);
        }
        var executable = training ? trainingPython : python;
        if (!File.Exists(executable)) throw new FileNotFoundException("Build Python is missing", executable);
        var info = new ProcessStartInfo(executable) {
            WorkingDirectory = root, RedirectStandardOutput = true,
            RedirectStandardError = true, UseShellExecute = false, CreateNoWindow = true
        };
        info.Environment["PYTHONPATH"] = System.IO.Path.Combine(root, "tools");
        info.Environment["PYTHONUNBUFFERED"] = "1";
        info.ArgumentList.Add("-m");
        info.ArgumentList.Add("nam2zoom");
        foreach (var argument in command) info.ArgumentList.Add(argument);
        using var process = Process.Start(info) ?? throw new InvalidOperationException("Could not start Python");
        using var registration = cancellationToken.Register(() => {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
        });
        async Task<string> DrainAsync(StreamReader reader)
        {
            var collected = new StringBuilder();
            string? line;
            while ((line = await reader.ReadLineAsync()) is not null) {
                collected.AppendLine(line);
                var capturedLine = line;
                if (stream && !IsDisposed && IsHandleCreated)
                    BeginInvoke(() => {
                        log.AppendText(capturedLine + "\r\n");
                        UpdateActivity(capturedLine);
                    });
            }
            return collected.ToString();
        }
        var stdout = DrainAsync(process.StandardOutput);
        var stderr = DrainAsync(process.StandardError);
        await process.WaitForExitAsync();
        var output = (await stdout) + (await stderr);
        cancellationToken.ThrowIfCancellationRequested();
        return (process.ExitCode, output);
    }

    private void UpdateActivity(string line)
    {
        var match = Regex.Match(line, @"^(Patch|File) (\d+)/(\d+):");
        if (match.Success && int.TryParse(match.Groups[2].Value, out var current)
            && int.TryParse(match.Groups[3].Value, out var total) && total > 0) {
            determinateProgress = true;
            progress.Style = ProgressBarStyle.Blocks;
            progress.Value = Math.Clamp(100 * current / total, 0, 100);
            status.Text = $"Backing up: {current} of {total} {match.Groups[1].Value.ToLowerInvariant()}s";
        } else if (line.Contains("Backup complete", StringComparison.OrdinalIgnoreCase)) {
            determinateProgress = false;
            progress.Style = ProgressBarStyle.Marquee;
            status.Text = "Backup complete; checking pedal state";
        } else if (line.Contains("Starting non-cancellable pedal uninstall", StringComparison.Ordinal)) {
            status.Text = "Uninstalling - keep pedal connected";
        } else if (line.Contains("Starting non-cancellable pedal transfer", StringComparison.Ordinal)) {
            status.Text = "Installing - keep pedal connected";
        }
    }
}
