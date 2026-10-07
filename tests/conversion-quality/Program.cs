using System.Globalization;
using System.Text.Json;
using Nam2ZoomDesktop;

static string? Review(double esr, double correlation = .99, double limit = .05,
                      string name = "High Gain.nam", string label = "GAIN")
{
    using var json = JsonDocument.Parse(JsonSerializer.Serialize(new { esr, correlation, max_esr = limit }));
    return ConversionQuality.ReviewLine(name, label, json.RootElement);
}

CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("de-DE");
if (Review(.05, .95) is not null) throw new Exception("Passing boundary triggered review");
var highGain = Review(.05384)!;
if (!highGain.Contains("High Gain.nam (GAIN)") || !highGain.Contains("ESR 0.05384 > limit 0.0500"))
    throw new Exception("Missing NAM filename, label, actual ESR, or limit");
if (Review(.04, .94) is not string correlation || !correlation.Contains("correlation 0.9400 < limit 0.9500"))
    throw new Exception("Low correlation was not reviewed");
if (Review(.05384, limit: .06) is not null) throw new Exception("Ignored reported ESR limit");
if (Review(.05000001) is not string precise || !precise.Contains("0.05000001"))
    throw new Exception("Rounded away a failing score");
var affected = new[] { Review(.01, name: "Clean.nam"), highGain,
    Review(.06, name: "Crunch.nam", label: "CRNCH") }.Where(line => line is not null).ToArray();
if (affected.Length != 2 || affected.Any(line => line!.Contains("Clean.nam")))
    throw new Exception("Review did not select only the affected models");
foreach (var (esr, corr, limit) in new[] { (-.1, .99, .05), (.1, 1.1, .05), (.1, .99, 0.0) }) {
    try { Review(esr, corr, limit); }
    catch (InvalidDataException) { continue; }
    throw new Exception("Invalid scores were accepted");
}
Console.WriteLine("Conversion quality review checks passed");
