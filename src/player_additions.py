"""Player-additions document output.

One row per player GAINED, across every acquisition channel — add/drop pickup,
trade receive, and draft pick — so the three can be compared on one ruler.
Pure drops are excluded (nothing was gained). Scoring columns are limited to the
tenure that acquisition started and are computed uniformly for all three types.
"""

FILE_NAME = "player_additions.csv"
PLAN_KEY = "player_additions"
FRAME_KEY = "player_additions"


def build_output(context):
    return context[FRAME_KEY]
