using System.Globalization;
using System.Text.Json;

namespace Nam2ZoomDesktop;

public static class ConversionQuality
{
    public static string? ReviewLine(string source, string label, JsonElement quality)
    {
        var esr = quality.GetProperty("esr").GetDouble();
        var limit = quality.GetProperty("max_esr").GetDouble();
        var correlation = quality.GetProperty("correlation").GetDouble();
        if (!double.IsFinite(esr) || esr < 0 || !double.IsFinite(limit) || limit <= 0 || limit >= 1
            || !double.IsFinite(correlation) || correlation < -1 || correlation > 1)
            throw new InvalidDataException("Conversion returned invalid quality scores.");
        var reasons = new List<string>();
        if (esr > limit)
            reasons.Add($"ESR {Number(esr)} > limit {Number(limit)}");
        if (correlation < 0.95)
            reasons.Add($"correlation {Number(correlation)} < limit 0.9500");
        return reasons.Count == 0 ? null : $"{Path.GetFileName(source)} ({label}): "
            + string.Join("; ", reasons);
    }

    private static string Number(double value) => value.ToString("0.0000####", CultureInfo.InvariantCulture);
}
