"""Package a checksum-pinned Node runtime for the offline Waveformer builder."""
import hashlib
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

VERSION = '24.18.0'
ARCHIVES = {
    'win-x64': ('win-x64.zip', '0ae68406b42d7725661da979b1403ec9926da205c6770827f33aac9d8f26e821'),
    'osx-arm64': ('darwin-arm64.tar.gz', 'e1a97e14c99c803e96c7339403282ea05a499c32f8d83defe9ef5ec66f979ed1'),
    'osx-x64': ('darwin-x64.tar.gz', 'dfd0dbd3e721503434df7b7205e719f61b3a3a31b2bcf9729b8b91fea240f080'),
}


def package_node(resources: Path, rid: str, cache: Path):
    suffix, digest = ARCHIVES[rid]
    name = f'node-v{VERSION}-{suffix}'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    if not archive.is_file():
        temporary = archive.with_suffix(archive.suffix + '.download')
        with urllib.request.urlopen(f'https://nodejs.org/dist/v{VERSION}/{name}', timeout=120) as source, temporary.open('wb') as target:
            shutil.copyfileobj(source, target)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
            raise ValueError('Node runtime download checksum mismatch')
        temporary.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise ValueError('Cached Node runtime checksum mismatch')
    target = resources / 'runtime/node'
    target.mkdir(parents=True, exist_ok=True)
    prefix = name.removesuffix('.zip').removesuffix('.tar.gz')
    members = [('node.exe', 'node.exe'), ('LICENSE', 'LICENSE.txt')] if rid == 'win-x64' else [('bin/node', 'node'), ('LICENSE', 'LICENSE.txt')]
    if rid == 'win-x64':
        with zipfile.ZipFile(archive) as bundle:
            for member, filename in members:
                (target / filename).write_bytes(bundle.read(prefix + '/' + member))
    else:
        with tarfile.open(archive) as bundle:
            for member, filename in members:
                with bundle.extractfile(prefix + '/' + member) as source:
                    (target / filename).write_bytes(source.read())
        (target / 'node').chmod(0o755)
    print(f'Bundled offline effect-builder runtime: Node {VERSION}', flush=True)
