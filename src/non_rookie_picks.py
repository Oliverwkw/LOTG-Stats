"""Non-rookie picks output: the 2020 startup draft + the 2021 veteran draft.

One half of the picks split (see `pick_history` for why the frame is built as
one table and written as two). These picks are ranked in their own O-Score
percentile universe and carry the draft-slot de-trend; a 19-round startup snake
and a 4-round rookie draft are not comparable, so they no longer share a sheet.
"""
import pick_history

FILE_NAME = "non_rookie_picks.csv"
PLAN_KEY = "non_rookie_picks"
FRAME_KEY = pick_history.FRAME_KEY


def build_output(context):
    ph = context[FRAME_KEY]
    mask = pick_history.non_rookie_mask(ph)
    return ph[mask] if bool(getattr(mask, "any", lambda: False)()) else ph.iloc[0:0]
