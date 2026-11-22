"""Run KiCad DRC on all boards; fail on electrical errors."""
import os
import re
import sys

import pcbnew

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
COSMETIC = {"lib_footprint_issues", "lib_footprint_mismatch", "silk_edge_clearance", "silk_over_copper",
            "silk_overlap", "text_height", "text_thickness"}
bad = 0
for n in ("main", "top-plate", "bottom-plate"):
    src = os.path.join(ROOT, "pcb", f"tsuki65-{n}.kicad_pcb")
    rpt = os.path.join(ROOT, "pcb", f"drc-{n}.rpt")
    b = pcbnew.LoadBoard(src)
    pcbnew.WriteDRCReport(b, rpt, pcbnew.EDA_UNITS_MILLIMETRES, True)
    txt = open(rpt).read()
    kinds = re.findall(r"^\[(\w+)\]", txt, re.M)
    real = [k for k in kinds if k not in COSMETIC]
    unconn = re.search(r"Found (\d+) unconnected", txt).group(1)
    print(f"{n}: {len(kinds)} items, electrical/mechanical errors: {len(real)} {sorted(set(real))}, unconnected: {unconn}")
    bad += len(real) + int(unconn)
sys.exit(1 if bad else 0)
