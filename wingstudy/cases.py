"""Template cases for the elastic studies.

The elastic studies start from a recorded rigid catalog case (geometry template and
solver settings). The full catalogs are large local SQLite files that are never
committed, so the cases the studies need are shipped in data/template_cases as JSON
exported from the master catalog (identical payloads). The local catalogs are still
read first when present.

This lives outside elastic_runner.py on purpose: that file is part of the structural
fingerprint, and resuming saved studies requires its content to stay unchanged. Importing
the package installs load_case as elastic_runner.load_catalog_case, so every caller,
elastic_runner's own included, gets the fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import elastic_runner

_catalog_only = getattr(elastic_runner.load_catalog_case, "catalog_only", elastic_runner.load_catalog_case)
TEMPLATE_CASES = Path(__file__).resolve().parent / "data" / "template_cases"


def load_case(case_no: int):
    """(case, settings) for a global case number: local catalogs first, then the shipped templates."""
    try:
        return _catalog_only(case_no)
    except KeyError:
        frozen = TEMPLATE_CASES / f"case_{int(case_no)}.json"
        if not frozen.exists():
            raise
        payload = json.loads(frozen.read_text(encoding="utf-8"))["payload"]
        return payload["case"], payload["settings"]


load_case.catalog_only = _catalog_only
elastic_runner.load_catalog_case = load_case
