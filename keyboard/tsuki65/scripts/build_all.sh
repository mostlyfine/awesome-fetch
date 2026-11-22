#!/bin/sh
# Regenerate everything (needs KiCad 7 python + shapely + matplotlib).
set -e
cd "$(dirname "$0")"
PY=${PY:-/usr/bin/python3.12}
$PY gen_main.py
$PY route.py ../pcb/tsuki65-main-unrouted.kicad_pcb ../pcb/tsuki65-main.kicad_pcb 4
$PY gen_plates.py
$PY drc.py
$PY export_fab.py
python3 gen_fw.py
python3 render.py
