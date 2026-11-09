# User guide

## Install and launch

Extract the complete portable package into a writable folder. On Windows, run
`nam2zoom.exe`; on macOS, open `nam2zoom.app`. Keep the bundled files together.
The release ZIP downloads Python and its dependencies on first launch. An
internet connection is required for setup. Later launches reuse the installed
runtime and can convert and build effects offline.

Windows can use CPU or NVIDIA CUDA training. GPU setup requires internet access
and a compatible NVIDIA driver. macOS uses CPU training. macOS packages are
unsigned; use the system's **Open Anyway** option for a release you trust.

## Retrain NAM files

1. Add NAM files, add a folder, or drop files into the **Retrain** queue.
2. Select the rows to process. Each file is retrained separately.
3. Choose the training device and epoch count, from 1 to 300.
4. Select **Retrain & export NAMs**.
5. Review the A/B preview if a result falls below the quality limits.
6. Use **Open Converted_NAM** to find the exported models.

The output is A2 Lite at 44.1 kHz: 23 layers, three channels and 1,871 float32
weights. Compatible files are exported without retraining. Other supported
captures, including 48 kHz models, are rendered and retrained into this format.
Retraining approximates the original sound; results vary by capture.

More epochs take longer and may improve the result. Matching cached conversions
are reused. Lower ESR indicates a closer match; listen to the A/B preview when
deciding whether to export a result that fails the quality checks.

**Cancel** stops the current file and continues the queue. **Cancel all** stops
the batch. Completed exports and cached conversions are retained. The row menu
can retry or skip files, open previews, and locate source or exported files.

## Files and settings

Exports are saved in `Converted_NAM` beside the Windows executable or beside
the macOS app bundle. Filenames keep the original name with a `-441-resampled`
suffix, for example `MyAmp-441-resampled.nam`. Identical exports are
reused; changed conversions receive numbered filenames. Original captures and
existing exports are preserved.

Keep the app in a writable location. Caches, previews, logs and preferences are
stored under `%LOCALAPPDATA%/nam2zoom` on Windows or
`~/Library/Application Support/nam2zoom` on macOS.

**Settings** includes saved queues, training-device selection and application
folders. Saved `.n2zqueue.json` files reference the original NAM paths, so those
files must still be available when reopening a queue. **Clear log** clears the
visible log, not the session log on disk.

## Share and load models

Exported NAMs can be shared as Zoom-ready models. Other users do not need to
repeat the retraining. Share only models you have permission to redistribute.
The generated `Converted_NAM/README.txt` includes sharing information and the
loader link.

[The NAM loader at sym.bios.is](https://sym.bios.is/?open=nam) loads NAM files onto compatible
Zoom pedals. The **Load NAMs at sym.bios.is** button opens it. Follow the loader's
compatibility guidance for your pedal and firmware.
sym.bios.is does not host or share retrained NAM models.

## Build, install and uninstall an effect

Open **Build effect** and select one to five retrained A2 Lite 44.1 kHz NAMs. Choose one of three effect slots:

| Slot | Effect ID | Pedal filename |
| --- | --- | --- |
| 1 | `0x04001787` | `N2ZBANK.ZD2` |
| 2 | `0x04001387` | `N2ZBNK2.ZD2` |
| 3 | `0x04001397` | `N2ZBNK3.ZD2` |

Each slot can hold a different bank of up to five models. Give each effect a
unique name of 1–8 ASCII letters, digits, spaces, hyphens or underscores.
**Show effect name on amp artwork** prints that name inside the amp icon;
Names use fixed bold lettering with side margins in both library and patch views.
Compact retains its separate badge. The original amp outline stays intact.
Previously built effects with longer names can still be loaded, installed and removed;
new builds require names of eight characters or fewer.

Install/replace and uninstall affect only the selected slot. Loading a built
file selects its slot automatically. Check the pedal again after changing
slots. Remove the target slot from saved patches and select a stock-only current
patch before a write; the other slots may remain in saved patches. The three
slots can coexist in the library, but active effects still share the pedal's
DSP budget. Slot 1 keeps the existing ID for compatibility; slots 2 and 3 use the documented
DIY playground. These are local assignments, not a registered author range.
Installation still checks for collisions with the pedal's catalog.

Assign unique pedal labels of one to five characters, then set their order.
Raw captures must be retrained first. Building an effect does not retrain them.

| Parameter page | Controls |
| --- | --- |
| 1 | Model, Gain, Volume, Mix |
| 2 | Bass, Middle, Treble |

Gain controls drive into the NAM: 50 is unity input, 0 is zero input and 100
doubles the input level. Volume 50 is unity output. EQ 50 is flat; Mix 100 is
fully wet.

Leave **Compact** unchecked for Full processing at 44.1 kHz. Compact uses the
same model and weights at 33.075 kHz internally, with filtered 44.1 kHz I/O.
Compact adjusts internal model delays to approximate the original 44.1 kHz
timing more closely. It does not require separate models or retraining.
It lowers DSP demand but can change tone and dynamics. It adds 64 samples
(about 1.45 ms) of latency; partial wet mixes align the dry signal to that delay.
Fully dry output remains immediate. Compact has a small label on the amp artwork.

Full declares 260 of the pedal's 270 admission budget; Compact declares 190.
These declarations control patch admission and are not measured CPU percentages.
The Compact checkbox changes only the effect build. Exported NAMs remain full
A2 Lite at 44.1 kHz and can still be shared or used with other loaders.

Builds are saved under `Built_effects` beside the app. Keep each slot’s ZD2 and
matching ZIC file together. **Load built effect...** opens an existing pair.
Rebuild and reinstall after changing models, labels, order, mode or control layout.

Direct installation supports MS-50G+ firmware 1.40, MS-70CDR+ firmware 1.20,
and MS-60B+ firmware 1.20. Other device/firmware combinations are
refused. **Check pedal / installed bank** performs read-only identification.

Before installing or removing a bank, remove the selected NAM slot from saved patches and
select a stock-only current patch. Full backup is enabled by default. The app
shows the binary/icon hashes for approval and verifies the transfer by readback.
**Uninstall selected slot** removes that bank without retraining any models.

Keep the pedal powered and connected during transfers. Installation and removal
cannot be cancelled halfway through. If a transfer fails, preserve the session
logs and follow the recovery instructions before retrying. Check a new bank in
an unsaved patch before saving it or combining it with other effects.

## Troubleshooting

- Unsupported captures are rejected with a reason in the log.
- For poor conversion quality, try more epochs or another capture and compare
  the A/B previews before exporting.
- If export fails, move the complete app folder to a writable location.
- If GPU setup fails, CPU training remains available. Check the NVIDIA driver
  and setup log before retrying.
- If the app fails after moving it, check that the complete portable package
  was extracted and that files from different releases were not mixed.
