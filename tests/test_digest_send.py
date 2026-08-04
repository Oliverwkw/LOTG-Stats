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


def check_test_flag_no_html_needed():
    # --test must NOT require the digest HTML and must not crash; with no creds
    # it bails cleanly (exit 0). Point --html at a nonexistent path to prove
    # --test ignores it.
    for k in ("SMTP_USERNAME", "SMTP_PASSWORD", "DIGEST_KEY"):
        os.environ.pop(k, None)
    rc = S.main(["--test", "--html", "/definitely/not/here.html"])
    return _ok("--test returns 0 (bails on missing creds, ignores HTML)", rc == 0, f"rc={rc}")


def check_recipient_split():
    cfg = {"recipients": ["a@x.com", "b@x.com", "c@x.com"], "test_recipients": ["a@x.com"]}
    ok = _ok("real digest -> all recipients", S._recipients_for(cfg, test=False) == cfg["recipients"])
    ok &= _ok("test email -> test recipients only", S._recipients_for(cfg, test=True) == ["a@x.com"])
    # No test_recipients configured -> test falls back to the full list.
    ok &= _ok("test falls back to recipients", S._recipients_for({"recipients": ["a@x.com"]}, test=True) == ["a@x.com"])
    return ok


def check_recipients_env_override():
    """Audit finding F4: repo secrets can supply the address lists so they need
    not sit in the public repo's config/digest.yaml."""
    cfg = {"recipients": ["yaml@x.com"], "test_recipients": ["yamltest@x.com"]}
    saved = {k: os.environ.get(k) for k in
             ("DIGEST_RECIPIENTS", "DIGEST_TEST_RECIPIENTS")}
    try:
        os.environ["DIGEST_RECIPIENTS"] = "a@x.com, b@x.com"
        ok = _ok("DIGEST_RECIPIENTS overrides the YAML league list",
                 S._recipients_for(cfg, test=False) == ["a@x.com", "b@x.com"])
        ok &= _ok("test email does NOT inherit the league override when its own is unset",
                  S._recipients_for(cfg, test=True) == ["a@x.com", "b@x.com"])
        os.environ["DIGEST_TEST_RECIPIENTS"] = "t@x.com"
        ok &= _ok("DIGEST_TEST_RECIPIENTS wins for the test email",
                  S._recipients_for(cfg, test=True) == ["t@x.com"])
        ok &= _ok("league list unaffected by the test override",
                  S._recipients_for(cfg, test=False) == ["a@x.com", "b@x.com"])
        del os.environ["DIGEST_RECIPIENTS"], os.environ["DIGEST_TEST_RECIPIENTS"]
        ok &= _ok("falls back to the YAML when no env is set",
                  S._recipients_for(cfg, test=False) == ["yaml@x.com"])
        os.environ["DIGEST_RECIPIENTS"] = "   "
        ok &= _ok("a blank env var does not blackhole the send",
                  S._recipients_for(cfg, test=False) == ["yaml@x.com"])
        return ok
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def check_subject_matches_the_digest_title():
    """The subject comes from the same `digest_title` the HTML header uses, so
    the two can't drift — including the offseason form (a date, not week 0)."""
    with tempfile.TemporaryDirectory() as d:
        snap = Path(d) / "ranks_snapshot.json"

        snap.write_text(json.dumps({"meta": {
            "season": 2026, "weeks_completed": 7,
            "captured_at": "2026-11-03T14:05:00+00:00"}}))
        got = S._subject(snap)
        ok = _ok("in-season subject names the week",
                 got == "LOTG weekly digest — 2026 season, week 7", f"got {got}")
        ok &= _ok("in-season subject says no 'through'", "through" not in got, f"got {got}")

        snap.write_text(json.dumps({"meta": {
            "season": 2026, "weeks_completed": 0,
            "captured_at": "2026-08-04T16:16:14.518605+00:00"}}))
        got = S._subject(snap)
        ok &= _ok("offseason subject names the date",
                  got == "LOTG weekly digest — 2026 season, August 4, 2026", f"got {got}")
        ok &= _ok("offseason subject never says week 0", "week 0" not in got.lower(), f"got {got}")

        ok &= _ok("unreadable snapshot -> plain subject",
                  S._subject(Path(d) / "nope.json") == "LOTG weekly digest")
    return ok


def run_all() -> bool:
    all_ok = True
    for t in (check_decrypt_roundtrip, check_resolve_prefers_env_override,
              check_resolve_none_without_creds, check_test_flag_no_html_needed,
              check_recipient_split, check_recipients_env_override,
              check_subject_matches_the_digest_title):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_digest_send():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
