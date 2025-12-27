"""League-year document output."""

FILE_NAME = "league_year.csv"
PLAN_KEY = "league-year"
FRAME_KEY = "league_year"


def build_output(context):
    return context[FRAME_KEY]
