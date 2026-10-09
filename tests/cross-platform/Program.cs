using Nam2ZoomDesktop;

if (args.FirstOrDefault() == "--child") {
    Console.OutputEncoding = System.Text.Encoding.UTF8;
    Console.WriteLine(args[1]);
    for (var n = 0; n < 3000; n++) { Console.WriteLine("stdout " + n); Console.Error.WriteLine("stderr " + n); }
    return 7;
}
if (args.FirstOrDefault() == "--wait") { await Task.Delay(30000); return 0; }
var temporary = Path.Combine(Path.GetTempPath(), "nam2zoom shared smoke " + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(temporary);
try {
    var paths = new AppPaths(Path.Combine(temporary, "read-only resources"), Path.Combine(temporary, "user data"));
    var di = paths.TrainingDi();
    if (!File.Exists(di) || !di.StartsWith(paths.Data)) throw new Exception("Training resource escaped writable data");
    var backend = new BackendService(paths);
    var result = await backend.ExecuteAsync(Environment.ProcessPath!, ["--child", "spaced/Кабинет/model name.nam"]);
    if (result.Exit != 7 || !result.Output.Contains("spaced/Кабинет/model name.nam")
        || !result.Output.Contains("stderr 2999") || !result.Output.Contains("stdout 2999"))
        throw new Exception($"Argument encoding or concurrent pipe draining failed (exit {result.Exit}): {result.Output[..Math.Min(500, result.Output.Length)]}");
    using var cancellation = new CancellationTokenSource(300);
    try { await backend.ExecuteAsync(Environment.ProcessPath!, ["--wait"], token: cancellation.Token); throw new Exception("Cancellation did not interrupt child"); }
    catch (OperationCanceledException) { }
    var models = new[] { new ModelSelection { Label = "AMP" }, new ModelSelection { Label = "amp" } };
    try { BankService.Validate(models); throw new Exception("Case-insensitive duplicate labels accepted"); }
    catch (InvalidDataException) { }
    var liteModels = Enumerable.Range(1, 3).Select(n => new ModelSelection { Label = $"L{n}", ModelProfile = "lite" }).ToArray();
    BankService.Validate(liteModels);
    var fourModels = liteModels.Append(new ModelSelection { Label = "L4", ModelProfile = "lite" }).ToArray();
    try { BankService.Validate(fourModels); throw new Exception("Four-model saved Lite list accepted"); }
    catch (InvalidDataException) { }
    try { BankService.Validate(fourModels, "lite"); throw new Exception("Four-model Lite build accepted"); }
    catch (InvalidDataException) { }
    BankService.Validate(Enumerable.Range(1, 10).Select(n => new ModelSelection { Label = $"C{n}" }).ToArray(), "compact");
    var model = Path.Combine(temporary, "model.nam");
    File.WriteAllText(model, "fixture");
    var compact = ConvertedNam.Save(model, model, paths.Data, "compact");
    var lite = ConvertedNam.Save(model, model, paths.Data, "lite");
    if (compact == lite || !compact.Contains("Compact") || !lite.Contains("Lite")) throw new Exception("Export profiles collided");
    if (ConvertedNam.Save(model, model, paths.Data, "compact") != compact) throw new Exception("Identical conversion duplicated");
    Console.WriteLine("Shared paths, DI hash, Unicode arguments, both output streams, cancellation and conversion export: PASS");
    return 0;
} finally { Directory.Delete(temporary, true); }
