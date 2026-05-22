#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build/lambda"
PACKAGE_DIR="$BUILD_DIR/package"
DIST_DIR="$ROOT_DIR/dist"

rm -rf "$BUILD_DIR"
mkdir -p "$PACKAGE_DIR" "$DIST_DIR"

python3 -m pip install \
  --upgrade \
  --platform manylinux2014_aarch64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --target "$PACKAGE_DIR" \
  -r "$ROOT_DIR/requirements-lambda.txt"

cp -R "$ROOT_DIR/src" "$PACKAGE_DIR/src"
cp -R "$ROOT_DIR/migrations" "$PACKAGE_DIR/migrations"

find "$PACKAGE_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$PACKAGE_DIR" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

(
  cd "$PACKAGE_DIR"
  zip -qr "$DIST_DIR/captureos_api.zip" .
)

cp "$DIST_DIR/captureos_api.zip" "$DIST_DIR/captureos_ingest.zip"
cp "$DIST_DIR/captureos_api.zip" "$DIST_DIR/captureos_resolver.zip"
cp "$DIST_DIR/captureos_api.zip" "$DIST_DIR/captureos_db_admin.zip"

python3 - <<'PY' "$DIST_DIR"
from pathlib import Path
import json
import sys

dist = Path(sys.argv[1])
for artifact in sorted(dist.glob("captureos_*.zip")):
    print(f"{artifact.name}: {artifact.stat().st_size:,} bytes")
PY
