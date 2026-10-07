using Nam2ZoomDesktop;

var temporary = Path.Combine(Path.GetTempPath(), "nam2zoom-export-" + Guid.NewGuid());
Directory.CreateDirectory(temporary);
try {
    var student = Path.Combine(temporary, "model.nam");
    File.WriteAllText(student, "converted weights");
    var original = Path.Combine(temporary, "Marshal_1982_Blabla.nam");
    File.WriteAllText(original, "original weights");
    var exported = ConvertedNam.Save(student, original, temporary);
    var expected = Path.Combine(temporary, "Converted_NAM", Path.GetFileName(original));
    if (exported != expected || File.ReadAllText(exported) != "converted weights")
        throw new Exception("Export must preserve the original filename and converted contents");
    if (ConvertedNam.Save(student, original, temporary) != exported)
        throw new Exception("Cached identical conversion must reuse the export");
    File.WriteAllText(student, "different conversion");
    var changed = ConvertedNam.Save(student, original, temporary);
    if (changed != Path.Combine(temporary, "Converted_NAM", "Marshal_1982_Blabla (2).nam")
        || File.ReadAllText(exported) != "converted weights")
        throw new Exception("Changed conversion must preserve earlier exports");
    File.WriteAllText(student, "conversion with cab");
    var withCab = ConvertedNam.Save(student, exported, temporary);
    if (withCab == exported || File.ReadAllText(exported) != "converted weights"
        || File.ReadAllText(original) != "original weights")
        throw new Exception("Importing an exported NAM must never overwrite the source");
    var compact = ConvertedNam.Save(student, original, temporary, "compact");
    var lite = ConvertedNam.Save(student, original, temporary, "lite");
    if (compact == lite || Path.GetDirectoryName(compact) != Path.Combine(temporary, "Converted_NAM", "Compact")
        || Path.GetDirectoryName(lite) != Path.Combine(temporary, "Converted_NAM", "Lite"))
        throw new Exception("Architectures must have separate export directories");
    if (ConvertedNam.Save(student, original, temporary, "lite") != lite)
        throw new Exception("Identical Lite export must be reused");
    try {
        ConvertedNam.Save(student, original, temporary, "../invalid");
        throw new Exception("Invalid profile accepted");
    } catch (ArgumentException) { }
    Console.WriteLine("Converted NAM export checks passed");
} finally {
    Directory.Delete(temporary, recursive: true);
}
