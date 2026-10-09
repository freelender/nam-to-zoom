# Precompiled pedal DSP

These zero-weight templates were imported from the existing maintainer build
`.tooling/portable-release-20261008-190001/{templates,templates-lite}`. Compact retains its original ten-capacity images. Lite was rebuilt on
2026-10-09 for the experimental shared-load kernel and contains only capacities
one through three; see [the review](../../docs/LITE_OPTIMIZATION.md).
Compact's local pedal-tested ELF baseline regression passed on Windows.
Lite reserves 270 raw and retains its existing experimental hardware status.

Each index records the template/icon SHA-256, data offsets and production DSP
source hashes. `template.fill_template` validates these plus CRC, INFO load,
controls, constant bounds and unchanged non-constant ELF sections at every build.
The precompiled files contain zero model weights; no user NAM is distributed.

`.gitattributes` fixes the original per-file line endings on every target. This
is necessary because these indices hash exact bytes, including line endings.
Do not normalize the hashed C/header files without regenerating reviewed indices.

`golden.json` records deterministic output hashes for one and ten Compact models
and one and three Lite models with every weight equal to 0.03125 and labels AMP1…AMP10. Native
CI compares generated ZD2/ZIC bytes with these Windows-generated hashes.

Only regenerate using `release/create_templates.py` on a maintainer Windows
machine with the licensed TI compiler. Review source hashes and run the template
and local pedal-baseline tests before replacing these files. A DSP source change
intentionally breaks release validation until matching reviewed templates exist.
TI compiler executables are never distributed or required in portable CI.
