"""Phase 14: digest email credential-decryption tests.

Verifies scripts/send_digest.py can decrypt the AES-256 credentials blob format
that scripts/encrypt_digest_credentials.py (and the committed
config/digest_credentials.enc) use. Uses a throwaway key + temp file — never
touches the committed blob (whose real DIGEST_KEY isn't in the repo). SKIPs if
the openssl CLI isn't available.

Run: PYTHONPATH=. python tests/test_digest_send.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import scripts.send_digest as S  # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def _encrypt(payload: str, key: str) -> str:
    proc = subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
         "-salt", "-base64", "-A", "-pass", "env:DIGEST_KEY"],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "DIGEST_KEY": key}, check=True,
    )
    return proc.stdout.strip()


def check_decrypt_roundtrip():
    if not shutil.which("openssl"):
        print("  [SKIP] openssl not available")
        return True
    key = "a" * 64
    creds = {"username": "lotgstats@gmail.com", "password": "app pass word"}
    with tempfile.TemporaryDirectory() as d:
        enc = Path(d) / "creds.enc"
        enc.write_text(_encrypt(json.dumps(creds), key) + "\n")
        got = S._decrypt_credentials(enc, key)
        ok = _ok("decrypts to original creds", got == creds, f"got {got}")
        ok &= _ok("wrong key -> None", S._decrypt_credentials(enc, "b" * 64) is None)
        ok &= _ok("missing file -> None", S._decrypt_credentials(Path(d) / "nope.enc", key) is None)
    return ok


def check_resolve_prefers_env_override():
    os.environ["SMTP_USERNAME"] = "override@x.com"
    os.environ["SMTP_PASSWORD"] = "pw"
    try:
        got = S._resolve_credentials()
    finally:
        del os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"]
    return _ok("env override wins", got == ("override@x.com", "pw"), f"got {got}")


def check_resolve_none_without_creds():
    # Ensure no ambient creds leak in.
    for k in ("SMTP_USERNAME", "SMTP_PASSWORD", "DIGEST_KEY"):
        os.environ.pop(k, None)
    return _ok("no creds -> None", S._resolve_credentials() is None)


def run_all() -> bool:
    all_ok = True
    for t in (check_decrypt_roundtrip, check_resolve_prefers_env_override,
              check_resolve_none_without_creds):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_digest_send():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
