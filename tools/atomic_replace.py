"""Atomic temp-file-then-rename helper, hardened against a transient macOS
issue observed on this environment: `Path.replace()` (rename(2)) on a
freshly-written file can fail with `PermissionError: Operation not permitted`
for a brief window after the file is created, apparently while some
background process (on-write security scanning, most likely) still holds it.
The failure is transient, not tied to a specific destination directory or
Python build - retrying after a short delay, or shelling out to Apple's own
signed /bin/mv, both reliably succeed. Never silently swallows a persistent
failure: if every attempt fails, the final error propagates.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

_RETRY_DELAYS = (0.05, 0.2, 0.5)


def atomic_replace(temporary: Path, destination: Path) -> None:
    """Rename `temporary` onto `destination`, retrying past the transient
    permission window before falling back to `/bin/mv`."""
    last_error: PermissionError | None = None
    for delay in _RETRY_DELAYS:
        try:
            temporary.replace(destination)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(delay)
    try:
        subprocess.run(["/bin/mv", str(temporary), str(destination)], check=True)
    except (OSError, subprocess.CalledProcessError):
        assert last_error is not None
        raise last_error
