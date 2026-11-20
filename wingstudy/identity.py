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


# Code that turns a study case into numbers, beyond the structural model: problem
# construction and load metrics (model.py), the per-design solve and its verification
# ladder (elastic_campaign.py, span_atlas.py), template cases (cases.py).
SOLVE_MODULES = ("model.py", "elastic_campaign.py", "span_atlas.py", "cases.py")


def code_identity() -> dict:
    """What produced a study result: structural fingerprint, solve-path digest, and the
    solver and numerical library versions. Its digest goes into every study case key, so
    changing any of them re-solves instead of reusing a cached result."""
    import json
    import platform
    from importlib import metadata

    def version(dist):
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            return None

    solve = hashlib.sha256(b"".join(canonical_source((HERE / n).read_bytes()) for n in SOLVE_MODULES)).hexdigest()
    ident = {"structural": structural_fingerprint(), "solve_path": solve,
             "ptera": version("pterasoftware"), "numpy": version("numpy"), "numba": version("numba"),
             "scipy": version("scipy"), "python": platform.python_version()}
    ident["digest"] = hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:16]
    return ident
