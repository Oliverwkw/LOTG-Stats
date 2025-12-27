"""Pick history document output."""

FILE_NAME = "pick_history.csv"
PLAN_KEY = "Pick History"
FRAME_KEY = "pick_history"


def build_output(context):
    return context[FRAME_KEY]
