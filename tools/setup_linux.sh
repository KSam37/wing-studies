#!/usr/bin/env bash
# Linux/macOS setup: pinned Ptera source + a private virtual environment.
# Mirrors "Setup Windows.cmd": verifies the pinned archive checksum from
# tools/ptera-source.json, installs Ptera in editable mode, and never touches
# the system Python. Environment lives outside the repository.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${WINGSTUDIES_VENV:-$HOME/.local/share/WingStudies/venv-linux}"
PY="${PYTHON:-python3}"

read -r COMMIT SHA < <("$PY" -c "import json;d=json.load(open('$ROOT/tools/ptera-source.json'));print(d['commit'],d['archive_sha256'])")

if [ ! -f "$ROOT/PteraSoftware/setup.cfg" ]; then
  echo "Fetching pinned Ptera $COMMIT"
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  curl -fsSL -o "$TMP/src.zip" "https://codeload.github.com/camUrban/PteraSoftware/zip/$COMMIT"
  echo "$SHA  $TMP/src.zip" | sha256sum -c -
  (cd "$TMP" && unzip -q src.zip)
  mkdir -p "$ROOT/PteraSoftware"
  cp -a "$TMP/PteraSoftware-$COMMIT/." "$ROOT/PteraSoftware/"
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating $VENV"
  mkdir -p "$(dirname "$VENV")"
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e "$ROOT/PteraSoftware" reportlab shapely trimesh
"$VENV/bin/python" -c "import pterasoftware, numpy, numba; print('Ready: Ptera', pterasoftware.__name__, 'numpy', numpy.__version__, 'numba', numba.__version__)"
echo "Run studies with: $VENV/bin/python $ROOT/WingStudy/elastic_study.py --help"
