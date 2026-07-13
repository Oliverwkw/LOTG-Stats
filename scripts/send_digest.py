"""Phase 14 — send the rendered weekly digest by email.

Reads the digest HTML (`scripts/build_digest.py` output) and `config/digest.yaml`
and mails it to the configured recipients over SMTP. Credentials come from env
(workflow secrets), never from the repo:

  SMTP_USERNAME   sending account, also the From address (required to send)
  SMTP_PASSWORD   app password / account password        (required to send)
  SMTP_HOST/PORT  optional overrides of config values

This is intentionally a **safe no-op** when it can't send: missing HTML (the
digest was skipped in the offseason), an empty digest with `--skip-empty`, or
absent SMTP creds all log a reason and exit 0, so the pipeline never fails just
because delivery isn't wired yet.

Usage:
  python scripts/send_digest.py [--html PATH] [--config PATH]
                                [--snapshot PATH] [--skip-empty] [--require]
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent

# Present in the rendered HTML only when there were no crossings/projections.
_EMPTY_MARKER = "No leaderboard changes this week."


def _subject(snapshot_path: Path) -> str:
    try:
        meta = json.loads(snapshot_path.read_text()).get("meta", {})
        return f"LOTG weekly digest — {meta.get('season')} season, week {meta.get('weeks_completed')}"
    except Exception:
        return "LOTG weekly digest"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Send the LOTG weekly digest email.")
    ap.add_argument("--html", default=str(_ROOT / "exports" / "raw" / "weekly_digest.html"))
    ap.add_argument("--config", default=str(_ROOT / "config" / "digest.yaml"))
    ap.add_argument("--snapshot", default=str(_ROOT / "data" / "digest" / "ranks_snapshot.json"))
    ap.add_argument("--skip-empty", action="store_true",
                    help="don't send when the digest has no changes")
    ap.add_argument("--require", action="store_true",
                    help="exit non-zero instead of skipping when send is impossible")
    args = ap.parse_args(argv)

    def _bail(msg: str) -> int:
        print(f"[send] {msg}")
        return 1 if args.require else 0

    html_path = Path(args.html)
    if not html_path.exists():
        return _bail(f"no digest HTML at {html_path} (offseason / not built) — nothing to send.")
    html = html_path.read_text()

    if args.skip_empty and _EMPTY_MARKER in html:
        return _bail("digest has no changes this week — skipping send.")

    cfg = yaml.safe_load(Path(args.config).read_text()) or {}
    recipients = [r for r in (cfg.get("recipients") or []) if r]
    if not recipients:
        return _bail(f"no recipients configured in {args.config}.")

    user = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    if not user or not password:
        return _bail("SMTP_USERNAME / SMTP_PASSWORD not set — skipping send.")

    host = os.environ.get("SMTP_HOST", cfg.get("smtp_host", "smtp.gmail.com"))
    port = int(os.environ.get("SMTP_PORT", cfg.get("smtp_port", 587)))

    msg = EmailMessage()
    msg["Subject"] = _subject(Path(args.snapshot))
    msg["From"] = formataddr((cfg.get("from_name", "LOTG Stats"), user))
    msg["To"] = ", ".join(recipients)
    msg.set_content("This digest is best viewed as HTML. See the attached leaderboard moves.")
    msg.add_alternative(html, subtype="html")

    print(f"[send] sending digest to {len(recipients)} recipient(s) via {host}:{port}")
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls(context=ctx)
        smtp.login(user, password)
        smtp.send_message(msg)
    print("[send] sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
