#!/usr/bin/env bash
set -euo pipefail

docs_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

if ! command -v plantuml >/dev/null 2>&1; then
  echo "error: plantuml is required" >&2
  exit 1
fi

plantuml -checkonly "$docs_dir/ffmpeg-flow.puml"
plantuml -tsvg "$docs_dir/ffmpeg-flow.puml"
PLANTUML_LIMIT_SIZE=16384 plantuml -DHIGH_DPI=1 -tpng \
  "$docs_dir/ffmpeg-flow.puml"

echo "wrote $docs_dir/ffmpeg-flow.svg"
echo "wrote $docs_dir/ffmpeg-flow.png"
