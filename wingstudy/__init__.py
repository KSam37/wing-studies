"""FAAV Wing Studies: flapping-wing simulation studies in water, built on Ptera Software.

Run commands with ``python -m wingstudy <command>`` from the repository root; see
``python -m wingstudy --help``.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"

from . import cases as _cases  # noqa: E402,F401  installs the template-case fallback (see cases.py)
