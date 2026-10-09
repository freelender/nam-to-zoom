using System.Globalization;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Input.Platform;
using Avalonia.Input.TextInput;
using Avalonia.Interactivity;

namespace Nam2Zoom;

/// <summary>A whole-number editor for the supported training epoch range.</summary>
public sealed class EpochUpDown : NumericUpDown
{
    protected override Type StyleKeyOverride => typeof(NumericUpDown);
    private TextBox? editor;

    public EpochUpDown()
    {
        Minimum = 1; Maximum = 300; Increment = 1; Value = 100;
        FormatString = "0"; ParsingNumberStyle = NumberStyles.None; ClipValueToMinMax = true;
        Classes.Add("epochs");
        AddHandler(TextInputEvent, (_, e) => {
            if (e.Text is { } text && !DigitsOnly(text)) e.Handled = true;
        }, RoutingStrategies.Tunnel);
        LostFocus += (_, _) => {
            if (!IsKeyboardFocusWithin) {
                Value = Math.Clamp(Value ?? 100, Minimum, Maximum);
                Text = Value.Value.ToString("0", CultureInfo.InvariantCulture);
            }
        };
    }

    protected override void OnApplyTemplate(TemplateAppliedEventArgs e)
    {
        if (editor is not null) editor.PastingFromClipboard -= PasteDigits;
        base.OnApplyTemplate(e);
        editor = e.NameScope.Find<TextBox>("PART_TextBox");
        if (editor is null) return;
        TextInputOptions.SetContentType(editor, TextInputContentType.Digits);
        editor.PastingFromClipboard += PasteDigits;
    }

    private static bool DigitsOnly(string text) => text.All(c => c is >= '0' and <= '9');

    private async void PasteDigits(object? sender, RoutedEventArgs e)
    {
        e.Handled = true;
        if (sender is not TextBox textBox || TopLevel.GetTopLevel(this)?.Clipboard is not { } clipboard) return;
        var text = await clipboard.TryGetTextAsync();
        // Reject the complete paste rather than silently changing its meaning.
        if (!string.IsNullOrEmpty(text) && DigitsOnly(text) && textBox.IsFocused && IsEffectivelyEnabled)
            textBox.SelectedText = text;
    }
}
