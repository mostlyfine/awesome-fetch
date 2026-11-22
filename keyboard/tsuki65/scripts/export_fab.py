"""Export JLCPCB fabrication files.

fab/<board>/gerbers/*  (+ <board>-gerbers.zip)
fab/main/tsuki65-main-bom.csv, tsuki65-main-cpl.csv  (JLCPCB PCBA format)
"""
import csv
import os
import shutil
import subprocess
import sys
import zipfile

import pcbnew

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PCB = os.path.join(ROOT, "pcb")
FAB = os.path.join(ROOT, "fab")

LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"


def run(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit(1)


def gerbers(name):
    src = os.path.join(PCB, f"tsuki65-{name}.kicad_pcb")
    out = os.path.join(FAB, name, "gerbers")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    run("kicad-cli", "pcb", "export", "gerbers", "-l", LAYERS, "--no-x2", "--subtract-soldermask",
        "-o", out + "/", src)
    run("kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
        "--excellon-zeros-format", "decimal", "-u", "mm", "--generate-map", "--map-format", "gerberx2",
        "-o", out + "/", src)
    z = os.path.join(FAB, name, f"tsuki65-{name}-gerbers.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(os.listdir(out)):
            zf.write(os.path.join(out, f), f)
    print("wrote", z)


def bom_cpl():
    b = pcbnew.LoadBoard(os.path.join(PCB, "tsuki65-main.kicad_pcb"))
    groups = {}
    rows = []
    for fp in b.GetFootprints():
        lcsc = fp.GetProperty("LCSC") if fp.HasProperty("LCSC") else ""
        if not lcsc:
            continue
        key = (fp.GetValue(), fp.GetFPID().GetLibItemName().wx_str(), lcsc)
        groups.setdefault(key, []).append(fp.GetReference())
        p = fp.GetPosition()
        rows.append([fp.GetReference(), f"{pcbnew.ToMM(p.x):.4f}mm", f"{-pcbnew.ToMM(p.y):.4f}mm",
                     "Top" if fp.GetLayer() == pcbnew.F_Cu else "Bottom",
                     f"{fp.GetOrientationDegrees() % 360:.1f}"])
    d = os.path.join(FAB, "main")
    with open(os.path.join(d, "tsuki65-main-bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (val, fpn, lcsc), refs in sorted(groups.items()):
            refs.sort(key=lambda r: (r.rstrip("0123456789"), int("0" + "".join(c for c in r if c.isdigit()))))
            w.writerow([val, ",".join(refs), fpn, lcsc])
    with open(os.path.join(d, "tsuki65-main-cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in sorted(rows):
            w.writerow(r)
    print("BOM groups:", {k[0]: len(v) for k, v in groups.items()})


if __name__ == "__main__":
    os.makedirs(FAB, exist_ok=True)
    for n in ("main", "top-plate", "bottom-plate"):
        gerbers(n)
    bom_cpl()
