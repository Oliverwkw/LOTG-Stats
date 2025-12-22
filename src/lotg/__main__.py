from __future__ import annotations
from pathlib import Path
from .build import build_all

if __name__ == "__main__":
    build_all(Path(__file__).resolve().parents[2])
