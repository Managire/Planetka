#!/bin/zsh
cd "$(dirname "$0")/.."
exec "${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}" --background --python tools/planetka_smoke_test.py
