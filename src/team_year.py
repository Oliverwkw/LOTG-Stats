"""Team-year document output."""

FILE_NAME = "team_year.csv"
PLAN_KEY = "team-year"
FRAME_KEY = "team_year"


def build_output(context):
    return context[FRAME_KEY]
