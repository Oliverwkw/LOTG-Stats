"""CI runs exactly the package versions requirements.lock names.

The lock is a pip constraints file every workflow installs with, so a CI run that
resolved anything else means a workflow skipped it or the lock went stale. That is
how pandas 3 reached CI unnoticed while local stayed on 2.3 (memory ci-runs-pandas3).
Locally the comparison only runs when LOTG_CHECK_LOCK=1 (a python 3.11 venv built
from the lock); a stock checkout on another interpreter has no reason to match.
"""
from __future__ import annotations

import os
import re
import sys
from importlib import metadata
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
LOCK = _ROOT / "requirements.lock"


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def lock_pins(path: Path = LOCK) -> dict:
    pins = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"([A-Za-z0-9_.\-]+)==([^\s;]+)", line)
        assert m, f"requirements.lock: not an exact `name==version` pin: {line!r}"
        assert _norm(m.group(1)) not in pins, f"requirements.lock pins {m.group(1)} twice"
        pins[_norm(m.group(1))] = m.group(2)
    return pins


def test_the_lock_is_exact_pins_only():
    pins = lock_pins()
    assert "pandas" in pins and "numpy" in pins, "the lock lost the packages it exists for"


def test_requirements_txt_agrees_with_the_lock():
    """An exact pin in requirements.txt must be the locked version."""
    pins = lock_pins()
    for line in (_ROOT / "requirements.txt").read_text().splitlines():
        m = re.fullmatch(r"([A-Za-z0-9_.\-]+)==(\S+)", line.split("#", 1)[0].strip())
        if m:
            assert pins.get(_norm(m.group(1))) == m.group(2), (
                f"requirements.txt pins {m.group(0)}, requirements.lock says "
                f"{pins.get(_norm(m.group(1)))}")


def test_installed_versions_match_the_lock():
    if os.environ.get("GITHUB_ACTIONS") != "true" and os.environ.get("LOTG_CHECK_LOCK") != "1":
        return
    assert sys.version_info[:2] == (3, 11), f"CI is python 3.11, this is {sys.version.split()[0]}"
    off = []
    for name, want in lock_pins().items():
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue        # a constraint only binds what a workflow installs
        if have != want:
            off.append(f"{name} {have} (lock {want})")
    assert not off, ("installed packages differ from requirements.lock: " + ", ".join(off)
                     + ". Install with `-c requirements.lock`, or bump the lock deliberately.")


def test_every_installed_package_is_locked():
    """A new transitive dependency must be added to the lock, not float."""
    if os.environ.get("GITHUB_ACTIONS") != "true" and os.environ.get("LOTG_CHECK_LOCK") != "1":
        return
    pins = lock_pins()
    loose = sorted({_norm(d.metadata["Name"]) for d in metadata.distributions()} - set(pins) - {"lotg"})
    assert not loose, ("installed but not in requirements.lock: " + ", ".join(loose)
                       + ". Add each at the version exports/raw/pip_freeze.txt shows.")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
