"""Read-only application resources and writable user data are separate."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def executable(name: str) -> str:
    return name + (".exe" if sys.platform == "win32" else "")


def data_root() -> Path:
    override = os.environ.get("NAM2ZOOM_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/nam2zoom"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "nam2zoom"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "nam2zoom"


def renderer() -> Path:
    return ROOT / "reference/nam_a2/build-core-ninja" / executable("core_render")


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python3")
