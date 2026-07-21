"""Phase 14 — the SECOND weekly email: a dataset-health check to the maintainer.

Separate from the league-wide Tuesday digest, this is a private weekly email to
the maintainer (config/digest.yaml `audit_recipients`, = okeimweiss only) that
alerts on two things:

  * DATASET BREAKAGES — the three-part weekly audit (scripts/audit_weekly.py):
    a completed-season row that changed (historical data must be frozen), a sheet
    that lost / renamed a pinned column, or a real (non-transient, non-current-
    season) build error / failing test.
  * MISSED INJURIES — played in-season weeks that have NO capture in the in-house
    Sleeper injury tracker (scripts/injury_coverage.py), so the build fell back to
    the lagging nflverse feed for them.

It's a weekly heartbeat: it sends every week so a silent inbox means "the check
didn't run", not "nothing's wrong". A clean week is a short "✅ all clear" note;
a bad week leads with the specific breakages / missed weeks. Pass --skip-clean to
suppress the email on a clean week instead.

Credentials come through lotg_support.mailer (DIGEST_KEY-decrypted, same as the
digest). Safe no-op (logged, exit 0) when creds are absent, unless --require.

Usage:
  PYTHONPATH=src:lib python scripts/send_audit_email.py \
      --exports exports --baseline /tmp/baseline_exports
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "lib"))

import audit_weekly as A          # noqa: E402
import injury_coverage as C       # noqa: E402
from lotg_support import mailer   # noqa: E402

_CREDS_ENC = _ROOT / "config" / "digest_credentials.enc"


def _audit_recipients(cfg: dict):
    """Maintainer-only recipients; a DIGEST_AUDIT_RECIPIENTS env var (repo
    secret) overrides the committed YAML — see mailer.recipients_from_env."""
    env = mailer.recipients_from_env("DIGEST_AUDIT_RECIPIENTS", "DIGEST_TEST_RECIPIENTS")
    if env is not None:
        return env
    lst = cfg.get("audit_recipients") or cfg.get("test_recipients") or cfg.get("recipients") or []
    return [r for r in lst if r]


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _breakage_html(flags) -> str:
    if not flags:
        return ('<p style="color:#137333;margin:0;">✅ No dataset breakages — '
                'historical data is frozen, every sheet keeps its pinned columns, '
                'and the last build ran clean.</p>')
    items = []
    for f in flags:
        sec = f" <span style=\"color:#888;\">({_esc(f['section'].split('—')[0].strip())})</span>" if f.get("section") else ""
        sub = ""
        if f["details"]:
            lis = "".join(f'<li style="margin:0;">{_esc(d)}</li>' for d in f["details"][:15])
            sub = f'<ul style="margin:2px 0 6px;padding-left:18px;color:#555;">{lis}</ul>'
        items.append(f'<li style="margin:4px 0;">{_esc(f["text"])}{sec}{sub}</li>')
    return ('<ul style="margin:0;padding-left:20px;color:#8a1c1c;">'
            + "".join(items) + "</ul>")


def _injury_html(gaps: dict, captures_present: bool) -> str:
    if not captures_present:
        return ('<p style="color:#666;margin:0;">The Sleeper injury tracker has no '
                'captures yet (first capture is 2026 week 1), so there are no missed '
                'weeks to report and the build uses the nflverse fallback throughout.</p>')
    if not gaps:
        return ('<p style="color:#137333;margin:0;">✅ Every played in-season week '
                'since the tracker began has an injury capture.</p>')
    items = []
    for season in sorted(gaps):
        wl = ", ".join(str(w) for w in gaps[season])
        items.append(f'<li style="margin:4px 0;"><b>{season}</b>: weeks {_esc(wl)} were '
                     f'played but have no tracker capture — the build fell back to nflverse '
                     f'for them.</li>')
    return ('<ul style="margin:0;padding-left:20px;color:#8a5a00;">'
            + "".join(items) + "</ul>")


def render_email(flags, gaps: dict, captures_present: bool):
    """Return (subject, html, has_issues)."""
    n_break = len(flags)
    n_gap = sum(len(v) for v in gaps.values())
    has_issues = bool(n_break or n_gap)
    today = date.today().isoformat()
    if has_issues:
        bits = []
        if n_break:
            bits.append(f"{n_break} breakage{'s' if n_break != 1 else ''}")
        if n_gap:
            bits.append(f"{n_gap} missed injury week{'s' if n_gap != 1 else ''}")
        subject = f"⚠️ LOTG dataset health — {', '.join(bits)} ({today})"
        banner_bg, banner = "#fdecea", "⚠️ Issues need a look"
    else:
        subject = f"✅ LOTG dataset health — all clear ({today})"
        banner_bg, banner = "#e7f4ea", "✅ All clear this week"

    html = f"""<div style="max-width:680px;margin:0 auto;padding:16px;font:15px/1.5 system-ui,sans-serif;color:#222;">
  <div style="background:{banner_bg};border-radius:8px;padding:14px 16px;margin-bottom:16px;">
    <h1 style="font:700 20px/1.3 system-ui,sans-serif;color:#0b2545;margin:0;">LOTG dataset health — {today}</h1>
    <p style="margin:4px 0 0;color:#0b2545;">{banner}</p>
  </div>
  <h2 style="font:600 17px/1.3 system-ui,sans-serif;color:#1a2b3c;margin:18px 0 6px;">Dataset breakages</h2>
  {_breakage_html(flags)}
  <h2 style="font:600 17px/1.3 system-ui,sans-serif;color:#1a2b3c;margin:22px 0 6px;">Missed injuries</h2>
  {_injury_html(gaps, captures_present)}
  <p style="color:#999;font-size:12px;margin-top:22px;">Automated weekly dataset-health check
  (audit: completed-season immutability, schema, build errors; injuries: tracker week gaps).</p>
