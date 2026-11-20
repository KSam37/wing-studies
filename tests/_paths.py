"""Put the repo root (the wingstudy package) on sys.path.
Every test module imports this first, so tests run with plain unittest from any directory:
    python -m unittest discover -s tests
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
