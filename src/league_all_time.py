"""League-all-time document output."""

FILE_NAME = "league_all_time.csv"
PLAN_KEY = "league-all-time"
FRAME_KEY = "league_all_time"


def build_output(context):
    return context[FRAME_KEY]
