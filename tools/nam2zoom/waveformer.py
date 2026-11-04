"""Build ready-only Lite models with the pinned Waveformer fixed-point host."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .bank import load_models
from .hybrid import classify

ROOT = Path(__file__).resolve().parents[2]


def _run(request):
    bundled = ROOT / 'runtime/node' / ('node.exe' if os.name == 'nt' else 'node')
    node = str(bundled) if bundled.is_file() else (None if (ROOT / 'runtime/portable.marker').exists() else shutil.which('node'))
    if not node:
        raise ValueError('Bundled effect-builder runtime missing. Extract the complete portable ZIP.')
    data = Path(os.environ.get('NAM2ZOOM_DATA_DIR', str(ROOT / '.tooling'))) / 'effect-builder'
    data.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='request-', dir=data) as temporary:
        path = Path(temporary) / 'request.json'
        path.write_text(json.dumps(request), encoding='utf-8')
        env = os.environ.copy()
        env.pop('NODE_OPTIONS', None)
        env.pop('NODE_PATH', None)
        subprocess.run([node, str(Path(__file__).with_name('waveformer_build.cjs')), str(path)],
                       env=env, check=True)


def build_ready_effect(paths, labels, output):
    # Preserve the existing labels, model-count checks and strict full Lite
    # shape/rate classification. This command never falls back to retraining.
    models = load_models(paths, labels, profile='lite')
    for path, *_ in models:
        if classify(path, 'lite')['status'] != 'direct':
            raise ValueError(f'{path.name}: retrain to A2 Lite 44.1 kHz first')
    build = output.resolve() / 'build'
    if output.exists():
        raise FileExistsError(f'Build output already exists: {output}')
    _run({'models': [{'path': str(path.resolve()), 'label': label} for path, label, *_ in models],
          'output': str(build)})
    effect = build / 'N2ZBANK.ZD2'
    from offline_effect_audit import audit_bytes
    errors = audit_bytes(effect.read_bytes(), effect.with_suffix('.ZIC').read_bytes(), {})
    if errors:
        raise ValueError('Optimized bank failed offline audit: ' + '; '.join(errors))
    vendor = ROOT / 'third_party/waveformer-nam'
    for name in ('LICENSE.txt', 'TI-NOTICE.txt'):
        shutil.copy2(vendor / name, build / ('Waveformer-' + name))
    return effect


def validate_ready_effect(effect):
    _run({'validate': str(effect.resolve()), 'icon': str(effect.with_suffix('.ZIC').resolve())})


def require_host_device(effect, profile):
    """The public host was validated only for MS-50G+ and MS-70CDR+."""
    from zd2 import parse_zd2_bytes
    candidate = parse_zd2_bytes(effect.read_bytes())
    # The NAMS magic is a uint32 word written little-endian (bytes SMAN).
    if candidate.data_chunk and b'SMAN' in candidate.data_chunk.data:
        validate_ready_effect(effect)
        if profile.key not in ('ms50g-plus', 'ms70cdr-plus'):
            raise ValueError('The optimized Waveformer host supports MS-50G+ 1.40 and MS-70CDR+ 1.20 only.')
