"""Team-all-time document output."""

FILE_NAME = "team_all_time.csv"
PLAN_KEY = "team-all-time"
FRAME_KEY = "team_all_time"


def build_output(context):
    return context[FRAME_KEY]
