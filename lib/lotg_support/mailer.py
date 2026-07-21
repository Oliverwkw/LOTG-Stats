"""Shared SMTP delivery for the LOTG emails (weekly digest + weekly health check).

Credentials never sit in the repo in the clear: the sending account + password
are AES-256 encrypted into config/digest_credentials.enc and decrypted at send
time with the DIGEST_KEY workflow secret (via the openssl CLI, no extra Python
dependency). SMTP_USERNAME / SMTP_PASSWORD env vars override the encrypted file.

Both scripts/send_digest.py and scripts/send_audit_email.py go through here so the
credential handling and the actual send live in exactly one place.
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import subprocess
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Optional, Sequence, Tuple


def decrypt_credentials(enc_path: Path, key: str) -> Optional[dict]:
    """Decrypt the AES-256 credentials blob with `key` via openssl. Mirrors the
    encryption (`-aes-256-cbc -pbkdf2 -iter 200000 -salt -base64 -A`). Returns
    {"username","password"} or None if anything goes wrong."""
    try:
        blob = Path(enc_path).read_text().strip()
    except OSError:
        return None
    try:
        proc = subprocess.run(
            ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
             "-base64", "-A", "-pass", "env:DIGEST_KEY"],
            input=blob, capture_output=True, text=True,
            env={**os.environ, "DIGEST_KEY": key}, check=False,
        )
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    try:
        creds = json.loads(proc.stdout)
    except ValueError:
        return None
    if creds.get("username") and creds.get("password"):
        return creds
    return None


def resolve_credentials(enc_path: Path) -> Optional[Tuple[str, str]]:
    """(username, password) from the SMTP_USERNAME/PASSWORD env override or the
    encrypted file (decrypted with DIGEST_KEY), else None."""
    user = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    if user and password:
        return user, password
    key = os.environ.get("DIGEST_KEY")
    if key and Path(enc_path).exists():
        creds = decrypt_credentials(enc_path, key)
        if creds:
            return creds["username"], creds["password"]
    return None


def recipients_from_env(*env_names: str) -> Optional[list]:
    """Recipient list from the first non-empty env var among `env_names`, or None.

    Lets the address lists live in repo *secrets* instead of the committed
    config/digest.yaml — this repo is public, so the YAML publishes every
    league member's email address (audit finding F4). Set DIGEST_RECIPIENTS
    (comma/space/semicolon separated) and the YAML `recipients:` becomes an
    unused fallback that can then be blanked. Absent env => YAML as before, so
    nothing breaks until the secret exists.
    """
    for name in env_names:
        raw = os.environ.get(name)
        if not raw:
            continue
        out = [r.strip() for r in re.split(r"[,;\s]+", raw) if r.strip()]
        if out:
            return out
    return None


def send_html(cfg: dict, recipients: Sequence[str], subject: str, html: str,
              user: str, password: str) -> None:
    """Send a multipart HTML email to `recipients` over SMTP (STARTTLS)."""
    host = os.environ.get("SMTP_HOST", cfg.get("smtp_host", "smtp.gmail.com"))
    port = int(os.environ.get("SMTP_PORT", cfg.get("smtp_port", 587)))

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg.get("from_name", "LOTG Stats"), user))
    msg["To"] = ", ".join(recipients)
    msg.set_content("This email is best viewed as HTML.")
    msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls(context=ctx)
        smtp.login(user, password)
        smtp.send_message(msg)
