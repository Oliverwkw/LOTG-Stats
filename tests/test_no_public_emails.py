"""This repo is public: no real person's email address may be committed.

The league's addresses live in the DIGEST_RECIPIENTS / DIGEST_TEST_RECIPIENTS /
DIGEST_AUDIT_RECIPIENTS repo secrets (user, 2026-09-30). This guard fails if a
personal-provider address (gmail, aol, outlook, ...) appears in any tracked text
file, or if config/digest.yaml carries a non-empty recipient list. Test fixtures
use @x.com / @example.com, which it ignores.

Runs under pytest and directly as `python tests/test_no_public_emails.py`.
"""
import re
import subprocess
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_PERSONAL = re.compile(
    r"[A-Za-z0-9._%+-]+@(gmail|googlemail|aol|outlook|hotmail|live|msn|yahoo|"
    r"icloud|me|protonmail|proton)\.(com|me)\b", re.I)


def _tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=_ROOT, capture_output=True,
                             text=True, check=True).stdout
    except Exception:
        return None
    return [_ROOT / p for p in out.splitlines() if p]


def test_no_personal_email_addresses_are_committed():
    files = _tracked_files()
    if files is None:
        print("  [SKIP] not a git checkout")
        return
    hits = []
    for f in files:
        if not f.is_file() or f.stat().st_size > 5_000_000:
            continue
        try:
            text = f.read_text(errors="strict")
        except (UnicodeDecodeError, OSError):
            continue  # binary
        for n, line in enumerate(text.splitlines(), 1):
            if _PERSONAL.search(line):
                # Name the file and line, never the address itself.
                hits.append(f"{f.relative_to(_ROOT)}:{n}")
    assert not hits, "personal email address committed to a public repo at: " + ", ".join(hits)


def test_digest_yaml_recipient_lists_are_empty():
    cfg = yaml.safe_load((_ROOT / "config" / "digest.yaml").read_text()) or {}
    for key in ("recipients", "test_recipients", "audit_recipients"):
        assert not (cfg.get(key) or []), (
            f"config/digest.yaml `{key}` must stay empty — the addresses belong in "
            f"repo secrets, not this public file")


if __name__ == "__main__":
    test_no_personal_email_addresses_are_committed()
    test_digest_yaml_recipient_lists_are_empty()
    print("ok")
