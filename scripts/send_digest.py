"""Phase 14 — send the rendered weekly digest by email.

Reads the digest HTML (`scripts/build_digest.py` output) and `config/digest.yaml`
and mails it to the configured recipients over SMTP.

Credentials never sit in the repo in the clear. The sending account + password
are AES-256 encrypted into `config/digest_credentials.enc`; the decryption key
is the single `DIGEST_KEY` workflow secret. At send time this script decrypts
the blob (via the `openssl` CLI, no extra Python dependency). As an alternative,
`SMTP_USERNAME` / `SMTP_PASSWORD` env vars override the encrypted file.

  DIGEST_KEY      hex key that decrypts config/digest_credentials.enc
  SMTP_USERNAME   (optional override) sending account + From address
  SMTP_PASSWORD   (optional override) that account's app password
  SMTP_HOST/PORT  optional overrides of config values

This is intentionally a **safe no-op** when it can't send: missing HTML (the
digest was skipped in the offseason), an empty digest with `--skip-empty`, or
absent credentials all log a reason and exit 0, so the pipeline never fails just
because delivery isn't wired yet.

Usage:
  python scripts/send_digest.py [--html PATH] [--config PATH]
                                [--snapshot PATH] [--skip-empty] [--require]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import mailer  # noqa: E402

_CREDS_ENC = _ROOT / "config" / "digest_credentials.enc"

# Re-exported so callers / tests keep the historical names.
_decrypt_credentials = mailer.decrypt_credentials


def _recipients_for(cfg: dict, test: bool):
    """Test emails go to `test_recipients` (falling back to `recipients`); the
    real digest goes to `recipients` (the whole league).

    A DIGEST_TEST_RECIPIENTS / DIGEST_RECIPIENTS env var (repo secret) overrides
    the committed YAML, so the addresses need not sit in this public repo."""
    if test:
        env = mailer.recipients_from_env("DIGEST_TEST_RECIPIENTS", "DIGEST_RECIPIENTS")
        lst = env if env is not None else (
            cfg.get("test_recipients") or cfg.get("recipients") or [])
    else:
        env = mailer.recipients_from_env("DIGEST_RECIPIENTS")
        lst = env if env is not None else (cfg.get("recipients") or [])
    return [r for r in lst if r]


def _resolve_credentials():
    """(username, password) from env override or the encrypted file, else None."""
    return mailer.resolve_credentials(_CREDS_ENC)

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
    ap.add_argument("--test", action="store_true",
                    help="send a confirmation email (delivery banner + a replay of "
                         "the most recent real digest) to the test recipients")
    ap.add_argument("--last-digest", default=str(_ROOT / "data" / "digest" / "last_digest.html"),
                    help="the most recent real digest, replayed inside a test email")
    args = ap.parse_args(argv)

    def _bail(msg: str) -> int:
        print(f"[send] {msg}")
        return 1 if args.require else 0

    cfg = yaml.safe_load(Path(args.config).read_text()) or {}

    if args.test:
        # Delivery banner + a replay of what the most recent real (in-season or
        # post-championship) digest would have said, so a test is representative.
        banner = ('<div style="font:15px/1.5 system-ui,sans-serif;max-width:680px;'
                  'margin:0 auto 8px;padding:16px;background:#eef6ff;border-radius:8px;">'
                  '<h2 style="color:#0b2545;margin:0 0 4px;">Digest delivery is working. 🎉</h2>'
                  '<p style="margin:0;">This is a test. Below is a replay of the most '
                  'recent digest (in the offseason, the post-championship wrap-up).</p></div>')
        last = Path(args.last_digest)
        replay = last.read_text() if last.exists() else (
            '<p style="font:15px system-ui,sans-serif;color:#666;max-width:680px;'
            'margin:0 auto;padding:0 16px;">(No recent digest on record yet.)</p>')
        subject = "LOTG digest — test email ✅"
        html = banner + replay
    else:
        html_path = Path(args.html)
        if not html_path.exists():
            return _bail(f"no digest HTML at {html_path} (offseason / not built) — nothing to send.")
        html = html_path.read_text()
        if args.skip_empty and _EMPTY_MARKER in html:
            return _bail("digest has no changes this week — skipping send.")
        subject = _subject(Path(args.snapshot))

    recipients = _recipients_for(cfg, args.test)
    if not recipients:
        return _bail(f"no recipients configured in {args.config}.")

    creds = _resolve_credentials()
    if not creds:
        return _bail("no credentials (set DIGEST_KEY, or SMTP_USERNAME/SMTP_PASSWORD) — skipping send.")

    print(f"[send] sending digest to {len(recipients)} recipient(s).")
    mailer.send_html(cfg, recipients, subject, html, creds[0], creds[1])
    print("[send] sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
