# Changelog

## 2.0.1

- Preserve the pinned Waveformer source checksum on Windows checkouts so the
  portable release passes its regression suite.
- Ship smaller Windows and macOS app ZIPs with a verified Python runtime
  download on first launch and license notices in both downloads.

## 2.0.0

- Ship smaller Windows and macOS app ZIPs with a verified Python runtime download on first launch.
- Cache the installed runtime so future launches work offline.
- Include license and copyright notices in both downloads.
- Open the NAM loader directly at sym.bios.is and clarify that the site does not host or share retrained NAM models.
- Improve Compact's agreement with Full using corrected internal tap delays, while preserving the same 44.1 kHz NAM files and retraining workflow.
- Show the sidebar pedal artwork and Plus-pedal compatibility list only on the Build effect page.
- Center the pedal artwork horizontally in the sidebar.

## 1.10.1

- Update Stomphacks with resident-effect collision checks and a 100 KB installation free-space margin; preserve existing NAM bank identities.

- Use bold, centered effect names with consistent proportions and side margins in both icon sizes.
- Limit new effect names to eight characters; preserve support for existing longer-named effects.

## 1.10.0

- Add three independent NAM effect slots with custom names and optional names on amp artwork.
- Install, replace and uninstall the selected slot while preserving the other two.

## 1.9.9

- Replace the sidebar pedal illustration with the supplied NAM A2 artwork.

## 1.9.8

- Build Full and Compact effects with up to five retrained A2 Lite models.

## 1.9.7

- Support six-character model labels and improve Build effect spacing and reorder buttons.

## 1.9.6

- Build Full and Compact effects with up to four retrained A2 Lite models.

## 1.9.5

- Arrange controls as Model, Gain, Volume, Mix on page 1 and Bass, Middle,
  Treble on page 2.
- Add smoothed input Gain, with 50 at unity.

## 1.9.4

- Preserve the selected model after leaving the tuner using a dedicated
  coefficient slot.
- Remove audio-side parameter polling.

## 1.9.2

- Identify Compact effects with a small label on the amp artwork.

## 1.9.1

- Reduce convolution history reads and optimize Compact FIR processing.

## 1.9.0

- Add Compact effect builds with lower-rate inference and filtered 44.1 kHz I/O.
- Keep retrained NAM exports in the full A2 Lite 44.1 kHz format.

## 1.2.2

- Repair CUDA environments after moving or removing an older portable release,
  retaining installed packages and the selected device.

## 1.2.1

- Add CPU/NVIDIA training-device selection and persistent preferences.
- Verify CUDA during GPU setup and retain CPU training as a fallback.
