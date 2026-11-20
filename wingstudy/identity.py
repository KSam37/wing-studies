"""Code identity for resumable studies.

The structural fingerprint is the SHA-256 of the structural model source. It is defined
over module *content*, not file location: package-relative imports are mapped back to
the flat form they had when the code lived in WingStudy/ (``from . import elastic`` ->
``import elastic``, ``from .spanwise_elastic import X`` -> ``from spanwise_elastic import X``).
Moving the files into the package therefore leaves the fingerprint, and every saved
plan and record that carries it, unchanged. Any other edit changes it, as intended.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRUCTURAL_MODULES = ("elastic.py", "spanwise_elastic.py", "finite_span.py", "elastic_runner.py")

_FROM_PKG = re.compile(rb"^([ \t]*)from \. import ", re.M)
_FROM_SUB = re.compile(rb"^([ \t]*)from \.(\w+) import ", re.M)


def canonical_source(source: bytes) -> bytes:
    """Source bytes with package-relative imports written in the original flat form."""
    source = _FROM_PKG.sub(rb"\1import ", source)
    return _FROM_SUB.sub(rb"\1from \2 import ", source)


def structural_fingerprint(directory: Path = HERE) -> str:
    return hashlib.sha256(b"".join(canonical_source((directory / n).read_bytes())
                                   for n in STRUCTURAL_MODULES)).hexdigest()
