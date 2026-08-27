"""Rookie picks output: every rookie draft (2021 onward, excluding the vet draft).

The other half of the picks split (see `pick_history`). These keep the O-Score
exactly as the build computes it — the de-trend applies only to the non-rookie
sheet — and the current class stays ungraded until week 8 of its rookie season.
"""
import pick_history

FILE_NAME = "rookie_picks.csv"
PLAN_KEY = "rookie_picks"
FRAME_KEY = pick_history.FRAME_KEY


def build_output(context):
    ph = context[FRAME_KEY]
    mask = pick_history.non_rookie_mask(ph)
    return ph[~mask] if bool(getattr(mask, "any", lambda: False)()) else ph
