"""Encrypt the digest sending credentials into config/digest_credentials.enc.

The blob is committed to the repo; the DIGEST_KEY that decrypts it is a GitHub
Actions secret (never committed). Run this whenever the sending account or
password changes — most importantly to swap the placeholder password for a
Gmail **App Password** (Gmail rejects plain-password SMTP; you need 2FA + a
16-char app password from https://myaccount.google.com/apppasswords).

Usage (key from env, recommended — matches how CI decrypts):
    DIGEST_KEY=<hex key> python scripts/encrypt_digest_credentials.py \
        --username lotgstats@gmail.com --password 'abcd efgh ijkl mnop'

Generate a fresh key first if you don't have one:
    python -c "import secrets; print(secrets.token_hex(32))"

The encryption matches scripts/send_digest.py's decryption exactly:
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -base64 -A
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "config" / "digest_credentials.enc"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Encrypt digest SMTP credentials.")
    ap.add_argument("--username", required=True, help="sending account / From address")
    ap.add_argument("--password", required=True, help="app password for that account")
    ap.add_argument("--out", default=str(_OUT))
    args = ap.parse_args(argv)

    key = os.environ.get("DIGEST_KEY")
    if not key:
        print("error: set DIGEST_KEY in the environment (the same secret CI uses).",
              file=sys.stderr)
        return 2

    payload = json.dumps({"username": args.username, "password": args.password})
    proc = subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
         "-salt", "-base64", "-A", "-pass", "env:DIGEST_KEY"],
        input=payload, capture_output=True, text=True,
        env={**os.environ, "DIGEST_KEY": key}, check=False,
    )
    if proc.returncode != 0:
        print(f"openssl failed: {proc.stderr}", file=sys.stderr)
        return 1

    Path(args.out).write_text(proc.stdout.strip() + "\n")
    print(f"[encrypt] wrote {args.out} ({len(proc.stdout.strip())} b64 chars).")
    print("[encrypt] commit this file; keep DIGEST_KEY only as a repo secret.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
