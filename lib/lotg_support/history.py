"""Player career-history reconciliation helpers.

player_all_time's "Top team" / "Last team" are overridden with transaction-tenure
data so sub-week roster sessions (which never produce a player_week row) still
count. But that tenure table is built only from recorded transactions — so a
player who *teleported* onto a roster (a roster change with no transaction, e.g.
a season-boundary carryover) has no tenure record for that team, and the override
would wrongly fall back to a stale early-career tenure.

Daniel Jones is the canonical case: shmuel256 / stevenb123 in 2020 (real
transactions), then JacobRosenzweig 2021-2025 via a teleport (no transaction).
His tenure table holds only the 2020 stints, so the naive override reported
Top team = shmuel256 and Last team = stevenb123 instead of JacobRosenzweig.

These pure helpers reconcile the tenure signal with the authoritative
player_week membership so neither source's blind spot wins.
"""

from __future__ import annotations

from typing import Dict, Optional

SECONDS_PER_WEEK = 7 * 24 * 3600


def reconcile_top_team(
    pw_top_team: Optional[str],
    tenure_secs_by_team: Optional[Dict[str, float]],
    pw_weeks_by_team: Optional[Dict[str, int]],
    week_secs: int = SECONDS_PER_WEEK,
) -> Optional[str]:
    """Team that rostered the player for the most time.

    Combines explicit tenure seconds (captures sub-week sessions player_week
    misses) with player_week rostered weeks scaled to seconds (captures teleport
    memberships the tenure table misses), then takes the argmax. Overlapping
    weeks counted in both sources are additive for every team, so the winner is
    unchanged for the common case where the two agree — only teleport/sub-week
    blind spots move it. Falls back to ``pw_top_team`` when there is no signal.
    """
    combined: Dict[str, float] = {}
    for tm, secs in (tenure_secs_by_team or {}).items():
        if tm:
            combined[tm] = combined.get(tm, 0.0) + float(secs)
    for tm, weeks in (pw_weeks_by_team or {}).items():
        if tm:
            combined[tm] = combined.get(tm, 0.0) + int(weeks) * week_secs
    if not combined:
        return pw_top_team
    return max(combined.items(), key=lambda kv: kv[1])[0]


def reconcile_last_team(
    pw_last_team: Optional[str],
    pw_last_fy: Optional[int],
    tenure_last_fy: Optional[int],
    tenure_last_team: Optional[str],
) -> Optional[str]:
    """Team that held the player most recently.

    Prefers the tenure last-event team (it can see an offseason move that never
    produced a player_week row) — UNLESS that event predates the player's last
    rostered season, which means it is a stale early-career tenure and the
    player_week last team is the real most-recent roster. Falls back to
    ``pw_last_team`` when there is no tenure event.
    """
    if not tenure_last_team:
        return pw_last_team
    if pw_last_fy is not None and tenure_last_fy is not None and tenure_last_fy < pw_last_fy:
        return pw_last_team
    return tenure_last_team
