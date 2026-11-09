# Third-party software and notices

nam2zoom is copyright © 2026 Aleksandar Vukasinovic and is licensed under the
MIT license. Third-party components retain their own copyrights and terms.

- CPython and its bundled libraries come from the
  [Python Build Standalone project](https://github.com/astral-sh/python-build-standalone).
  The Python directory contains its original license files. The collected
  copies and notices for Python packages are under `python/`.
- `installed-packages.txt` lists the Python packages in this build, including
  PyTorch. See the packages' own licenses and notices for their terms.
- `dependency-sources.json` records the upstream revisions for Neural Amp
  Modeler, Neural Amp Modeler Core, stomphacks and zoom-zt2. nam2zoom applies
  the listed patches, included under `patches/`.
- The remaining files record notices for the .NET runtime, NuGet dependencies,
  Node.js, Waveformer, TI code and applicable platform components.

SoundFile's bundled libsndfile and codecs are documented in the wheel's
`licensing/license_notes.md` and `_soundfile_data/COPYING`. Python-SoXR is
LGPL-licensed and its PyPI wheels include a modified libsoxr. See
[SoundFile](https://github.com/bastibe/python-soundfile) and
[Python-SoXR](https://github.com/dofuuz/python-soxr) for upstream source and
build information.

Before publishing a binary release, review the corresponding-source and
replacement requirements for the exact LGPL binaries in the runtime. Include
the matching source or a compliant source offer as required by their licenses.
The upstream project links above are provenance references. Verify any
Windows runtime DLLs against the applicable Microsoft redistribution terms.
