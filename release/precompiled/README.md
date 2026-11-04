# Precompiled DSP templates

Templates contain zero model weights. Portable builds fill only validated weights
and selector labels; they do not compile or modify DSP instructions.

| Directory | Runtime | Model capacities |
| --- | --- | --- |
| `own-lite` | Current Full host | 1-5 |
| `own-lite-compact` | Current Compact host | 1-5 |
| `lite` | Legacy Lite host | 1-5 |
| `compact` | Legacy 14-layer host | 1-10 |

Indexes record source, binary and icon hashes, patch offsets, control layout and
DSP reservation. Current indexes also bind the mode and coefficient mapping.
Filling verifies these values, CRC, finite weights, constant-data bounds and
unchanged non-constant ELF sections.

Generate current templates on Windows with the TI C6000 8.3.1 toolchain:

```text
python release/create_templates.py --profile lite --own-host --output <new-directory> --work <new-work-directory>
```

Add `--compact-effect` for Compact. Use separate new directories, validate the
outputs and replace each template set together with its index and icon. Do not
redistribute TI tools.

Source hashes include line endings. Preserve `.gitattributes`; source changes
require matching templates. `golden.json` holds fixed legacy-output hashes for CI.
