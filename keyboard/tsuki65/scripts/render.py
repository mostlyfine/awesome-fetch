"""Render preview images into img/ (needs kicad-cli, cairosvg, matplotlib)."""
import os
import subprocess
import sys
import tempfile

import cairosvg
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
import layout as L  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
IMG = os.path.join(ROOT, "img")


def pcb_png(name, layers, out, width=1400):
    with tempfile.TemporaryDirectory() as d:
        svg = os.path.join(d, "x.svg")
        subprocess.run(["kicad-cli", "pcb", "export", "svg", "-l", layers, "--page-size-mode", "2",
                        "--exclude-drawing-sheet", "-o", svg, os.path.join(ROOT, "pcb", name)],
                       check=True, capture_output=True)
        cairosvg.svg2png(url=svg, write_to=os.path.join(IMG, out), output_width=width,
                         background_color="white")


def layout_png():
    BASE = ["ESC 1 2 3 4 5 ` | LClk 6 7 8 9 0 -", "Tab Q W E R T [ | TB Y U I O P =",
            "Ctrl A S D F G ] | RClk H J K L ; '", "Shift Z X C V B | N M , . / Shift",
            "Fn Gui Alt Lower BS Spc | Ent Lower ← ↓ ↑ →"]
    fig, ax = plt.subplots(figsize=(14, 5.2))
    mxv = 290.0
    rows = [r.replace(" | ", " ").split(" ") for r in BASE]
    ks = {(k["r"], k["c"]): k for k in L.keys()}
    for r in range(5):
        labels = rows[r]
        i = 0
        order = [("L", c) for c in range(7) if (r, c) in ks] + [("R", c) for c in reversed(range(7)) if (r, c) in ks]
        for side, c in order:
            k = ks[(r, c)]
            x = k["x"] if side == "L" else mxv - k["x"]
            y = k["y"]
            tb = side == "R" and k["tb"]
            if tb:
                ax.add_patch(plt.Rectangle((x - 8.25, y - 8.25), 16.5, 16.5, fc="#eeeeee", ec="#999"))
                ax.add_patch(plt.Circle((x, y), 7, fc="#d9534f", ec="#822"))
                ax.text(x, y, "14mm\nTB", ha="center", va="center", fontsize=7, color="white")
            else:
                ax.add_patch(plt.Rectangle((x - 8.0, y - 8.0), 16.0, 16.0, fc="#f7f7f2", ec="#555", lw=1))
                ax.text(x, y, labels[i], ha="center", va="center", fontsize=8)
            i += 1
    for side in ("L", "R"):
        bx = L.OX - 19 if side == "L" else mxv - (L.OX - 19)
        ax.add_patch(plt.Rectangle((bx - 9, L.OY), 18, 33, fc="#cfe3ff", ec="#36c", ls="--"))
        ax.text(bx, L.OY + 16, "BMP\nBoost", ha="center", va="center", fontsize=8, color="#236")
    ax.set_xlim(-15, 305)
    ax.set_ylim(95, -15)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("tsuki65 — column-staggered 65% split, 17 mm pitch, Choc V2, 14 mm trackball (default keymap)")
    fig.savefig(os.path.join(IMG, "layout.png"), dpi=110, bbox_inches="tight")


if __name__ == "__main__":
    os.makedirs(IMG, exist_ok=True)
    layout_png()
    pcb_png("tsuki65-main.kicad_pcb", "Edge.Cuts,F.Cu,B.Cu", "main-pcb-copper.png")
    pcb_png("tsuki65-main.kicad_pcb", "Edge.Cuts,B.SilkS,B.Fab,F.SilkS", "main-pcb-parts.png")
    pcb_png("tsuki65-top-plate.kicad_pcb", "Edge.Cuts,F.SilkS", "top-plate.png", 900)
    pcb_png("tsuki65-bottom-plate.kicad_pcb", "Edge.Cuts,B.SilkS", "bottom-plate.png", 900)
    print("ok")
