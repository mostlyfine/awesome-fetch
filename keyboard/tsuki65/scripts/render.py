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
    fig, ax = plt.subplots(figsize=(15, 5.4))
    for side, col in (("L", "#333"), ("R", "#a3a")):
        g = L.main_outline(side)
        x, y = g.exterior.xy
        ax.plot(x, y, "-", color=col, lw=1)
        for k in L.keys(side):
            x, y = k["x"], k["y"]
            if k["tb"]:
                ax.add_patch(plt.Rectangle((x - 8.25, y - 8.25), 16.5, 16.5, fc="#eeeeee", ec="#999"))
                ax.add_patch(plt.Circle((x, y), 7, fc="#d9534f", ec="#822"))
                ax.text(x, y, "14mm\nTB", ha="center", va="center", fontsize=7, color="white")
            else:
                ax.add_patch(plt.Rectangle((x - 8.0, y - 8.0), 16.0, 16.0, fc="#f7f7f2", ec="#555", lw=1))
                ax.text(x, y, k["label"], ha="center", va="center", fontsize=8)
        b = L.bmp_rect(side).bounds
        ax.add_patch(plt.Rectangle(b[:2], b[2] - b[0], b[3] - b[1], fc="#cfe3ff", ec="#36c", ls="--"))
        ax.text((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, "BMP\nBoost\n(USB↑)", ha="center", va="center",
                fontsize=7, color="#236")
        sx, sy = L.CTRL[side]["sw"]
        ax.plot([sx], [sy], "s", color="#c60", ms=6)
    ax.set_xlim(-20, 268)
    ax.set_ylim(75, -20)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("tsuki65 — row-staggered 4-row split (halves joined), 17 mm pitch, Choc V2, 14 mm trackball\n"
                 "black = left half, purple = right half, orange = power switch, AA battery under the bottom plate")
    fig.savefig(os.path.join(IMG, "layout.png"), dpi=110, bbox_inches="tight")


if __name__ == "__main__":
    os.makedirs(IMG, exist_ok=True)
    layout_png()
    pcb_png("tsuki65-main.kicad_pcb", "Edge.Cuts,F.Cu,B.Cu", "main-pcb-copper.png")
    pcb_png("tsuki65-main.kicad_pcb", "Edge.Cuts,B.SilkS,B.Fab,F.SilkS", "main-pcb-parts.png")
    pcb_png("tsuki65-top-plate.kicad_pcb", "Edge.Cuts,F.SilkS", "top-plate.png", 900)
    pcb_png("tsuki65-bottom-plate.kicad_pcb", "Edge.Cuts,B.SilkS", "bottom-plate.png", 900)
    print("ok")
