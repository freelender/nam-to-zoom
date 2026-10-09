# Portable nam2zoom (cross-platform preview)

Extract the complete ZIP. On Windows 10/11 x64, run `nam2zoom.exe`.
On macOS 14 or later, open `nam2zoom.app`. Use the package matching your Mac:
ARM64 for Apple Silicon or x64 for Intel. Do not move the executable out of its
folder/bundle. Python, .NET, native rendering and training packages are included.
No installer, compiler, Apple developer account or internet connection is needed
for conversion. An NVIDIA driver is needed only for a CUDA-enabled Windows build.
Default Windows builds use CPU; maintainers can request a bundled CUDA build.
macOS training uses CPU. MPS is not enabled or validated.

These macOS apps have no Developer ID signature or notarization. If macOS blocks
opening a downloaded app, try opening it once, then go to **System Settings →
Privacy & Security → Open Anyway**, confirm **Open**, and authenticate if asked.
Only approve an app obtained from a trusted project release. Do not disable
Gatekeeper globally. See Apple's supported procedure:
https://support.apple.com/en-us/102445

Select or drop one to ten `.nam` files. Reorder them and use unique labels of
one to five ASCII letters, digits, hyphens or underscores. Choose Compact or
Lite (alone) for the whole bank. Optionally choose a mono cabinet IR WAV for
each selected model. Set epochs (1–300), choose Build effect and an output folder.
Compatible converted NAMs build without retraining. Other compatible teachers
are rendered and retrained using the existing quality-gated NAM pipeline.
When conversion quality is below the limits, audition the original/converted
clips in the A/B preview folder before accepting. Declining retains previews
and cached conversions without building or installing an effect.

Open/Save list uses the existing `.n2zbank.json` list format. Existing exported
NAMs remain compatible. User data is in `%LOCALAPPDATA%\nam2zoom` on Windows or
`~/Library/Application Support/nam2zoom` on macOS: `Converted_NAM/Compact`,
`Converted_NAM/Lite`, `adapt-cache`, `Backup`, `sessions`, `logs`, and `training`.
The Open user files button opens this directory. Build output goes in your
chosen folder. Copy old exports/backups from beside the legacy Windows EXE if
desired; they are not deleted or automatically moved.

Detect pedal reads ports and identity. Build & install requires explicit approval
of the exact ZD2/ZIC hashes. Keep full backup enabled. Unchecking it retains only
the previous effect list and bank recovery files. Installation/removal checks
identity/firmware, autosave OFF, stock-only current/saved patches, dry runs and
independent readback. Never disconnect, power off, cancel or close the app during
a pedal transfer. After a failure, preserve logs and session files and follow
the bundled `.tooling/stomphacks/SAFETY.md`, especially DO-NOT-POWER-CYCLE guidance.
No automatic restore button existed in the original app; recovery scripts and
backup formats are preserved. Use the bundled Python to run recovery commands
only after reading the recorded failure and SAFETY.md.

Supported identities remain MS-50G+ 1.40, MS-70CDR+ 1.20 and experimental MS-60B+
1.20. **macOS USB-MIDI hardware verification is pending for every device**.
A compiled app or CI test does not certify hardware transfers. Custom effects
can cause slowdown, crackling, freezing or permanent failure. Lite reserves the
full DSP budget and must run alone. Audition new builds in an unsaved patch;
saved-patch recall, reboot and real-time audio need separate hardware testing.

The original WinForms project and legacy Windows release script remain available
while this frontend undergoes parity/manual testing. The full legacy feature and
safety guide is `docs/USER_GUIDE.md` in the source repository.

Lite banks support at most **3 NAM models**; Compact banks support at most **10**. Only the selected model runs. This model-count limit does not resolve the reported Lite saved-patch/startup failure; keep Lite patches unsaved.
