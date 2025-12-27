"""League-week document output."""

FILE_NAME = "league_week.csv"
PLAN_KEY = "league-week"
FRAME_KEY = "league_week"


def build_output(context):
    return context[FRAME_KEY]
