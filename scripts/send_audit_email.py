"""Phase 14 — the SECOND weekly email: a dataset-health check to the maintainer.

Separate from the league-wide Tuesday digest, this is a private weekly email to
the maintainer (config/digest.yaml `audit_recipients`, = okeimweiss only) that
alerts on two things:

  * DATASET BREAKAGES — the three-part weekly audit (scripts/audit_weekly.py):
    a completed-season row that changed (historical data must be frozen), a sheet
    that lost / renamed a pinned column, or a real (non-transient, non-current-
    season) build error / failing test.
  * NFLVERSE CHANGES — what upstream revised since the committed exports were
    built. NFLverse back-corrects completed seasons, so rows of ours that moved
    for that reason are NOT breakages; they're reported here as "NFLverse made N
    changes" and only escalate to a breakage when the drift is structural or has
    moved an unreasonable share of our exports.
  * MISSED INJURIES — played in-season weeks that have NO capture in the in-house
    Sleeper injury tracker (scripts/injury_coverage.py), so the build fell back to
    the lagging nflverse feed for them.

It's a weekly heartbeat: it sends every week so a silent inbox means "the check
didn't run", not "nothing's wrong". Pass --skip-clean to suppress the email on a
clean week instead.

A week WITH findings opens with a lede — up to five sentences saying which of
them is most likely to be a REAL BUG, because a flag per sheet with a dozen
detail lines under each is a wall. It is computed, not written: a lost column or
a build error outranks rows that moved, and among rows that moved the SHAPE of
the number change (a value that went blank, dropped to zero, flipped sign, or
jumped an order of magnitude) is what separates a defect from upstream drift.
See lotg_support.email_summary. It cannot stop the email going out. A clean week
gets no lede — that email is already one sentence.

HOW MUCH IT SAYS depends entirely on whether anything needs a decision:

  * NOTHING FLAGGED, no missed weeks, upstream drift measured — the email is its
    title and one line: "NFLverse changed N values, which in turn changed M
    cells". No sections, no all-clear notes for the parts with nothing to say,
    no per-file breakdown. Upstream revising completed seasons and our exports
    following is the normal state of this pipeline, not an event; the only facts
    worth reading are how big the change was and how far it reached. Everything
    else the long form carries exists to be read AGAINST a breakage.
  * ANYTHING FLAGGED — the full layout returns: the breakages themselves, the
    NFLverse breakdown to read them against, and the missed-injury weeks.

Credentials come through lotg_support.mailer (DIGEST_KEY-decrypted, same as the
digest). Safe no-op (logged, exit 0) when creds are absent, unless --require.

Usage:
  PYTHONPATH=src:lib python scripts/send_audit_email.py \
      --exports exports --baseline /tmp/baseline_exports
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "lib"))

import audit_weekly as A                       # noqa: E402
import injury_coverage as C                    # noqa: E402
from lotg_support import email_summary as ES   # noqa: E402
from lotg_support import schedule_watch as SW  # noqa: E402
from lotg_support import mailer                # noqa: E402

_CREDS_ENC = _ROOT / "config" / "digest_credentials.enc"

# Detail lines rendered under one finding. Sized to hold everything the audit
# itself is willing to emit (its own per-finding budget, plus the roll-up and
# "… and N more" lines it adds), so the email never truncates a finding that
# the audit had already trimmed to fit.
_MAX_DETAIL_LINES = A._MAX_REPORT + 6


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
        return ('<p style="color:#137333;margin:0;">✅ Nothing unaccounted for — '
                'every row of every sheet either matches the committed build or is '
                'explained (the wall clock, a renumbered row pointer, or an '
                'NFLverse revision), every sheet keeps its pinned columns, and the '
                'last build logged no errors.</p>')
    items = []
    for f in flags:
        sec = f" <span style=\"color:#888;\">({_esc(f['section'].split('—')[0].strip())})</span>" if f.get("section") else ""
        sub = ""
        if f["details"]:
            # The audit already budgets its detail lines per finding (and says
            # so when it truncates). Re-cutting them here at a smaller, blind
            # limit used to drop whole classes of line — a sheet with 17 changed
            # rows showed 15 of them and none of the follow-on detail.
            shown = [d[2:] if d.startswith("- ") else d       # the <li> is the bullet
                     for d in f["details"][:_MAX_DETAIL_LINES]]
            dropped = len(f["details"]) - len(shown)
            if dropped > 0:
                shown.append(f"… and {dropped} more line(s)")
            lis = "".join(f'<li style="margin:0;">{_esc(d)}</li>' for d in shown)
            sub = f'<ul style="margin:2px 0 6px;padding-left:18px;color:#555;">{lis}</ul>'
        items.append(f'<li style="margin:4px 0;">{_esc(f["text"])}{sec}{sub}</li>')
    return ('<ul style="margin:0;padding-left:20px;color:#8a1c1c;">'
            + "".join(items) + "</ul>")


def _nflverse_html(drift, attributed: int, sheets=None, columns=None,
                   breakages: int = 0) -> str:
    """The 'NFLverse made N changes' line. Upstream back-corrects completed
    seasons; that is their data moving, not our build breaking, so it gets its
    own informational section instead of being counted as a breakage.

    ONE SENTENCE, ALWAYS. This section used to carry a bullet list under the
    header on any week with a breakage: a per-file breakdown of what upstream
    revised, then which of our sheets it explained, then which columns moved in
    them. Nine bullets of five-figure counts, in the section explicitly headed
    "not a breakage" — and the same per-file list already appears verbatim
    under the drift's own flag above it, so the email printed it twice. None of
    it is a decision the maintainer makes: how many `fumble_recovery_yards_own`
    cells upstream touched in 2019 does not change what to do about the rows
    that DID flag. The size of the change and how far it reached is the whole
    story, and that is what `drift.summary()` says. The breakdown still exists
    on the audit's own stdout / the run's step summary, and the artifacts hold
    the frames themselves, for the week somebody wants to dig.

    `sheets` / `columns` / `breakages` stay in the signature: the caller passes
    what the audit computed, and this is the one place that decides how much of
    it a reader sees.
    """
    if drift is None or not getattr(drift, "compared", False):
        return ('<p style="color:#666;margin:0;">No NFLverse snapshot to compare '
                'against this run, so upstream drift was not measured.</p>')
    summary = _esc(drift.summary())
    if not drift.any_change:
        return f'<p style="color:#137333;margin:0;">✅ {summary}</p>'
    tail = ""
    if attributed:
        tail = (f' It accounts for {attributed} changed row(s) in our exports, '
                'which are therefore not flagged as breakages.')
    return f'<p style="margin:0;color:#5a4a00;">ℹ️ {summary}{tail}</p>' 


def _injury_html(gaps: dict, captures_present: bool, incomplete=()) -> str:
    """Missing weeks, AND weeks whose capture landed but is incomplete.

    A week with no rows at all is what `week_gaps` sees. Both of the tracker's
    scheduled workflows can fail while still leaving rows behind — a week with
    sweeps but no Tuesday capture, or a finalized week no gameday sweep ran for —
    and neither of those appears in `gaps`. Sleeper keeps no injury history, so
    both are permanent the moment they happen; they belong in the email, not in a
    markdown report on a workflow's stdout.
    """
    incomplete = list(incomplete)
    if not captures_present:
        return ('<p style="color:#666;margin:0;">The Sleeper injury tracker has no '
                'captures yet (first capture is 2026 week 1), so there are no missed '
                'weeks to report and the build uses the nflverse fallback throughout.</p>')
    if not gaps and not incomplete:
        return ('<p style="color:#137333;margin:0;">✅ Every played in-season week '
                'since the tracker began has an injury capture, each finalized and '
                'with at least one gameday sweep behind it.</p>')
    items = []
    for g in incomplete:
        what = ("no post-week capture" if g.kind == "unfinalized"
                else "no gameday sweep")
        items.append(f'<li style="margin:4px 0;"><b>{_esc(g.label())}</b> — '
                     f'{_esc(what)}: {_esc(g.detail)}</li>')
    for season in sorted(gaps):
        wl = ", ".join(str(w) for w in gaps[season])
        items.append(f'<li style="margin:4px 0;"><b>{season}</b>: weeks {_esc(wl)} were '
                     f'played but have no tracker capture — the build fell back to nflverse '
                     f'for them.</li>')
    return ('<ul style="margin:0;padding-left:20px;color:#8a5a00;">'
            + "".join(items) + "</ul>")


def _missed_runs_html(missed, now) -> str:
    """A scheduled run that never happened leaves no failed workflow to notice."""
    if not missed:
        return ('<p style="color:#137333;margin:0;">✅ Every scheduled weekly run '
                'since the last check completed and left its stamp.</p>')
    items = []
    for m in missed:
        age = m.age_days(now)
        seen = (f'last stamped {age:.1f} days ago ({m.captured_at:%Y-%m-%d %H:%M} UTC)'
                if age is not None else 'never stamped')
        items.append(
            f'<li style="margin:6px 0;"><b>{_esc(m.what)}</b> — '
            f'{m.cycles} scheduled run{"s" if m.cycles != 1 else ""} did not complete. '
            f'Expected by {m.expected_at:%Y-%m-%d %H:%M} UTC; {_esc(seen)} '
            f'(<code>{_esc(m.stamp_path)}</code>).<br>'
            f'<span style="color:#666;">{_esc(m.detail)}</span></li>')
    return ('<ul style="margin:0;padding-left:20px;color:#8a5a00;">'
            + "".join(items) + "</ul>")


def _upstream_only_html(drift, attributed_cells: int) -> str:
    """The whole email, on a week that is nothing but upstream drift.

    One bullet, one sentence, no sections. If every past-season row that moved
    moved because NFLverse revised the data underneath it, there is nothing to
    look at and nothing to decide — the only fact worth a maintainer's attention
    is how big the upstream change was and how far it reached into our exports.
    Everything the long form carries (per-file breakdown, which of our sheets it
    touched, the all-clear notes for the sections with nothing to say) exists to
    be read against a breakage, so on a clean week it is noise around the
    signal. The full layout comes back the moment anything is flagged.
    """
    return ('<ul style="margin:0;padding-left:20px;color:#333;">'
            f'<li style="margin:0;">NFLverse changed {drift.changed_cells} values, '
            f'which in turn changed {attributed_cells} cells</li></ul>')


# ---------------------------------------------------------------------------
# The lede
# ---------------------------------------------------------------------------
# A week with findings is a wall: a flag per sheet, a dozen detail lines under
# each, plus the NFLverse breakdown they have to be read against. The lede says
# which of it is most likely to be a real bug — see lotg_support.email_summary,
# which parses the audit's own detail lines for the SHAPE of each number change
# (blank, zero, sign flip, order of magnitude) rather than just counting rows.
#
# Only on a week WITH findings. The clean-week email is already one sentence
# long; a summary of one sentence is noise.
def _lede_html(intro: str) -> str:
    if not intro:
        return ""
    return ('<p style="margin:0 0 16px;padding:12px 14px;background:#f2f6fb;'
            'border-left:3px solid #0b2545;border-radius:4px;color:#0b2545;">'
            f'{_esc(intro)}</p>')


def render_email(flags, gaps: dict, captures_present: bool, drift=None,
                 attributed: int = 0, attributed_sheets=None, attributed_columns=None,
                 attributed_cells: int = 0, missed=(), now=None, injury_incomplete=()):
    """Return (subject, html, has_issues)."""
    n_break = len(flags)
    n_gap = sum(len(v) for v in gaps.values())
    missed = list(missed)
    n_missed = sum(m.cycles for m in missed)
    injury_incomplete = list(injury_incomplete)
    n_inc = len(injury_incomplete)
    now = now or datetime.now(timezone.utc)
    has_issues = bool(n_break or n_gap or n_missed or n_inc)
    today = date.today().isoformat()

    # Nothing flagged, no missed weeks, and upstream drift actually measured:
    # the week collapses to its one line. Without a drift snapshot we cannot
    # make that claim, so the full layout stands.
    if not has_issues and drift is not None and getattr(drift, "compared", False):
        html = f"""<div style="max-width:680px;margin:0 auto;padding:16px;font:15px/1.5 system-ui,sans-serif;color:#222;">
  <div style="background:#e7f4ea;border-radius:8px;padding:14px 16px;margin-bottom:16px;">
    <h1 style="font:700 20px/1.3 system-ui,sans-serif;color:#0b2545;margin:0;">LOTG dataset health — {today}</h1>
  </div>
  {_upstream_only_html(drift, attributed_cells)}
