"""Player-year document output."""

FILE_NAME = "player_year.csv"
PLAN_KEY = "Player-year"
FRAME_KEY = "player_year"


def build_output(context):
    return context[FRAME_KEY]
