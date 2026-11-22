"""Generate top plate (1.2 mm) and bottom plate (1.6 mm) panels as PCBs."""
import os
import sys

import pcbnew
from shapely import affinity
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(__file__))
import layout as L  # noqa: E402
import panel  # noqa: E402
from kutil import new_board, draw_polygon_edges, npth, text  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "pcb")
SW_HOLE = 13.8      # Kailh Choc V1/V2 plate cutout
TB_HOLE = 14.0      # maghold 14 mm trackball case (14 x 14 x 2.2 mm plug)


def cutouts(tb_side):
    """Switch cutouts for the LEFT half (local coords)."""
    out = []
    for k in L.keys():
        s = TB_HOLE if (k["tb"] and tb_side) else SW_HOLE
        h = s / 2
        out.append(L.rect(k["x"] - h, k["y"] - h, k["x"] + h, k["y"] + h))
    return unary_union(out)


def build(kind):
    mx = L.mirror_x()
    fn = L.top_outline if kind == "top" else L.bottom_outline
    thick = 1.2 if kind == "top" else 1.6
    left = fn("L")
    right_local = fn("R")
    if kind == "top":
        left = left.difference(cutouts(False))
        right_local = right_local.difference(cutouts(True))
    rm = affinity.scale(right_local, xfact=-1, yfact=1, origin=(mx / 2, 0))
    # use the same vertical offset as the main PCB so all three panels line up
    import gen_main
    _, _, dy, _ = gen_main.outlines()
    right = affinity.translate(rm, 0, dy)
    # plates may be wider (bottom plate battery lip): make sure they don't touch
    if right.distance(left) < panel.GAP:
        dy2 = panel.place_right(left, rm)
        right = affinity.translate(rm, 0, dy2)
        dy = dy2
    board = new_board(thick)
    # tabs only on the outer outline (ignore cutouts)
    lo = type(left)(left.exterior)
    ro = type(right)(right.exterior)
    pnl, holes, tabs = panel.build(lo, ro)
    # put the inner cut-outs back
    inner = unary_union([type(left)(r) for r in left.interiors] +
                        [type(right)(r) for r in right.interiors])
    pnl = pnl.difference(inner)
    draw_polygon_edges(board, pnl)
    for i, p in enumerate(holes):
        npth(board, f"MB{i}", p.x, p.y, panel.HOLE_D)
    for side, T in (("L", lambda x, y: (x, y)), ("R", lambda x, y: (mx - x, y + dy))):
        for i, h in enumerate(L.HOLES):
            X, Y = T(*h)
            npth(board, f"H{side}{i}", X, Y, L.PLATE_HOLE)
    title = "tsuki65 top plate (FR4 1.2 mm, no copper)" if kind == "top" else \
        "tsuki65 bottom plate (FR4 1.6 mm, no copper)"
    text(board, title, pnl.bounds[0] + 30, pnl.bounds[1] + 2.5, 1.5, pcbnew.F_SilkS)
    if kind == "bottom":
        # silk hints on the bottom plate
        for side, T in (("L", lambda x, y: (x, y)), ("R", lambda x, y: (mx - x, y + dy))):
            X, Y = T(*L.O(-19, 20))
            text(board, "battery under here (AA)", X, Y, 1.2, pcbnew.B_SilkS, 90, True)
            X, Y = T(60, 40)
            text(board, "tsuki65 " + ("LEFT" if side == "L" else "RIGHT"), X, Y, 3, pcbnew.B_SilkS, 0, True)
    out = os.path.join(OUT, f"tsuki65-{kind}-plate.kicad_pcb")
    board.Save(out)
    print("saved", out, [round(v, 1) for v in pnl.bounds], "tabs", len(tabs))


if __name__ == "__main__":
    build("top")
    build("bottom")
