"""Shared geometry for tsuki65 (all units: mm, KiCad coords: x right, y down).

The LEFT half is defined in local coordinates; the right half is the mirror
image (x -> MIRROR_X - x).  Footprints are never mirrored (same as
torabo-tsuki LP): only their positions are.
"""
from shapely.geometry import Polygon, box, MultiPoint
from shapely.ops import unary_union

P = 17.0                      # key pitch (x and y)
COL_OFF = [8, 8, 3, 0, 3, 5, 5]   # column stagger (mm, + = lower), c0 = outer pinky
THUMB_DROP = 2.0              # extra drop of the thumb keys (row 4, c3..c5)
TB_KEY = (1, 6)               # (row, col) of the 14 mm trackball position

# ---- controller block copied from torabo-tsuki LP M (left half) -------------
# Origin O = upper battery-holder pin.  Keeps compatibility with
# torabo-tsuki LP 3d-models/STL/controller-cover-aa-Body(.stl / -mirror.stl).
# +2 mm gap so the (unmirrored) socket pads of the right half's inner column
# stay clear of the BMP pins.
OX = 6 * P + 8.5 + 2.0 + 28.5  # 141.0
OY = (COL_OFF[6] - 8.5) + 1.7 # -1.8


def keys():
    """Return list of dicts {r, c, x, y, tb} for the LEFT half."""
    out = []
    for c in range(6):
        for r in range(4):
            out.append(dict(r=r, c=c, x=c * P, y=r * P + COL_OFF[c]))
    for r in range(3):
        out.append(dict(r=r, c=6, x=6 * P, y=r * P + COL_OFF[6]))
    for c in range(3):
        out.append(dict(r=4, c=c, x=c * P, y=4 * P + COL_OFF[c]))
    for c in range(3, 6):
        out.append(dict(r=4, c=c, x=c * P, y=4 * P + COL_OFF[c] + THUMB_DROP))
    for k in out:
        k["tb"] = (k["r"], k["c"]) == TB_KEY
    return out


# Spacer positions (LEFT half).  5 mm holes in the main PCB (M2 x 4.5 mm
# spacer passes through), 2.2 mm holes in top/bottom plates.  At 17 mm pitch
# there is no room between switches, so they sit in stagger pockets / empty
# spots; the outline gets a small lug around each one.
HOLES = [
    (8.5, -3.6),     # top-left pocket (above c0/c1)
    (93.5, -6.6),    # top, above c5/c6
    (102.0, 56.0),   # empty c6/r3 spot
    (120.5, 61.8),   # under controller cover (torabo position, O(-20.5, 63.6))
    (106.0, 73.0),   # between thumbs and controller
    (42.5, 82.6),    # bottom, between c2/r4 and thumb c3
    (8.5, 85.6),     # bottom-left
]
SPACER_HOLE = 5.0
PLATE_HOLE = 2.2
LUG_R = 4.6


def lugs():
    from shapely.geometry import Point
    return unary_union([Point(h).buffer(LUG_R, 32) for h in HOLES])


def O(dx, dy):
    return (OX + dx, OY + dy)


def rect(x0, y0, x1, y1):
    return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def cell(k, grow=0.0):
    h = P / 2 + grow
    return rect(k["x"] - h, k["y"] - h, k["x"] + h, k["y"] + h)


def _close(g, d=1.5):
    return g.buffer(d, join_style=2).buffer(-d, join_style=2)


def _keymap():
    return {(k["r"], k["c"]): k for k in keys()}


def module_rect():
    return rect(OX - 28.5, OY - 2.0, OX + 2.5, OY + 67.0)


def battery_notch():
    return rect(OX - 8.5, OY + 2.0, OX + 2.6, OY + 59.0)


def pad_lugs(side):
    """Socket pad 1 sticks out 1.5 mm beyond the 17 mm cell (on the left of
    each key in board coordinates).  In LEFT-local coordinates that is the
    -x side for the left half and the +x side for the right half."""
    out = []
    for k in keys():
        if side == "L":
            out.append(rect(k["x"] - 10.7, k["y"] + 1.5, k["x"], k["y"] + 5.9))
        else:
            out.append(rect(k["x"], k["y"] + 1.5, k["x"] + 10.7, k["y"] + 5.9))
    return unary_union(out)


def _fill():
    km = _keymap()
    pts = []
    for rc in [(4, 4), (4, 5), (2, 6), (3, 5)]:
        pts += list(cell(km[rc]).exterior.coords)
    m = module_rect()
    x0, y0, x1, y1 = m.bounds
    pts += [(x0, y1 - 30), (x1, y1 - 30), (x1, y1), (x0, y1)]
    return MultiPoint(pts).convex_hull


def _base(side):
    cells = unary_union([cell(k) for k in keys()])
    g = unary_union([cells, module_rect(), _fill(), lugs(), pad_lugs(side)])
    return _close(g, 2.5)


def main_outline(side="L"):
    g = _base(side).difference(battery_notch())
    return g.simplify(0.01)


def controller_zone():
    """Area left free on the top plate for the controller cover."""
    return unary_union([
        rect(OX - 28.5, OY - 50, OX + 50, OY + 37.8),
        rect(OX - 9.5, OY - 50, OX + 50, OY + 64.5),
    ])


def top_outline(side="L"):
    g = _base(side).difference(controller_zone())
    # remove slivers
    g = g.buffer(-0.3, join_style=2).buffer(0.3, join_style=2)
    return g.simplify(0.01)


def bottom_outline(side="L"):
    g = unary_union([_base(side), rect(OX + 2.0, OY + 2.0, OX + 8.5, OY + 59.0)])
    g = _close(g, 2.5)
    cut = unary_union([
        rect(OX - 0.9, OY - 5, OX + 0.6, OY + 5.7),     # battery pin slot (open)
        rect(OX - 0.9, OY + 55.2, OX + 0.6, OY + 62.0),  # battery pin slot
        rect(OX - 24.0, OY - 5, OX - 14.0, OY + 2.3),   # power switch access
    ])
    return g.difference(cut).simplify(0.01)


# Mirror axis for the right half (x_board = MX - x_local).
MX = -8.5 + OX + 2.5


def mirror_x():
    return MX
