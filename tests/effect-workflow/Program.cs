using Nam2ZoomDesktop;

var root = Path.Combine(Path.GetTempPath(), "nam2zoom-effects-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try {
    var backend = new FakeEffects();
    var service = new ReadyEffectService(new AppPaths(root, Path.Combine(root,"private data")), backend);
    var models = Enumerable.Range(1, 5).Select(n => new ModelSelection { Path = Path.Combine(root,$"AMP{n}.nam"), Label = $"MODEL{n}", ModelProfile = "lite" }).ToArray();
    foreach (var model in models) File.WriteAllText(model.Path, "ready fixture");
    var bank = await service.BuildAsync(models, Path.Combine(root,"Built_effects"), _ => {}, default);
    if (backend.Commands.Any(a => a[0] == "adapt") || !File.Exists(bank.Effect) || !File.Exists(bank.Icon)) throw new Exception("Build must package ready models without retraining.");
    var build = backend.Commands.Single(a => a[0] == "build-ready-effect");
    if (build.Count(a => a == "--label") != 5 || build[Array.IndexOf(build,"--profile")+1] != "lite") throw new Exception("Selected labels/profile were not forwarded.");
    if (build.Contains("--compact-effect")) throw new Exception("Full must be the default effect mode.");
    await service.BuildAsync(models, Path.Combine(root,"Compact_effects"), _=>{}, default, compactEffect: true);
    if (!backend.Commands.Last(a=>a[0]=="build-ready-effect").Contains("--compact-effect")) throw new Exception("Compact checkbox mode was not forwarded.");
    foreach (var slot in EffectSlot.All) {
        var named = await service.BuildAsync(models, Path.Combine(root,"slot"+slot.Number), _=>{}, default,
            effectSlot: slot.Number, effectName: "My Amp " + slot.Number);
        if (ReadyEffectService.SlotFor(named) != slot || ReadyEffectService.NameFor(named) != "My Amp " + slot.Number)
            throw new Exception("Named slot identity was lost.");
        await service.UninstallAsync(true,_=>{},slot.Number);
        var removal = backend.Commands.Last();
        if (removal[Array.IndexOf(removal,"--effect-slot")+1] != slot.Number.ToString()) throw new Exception("Wrong removal slot.");
    }
    var calls = backend.Commands.Count;
    backend.Ready = false;
    try { await service.BuildAsync([models[0]], root, _=>{}, default); throw new Exception("Unretrained NAM accepted."); } catch (InvalidDataException) { }
    if (backend.Commands.Skip(calls).Any(a => a[0] == "build-ready-effect")) throw new Exception("Raw models reached the packager.");
    backend.Ready = true;
    try { await service.BuildAsync([..models,models[0]], root, _=>{}, default); throw new Exception("Oversized Lite bank accepted."); } catch (InvalidDataException) { }
    await service.InstallAsync(bank, true, _=>{});
    var install = backend.Commands.Last();
    if (install[0] != "install-bank" || !install.Contains("--ack-risk") || install.Contains("--no-backup")
        || install[Array.IndexOf(install,"--approved-zd2-sha256")+1] != bank.EffectHash
        || install[Array.IndexOf(install,"--approved-zic-sha256")+1] != bank.IconHash)
        throw new Exception("Install lost approval hashes or backup/safety checks.");
    File.AppendAllText(bank.Effect,"modified"); calls = backend.Commands.Count;
    try { await service.InstallAsync(bank,true,_=>{}); throw new Exception("Changed binary accepted."); } catch (InvalidDataException) { }
    if (backend.Commands.Count != calls) throw new Exception("Changed bytes reached deployment.");
    await service.UninstallAsync(true,_=>{});
    if (backend.Commands.Last()[0] != "uninstall-bank" || backend.Commands.Last().Contains("--no-backup")) throw new Exception("Guarded uninstall was not called.");
    if (backend.DeviceCancellationPassed) throw new Exception("A pedal write must not be cancellable.");
    Console.WriteLine("Ready-only effect build, Lite limits, labels, approved binary hashes, full backup, guarded install/uninstall and non-cancellable writes: PASS");
} finally { Directory.Delete(root,true); }

sealed class FakeEffects : IConversionBackend
{
    public List<string[]> Commands = [];
    public bool Ready = true, DeviceCancellationPassed;
    public Task<ProcessResult> RunAsync(IEnumerable<string> arguments, bool training = false, Action<string>? report = null, CancellationToken token = default)
    {
        var args = arguments.ToArray(); Commands.Add(args);
        if (training) throw new Exception("Effect packaging must not train.");
        if (args[0] == "inspect-hybrid") return Task.FromResult(new ProcessResult(0, Ready ? "{\"status\":\"direct\"}" : "{\"status\":\"adaptable\"}"));
        if (args[0] == "build-ready-effect") {
            var output = Path.Combine(args[Array.IndexOf(args,"--output")+1],"build"); Directory.CreateDirectory(output);
            var slot = EffectSlot.Get(int.Parse(args[Array.IndexOf(args,"--effect-slot")+1]));
            var name = args.Contains("--effect-name") ? args[Array.IndexOf(args,"--effect-name")+1] : slot.DefaultName;
            var bytes = new byte[128]; "ZDLF"u8.CopyTo(bytes);
            System.Buffers.Binary.BinaryPrimitives.WriteUInt32LittleEndian(bytes.AsSpan(96,4),slot.Id);
            System.Text.Encoding.ASCII.GetBytes(name).CopyTo(bytes,100);
            File.WriteAllBytes(Path.Combine(output,slot.Filename),bytes); File.WriteAllText(Path.Combine(output,slot.Stem+".ZIC"),"icon fixture");
        } else if (args[0] is "install-bank" or "uninstall-bank") DeviceCancellationPassed |= token.CanBeCanceled;
        else throw new Exception("Unexpected command: "+args[0]);
        return Task.FromResult(new ProcessResult(0,"OK"));
    }
}