</div>"""
        return f"✅ LOTG dataset health — all clear ({today})", html, False

    if has_issues:
        bits = []
        if n_break:
            bits.append(f"{n_break} breakage{'s' if n_break != 1 else ''}")
        if n_gap:
            bits.append(f"{n_gap} missed injury week{'s' if n_gap != 1 else ''}")
        if n_inc:
            bits.append(f"{n_inc} incomplete injury week{'s' if n_inc != 1 else ''}")
        if n_missed:
            # First in the subject when it is the only thing wrong: a skipped run
            # means the rest of this email is describing a stale week.
            bits.append(f"{n_missed} missed scheduled run{'s' if n_missed != 1 else ''}")
        subject = f"⚠️ LOTG dataset health — {', '.join(bits)} ({today})"
        banner_bg, banner = "#fdecea", "⚠️ Issues need a look"
    else:
        subject = f"✅ LOTG dataset health — all clear ({today})"
        banner_bg, banner = "#e7f4ea", "✅ All clear this week"

    intro = ES.audit_lede(flags, gaps, drift, attributed) if has_issues else ""
    if intro:
        print(f"[audit-email] lede: {intro}")

    html = f"""<div style="max-width:680px;margin:0 auto;padding:16px;font:15px/1.5 system-ui,sans-serif;color:#222;">
  <div style="background:{banner_bg};border-radius:8px;padding:14px 16px;margin-bottom:16px;">
    <h1 style="font:700 20px/1.3 system-ui,sans-serif;color:#0b2545;margin:0;">LOTG dataset health — {today}</h1>
    <p style="margin:4px 0 0;color:#0b2545;">{banner}</p>
  </div>
  {_lede_html(intro)}
  <h2 style="font:600 17px/1.3 system-ui,sans-serif;color:#1a2b3c;margin:18px 0 6px;">Dataset breakages</h2>
  {_breakage_html(flags)}
  <h2 style="font:600 17px/1.3 system-ui,sans-serif;color:#1a2b3c;margin:22px 0 6px;">NFLverse changes</h2>
  {_nflverse_html(drift, attributed, attributed_sheets, attributed_columns, n_break)}
  <h2 style="font:600 17px/1.3 system-ui,sans-serif;color:#1a2b3c;margin:22px 0 6px;">Missed injuries</h2>
  {_injury_html(gaps, captures_present, injury_incomplete)}
  <h2 style="font:600 17px/1.3 system-ui,sans-serif;color:#1a2b3c;margin:22px 0 6px;">Missed scheduled runs</h2>
  {_missed_runs_html(missed, now)}
  <p style="color:#999;font-size:12px;margin-top:22px;">Automated weekly dataset-health check
  (audit: completed-season immutability, schema, build errors; NFLverse: upstream revisions since
  the committed exports were built; injuries: tracker week gaps, unfinalized and unswept weeks; scheduled runs: weekly cycles with no completion stamp).</p>
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
    ap.add_argument("--nflverse-before", default=None,
                    help="NFLverse cache CSVs as committed, snapshotted before the build")
    ap.add_argument("--nflverse-after", default=str(_ROOT / ".cache"),
                    help="NFLverse cache CSVs after the build re-fetched them")
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
    rep = A.run_audit(
        exports,
        Path(args.baseline) if args.baseline else None,
        Path(args.nflverse_before) if args.nflverse_before else None,
        Path(args.nflverse_after) if args.nflverse_after else None,
    )
    flags = rep.grouped_flags()
    # Injury coverage.
    captures = C.load_captures(Path(args.root))
    summary = C.capture_summary(captures)
    gaps = C.week_gaps(summary, C.played_weeks(_read_csv(exports, "team_week")))

    # A scheduled run that never happened leaves no failed workflow behind, so
    # nothing else in this email would mention it — and every other section would
    # quietly be describing a week-old dataset as if it were current.
    now = datetime.now(timezone.utc)
    try:
        missed = SW.missed_runs(Path(args.root), now=now)
    except Exception as e:                       # never let the watch stop the email
        print(f"[audit-email] schedule watch unavailable: {type(e).__name__}: {e}")
        missed = []
    for m in missed:
        print(f"::warning::[audit-email] {m.what}: {m.cycles} scheduled run(s) did not "
              f"complete (expected by {m.expected_at:%Y-%m-%d %H:%M} UTC)")

    # The tracker's own scheduled runs can fail while still leaving rows behind:
    # a week with sweeps but no Tuesday capture, or a finalized week nobody swept
    # a gameday of. week_gaps() sees neither — it only sees a week with no rows
    # at all — and Sleeper keeps no history, so both are permanent.
    injury_incomplete = SW.injury_capture_health(summary)
    for g in injury_incomplete:
        print(f"::warning::[audit-email] injury tracker {g.label()}: {g.kind}")

    subject, html, has_issues = render_email(
        flags, gaps, bool(captures), rep.drift, rep.nflverse_attributed,
        rep.attributed_sheets, rep.attributed_columns, rep.attributed_cells,
        missed=missed, now=now, injury_incomplete=injury_incomplete)
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
