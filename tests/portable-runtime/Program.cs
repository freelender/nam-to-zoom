// Not used by the macOS port: this smoke test exercises PortableRuntime.cs
// (Windows-only self-contained portable ZIP bootstrap - VC++ redist check,
// bundled Python setup), which lives in the Windows WinForms app
// (apps/nam2zoom-desktop) that this fork does not include. Kept commented
// out, rather than deleted, for reference against the upstream project.
/*
using Nam2ZoomDesktop;

if (args.Length != 2 || args[1] is not ("--check" or "--setup-cpu")) {
    Console.Error.WriteLine("Usage: RuntimeSmoke <extracted portable folder> --check|--setup-cpu");
    return 2;
}
var root = Path.GetFullPath(args[0]);
if (!PortableRuntime.IsPortable(root)) throw new InvalidOperationException("Not a portable release folder");
PortableRuntime.Prepare(root);
Console.WriteLine($"VisualCppReady: {PortableRuntime.VisualCppReady()}");
if (!PortableRuntime.VisualCppReady()) throw new InvalidOperationException("Microsoft C++ runtime prerequisite missing; test the GUI's signed-installer flow before continuing");
if (args[1] == "--setup-cpu")
    await PortableRuntime.EnsureTrainingAsync(root, false, Console.WriteLine, CancellationToken.None);
Console.WriteLine($"TrainingReady: {PortableRuntime.TrainingReady(root)}");
return PortableRuntime.TrainingReady(root) ? 0 : 1;
*/
