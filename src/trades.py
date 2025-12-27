"""Trades document output."""

FILE_NAME = "trades.csv"
PLAN_KEY = "trades"
FRAME_KEY = "trades"


def build_output(context):
    return context[FRAME_KEY]