</div>"""
    return subject, html, has_issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _read_csv(exports: Path, name: str) -> pd.DataFrame:
    p = exports / f"{name}.csv"
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Send the weekly dataset-health email.")
    ap.add_argument("--exports", default=str(_ROOT / "exports"))
    ap.add_argument("--baseline", default=None, help="previous committed exports (Part 1 diff)")
    ap.add_argument("--config", default=str(_ROOT / "config" / "digest.yaml"))
    ap.add_argument("--root", default=str(_ROOT), help="repo root (holds data/injury_tracker.csv)")
    ap.add_argument("--out", default=None, help="also write the email HTML to this path")
    ap.add_argument("--skip-clean", action="store_true",
                    help="don't send when there are no breakages and no missed weeks")
    ap.add_argument("--require", action="store_true",
                    help="exit non-zero instead of skipping when the send is impossible")
    args = ap.parse_args(argv)

    def _bail(msg: str) -> int:
        print(f"[audit-email] {msg}")
        return 1 if args.require else 0

    exports = Path(args.exports)
    # Part 1-3 audit.
    rep = A.run_audit(exports, Path(args.baseline) if args.baseline else None)
    flags = rep.grouped_flags()
    # Injury coverage.
    captures = C.load_captures(Path(args.root))
    summary = C.capture_summary(captures)
    gaps = C.week_gaps(summary, C.played_weeks(_read_csv(exports, "team_week")))

    subject, html, has_issues = render_email(flags, gaps, bool(captures))
    print(f"[audit-email] {subject}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(html + "\n")

    if args.skip_clean and not has_issues:
        return _bail("clean week and --skip-clean set — not sending.")

    cfg = yaml.safe_load(Path(args.config).read_text()) or {}
    recipients = _audit_recipients(cfg)
    if not recipients:
        return _bail(f"no audit_recipients configured in {args.config}.")
    creds = mailer.resolve_credentials(_CREDS_ENC)
    if not creds:
        return _bail("no credentials (set DIGEST_KEY, or SMTP_USERNAME/PASSWORD) — skipping send.")

    print(f"[audit-email] sending to {len(recipients)} recipient(s).")
    mailer.send_html(cfg, recipients, subject, html, creds[0], creds[1])
    print("[audit-email] sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
