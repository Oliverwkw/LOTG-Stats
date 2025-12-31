"""Transactions document output."""

FILE_NAME = "transactions.csv"
PLAN_KEY = "transactions"
FRAME_KEY = "transactions"


def build_output(context):
    return context[FRAME_KEY]
