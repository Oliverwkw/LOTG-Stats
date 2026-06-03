"""Pick history document output."""

FILE_NAME = "picks.csv"
PLAN_KEY = "picks"
FRAME_KEY = "pick_history"  # internal context key (unchanged); output sheet is "picks"


def build_output(context):
    return context[FRAME_KEY]
