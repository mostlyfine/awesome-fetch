"""Shared geometry for tsuki65 (all units: mm, KiCad coords: x right, y down).

Row-staggered (ANSI-like) 65 % split keyboard.  Both halves are defined in
one common "visual" coordinate system (x = key units * 17 mm, as if the two
halves were one keyboard), so

* the inner edges of the halves follow the key-cell boundaries exactly and
  the two halves can be pushed together into a normal one-piece keyboard;
* the controller (BMP Boost), power switch and battery leads sit in the
  gaps on the OUTER side that the row stagger leaves anyway;
* the AA battery (lead-wire holder) is stuck under the bottom plate.

Footprints are never mirrored.  The left-most key of every row has its
hot-swap socket rotated 180 deg, so that no socket pad sticks out over the
mating edge (right half) or into the BMP area (left half).
"""
from shapely.geometry import Point, box
from shapely.ops import unary_union

P = 17.0                      # key pitch (x and y)

# ---- key layout (all 1U).  (x of the key's left edge in U, label) ------------
ROW_OFF = [0.0, 0.5, 0.75, 1.25]
LEFT_ROWS = [
    ["Esc", "1", "2", "3", "4", "5", "6"],
    ["Tab", "Q", "W", "E", "R", "T"],
    ["Ctrl", "A", "S", "D", "F", "G"],
    ["Shift", "Z", "X", "C", "V", "B"],
]
LEFT_R4 = [(0, "Fn"), (1, "Gui"), (2, "Alt"), (3, "Lower"), (4, "BS"), (5, "Spc")]
RIGHT_ROWS = [
    (7.0, ["7", "8", "9", "0", "-", "=", "BS"]),
    (6.5, ["Y", "U", "I", "O", "P", "[", "]"]),
    (6.75, ["H", "J", "K", "L", ";", "'", "Ent"]),
    (7.25, ["N", "M", ",", ".", "/", "Shift", "Up"]),
]
RIGHT_R4 = [(6.0, "Spc"), (8.0, "Raise"), (9.0, "Alt"), (10.0, "Ctrl"),
            (12.25, "Left"), (13.25, "Down"), (14.25, "Right")]
TB_SLOT = (4, 7.0)            # right half, bottom row next to Space: 14 mm trackball

# ---- controller blocks (outer side).  BMP footprint origin = pin-1 row centre.
# BMP Boost board ~18 x 33 mm, USB at the pin-1 end (top).
CTRL = {
    "L": dict(bmp=(3.5, 27.6),          # rows 2-3, left of Ctrl/Shift
              edge_x=-7.6, sw=(-7.6 + 5.2, 15.5), sw_rot=180,
              bat=(1.0, 20.0), led=(-3.5, 21.2), res=(-3.5, 23.0),
              wire_hole=(2.3, 13.0),
              extra=[(-7.6, 8.5, 21.25, 59.5)]),
    "R": dict(bmp=(248.0, -6.18),       # rows 0-1, right of BS / ]
              edge_x=259.25, sw=(259.25 - 5.2, 33.0), sw_rot=0,
              bat=(247.0, 45.0), led=(246.0, 52.0), res=(246.0, 53.8),
              wire_hole=(252.0, 50.0),
              extra=[(229.5, -8.5, 259.25, 59.5)]),
}
BMP_BOX = (-9.45, -1.82, 9.45, 31.81)  # BMP footprint courtyard (relative)

SPACER_HOLE = 5.0
PLATE_HOLE = 2.2
LUG_R = 4.6


def rect(x0, y0, x1, y1):
    return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def keys(side="L"):
    """list of dicts {r, c, x, y, xv, label, tb, rot}.  c = matrix column
    (COL0 = outer), None for the trackball slot.  rot = socket rotation."""
    out = []
    if side == "L":
        for r, row in enumerate(LEFT_ROWS):
            for i, lab in enumerate(row):
                out.append(dict(r=r, c=i, xv=ROW_OFF[r] + i + 0.5, label=lab))
        for i, (xl, lab) in enumerate(LEFT_R4):
            out.append(dict(r=4, c=i, xv=xl + 0.5, label=lab))
    else:
        for r, (x0, row) in enumerate(RIGHT_ROWS):
            n = len(row)
            for i, lab in enumerate(row):
                out.append(dict(r=r, c=n - 1 - i, xv=x0 + i + 0.5, label=lab))
        n = len(RIGHT_R4)
        for i, (xl, lab) in enumerate(RIGHT_R4):
            out.append(dict(r=4, c=n - 1 - i, xv=xl + 0.5, label=lab))
        out.append(dict(r=TB_SLOT[0], c=None, xv=TB_SLOT[1] + 0.5, label="TB"))
    for k in out:
        k["tb"] = k["c"] is None
        k["y"] = k["r"] * P
        k["x"] = k["xv"] * P
        k["rot"] = 0
    # Rotate the socket of the left-most key of every row by 180 deg so that its
    # pad 1 points into the board: on the right half this keeps the mating
    # edge clean, on the left half it keeps the outer edge / BMP area clear.
    for r in range(5):
        row = [k for k in out if k["r"] == r and not k["tb"]]
        min(row, key=lambda k: k["x"])["rot"] = 180
    return out


def cell(k, grow=0.0):
    h = P / 2 + grow
    return rect(k["x"] - h, k["y"] - h, k["x"] + h, k["y"] + h)


def _close(g, d=1.5):
    return g.buffer(d, join_style=2).buffer(-d, join_style=2)


def bmp_rect(side, margin=0.0):
    bx, by = CTRL[side]["bmp"]
    x0, y0, x1, y1 = BMP_BOX
    return rect(bx + x0 - margin, by + y0 - margin, bx + x1 + margin, by + y1 + margin)


def mating_zone(side):
    """Region beyond the inner (mating) edge, row by row.  Nothing of this
    half may extend into it."""
    ks = keys(side)
    zs = []
    for r in range(5):
        row = [k for k in ks if k["r"] == r]
        y0, y1 = r * P - P / 2, r * P + P / 2
        if r == 0:
            y0 -= 40
        if r == 4:
            y1 += 40
        if side == "L":
            xe = max(k["x"] for k in row) + P / 2
            zs.append(rect(xe, y0, xe + 400, y1))
        else:
            xe = min(k["x"] for k in row) - P / 2
            zs.append(rect(xe - 400, y0, xe, y1))
    return unary_union(zs)


def pad_lugs(side):
    """Socket pad 1 sticks out 1.5 mm beyond the cell on the board-left of
    a key (board-right when the socket is rotated 180 deg)."""
    out = []
    for k in keys(side):
        if k["tb"]:
            continue
        if k["rot"] == 0:
            out.append(rect(k["x"] - 10.7, k["y"] + 1.5, k["x"], k["y"] + 5.9))
        else:
            out.append(rect(k["x"], k["y"] - 5.9, k["x"] + 10.7, k["y"] - 1.5))
    return unary_union(out).difference(mating_zone(side))


def _keepout(side):
    ko = []
    for k in keys(side):
        if k["tb"]:
            ko.append(rect(k["x"] - 9.0, k["y"] - 9.0, k["x"] + 9.0, k["y"] + 9.0))
            continue
        a, b = (10.0, 7.2) if k["rot"] == 0 else (7.2, 10.0)
        ko.append(rect(k["x"] - a, k["y"] - 7.8, k["x"] + b, k["y"] + 7.8))
    c = CTRL[side]
    ko.append(bmp_rect(side, 2.5))
    for p in (c["sw"], c["bat"], c["led"], c["wire_hole"]):
        ko.append(Point(p).buffer(5.5))
    ko.append(rect(c["edge_x"] - 8, c["sw"][1] - 9, c["edge_x"] + 8, c["sw"][1] + 9))  # lever notch
    return unary_union(ko)


def _body(side):
    cells = [cell(k) for k in keys(side)]
    row4 = unary_union([cell(k) for k in keys(side) if k["r"] == 4]).envelope
    extra = [rect(*e) for e in CTRL[side]["extra"]]
    return unary_union(cells + [row4] + extra)


def holes(side="L"):
    """Spacer positions, found automatically around the key area (never on
    the mating edge)."""
    body = _body(side)
    ko = _keepout(side)
    mz = mating_zone(side)
    ring = body.convex_hull.exterior
    n = max(8, int(ring.length / 55))
    res = []
    for i in range(n):
        t = ring.interpolate(ring.length * i / n)
        best = None
        for dx in range(-24, 25):
            for dy in range(-24, 25):
                p = Point(t.x + dx * 0.5, t.y + dy * 0.5)
                if ko.distance(p) < 2.7 or ko.contains(p) or body.distance(p) > 3.0:
                    continue
                if p.buffer(LUG_R + 0.5).intersects(mz):
                    continue
                if any(p.distance(Point(q)) < 30 for q in res):
                    continue
                cost = p.distance(t) + (0 if body.buffer(-2.8).contains(p) else 2.0)
                if best is None or cost < best[0]:
                    best = (cost, (round(p.x, 2), round(p.y, 2)))
        if best:
            res.append(best[1])
    return res


def lugs(side="L"):
    return unary_union([Point(h).buffer(LUG_R, 32) for h in holes(side)])


def _base(side):
    g = unary_union([_body(side), lugs(side), pad_lugs(side)])
    return _close(g, 2.5).difference(mating_zone(side))


def main_outline(side="L"):
    return _base(side).simplify(0.01)


def top_outline(side="L"):
    """Top plate: also open over the BMP Boost."""
    g = _base(side).difference(bmp_rect(side, 0.5))
    g = g.buffer(-0.3, join_style=2).buffer(0.3, join_style=2)
    return g.simplify(0.01)


def bottom_outline(side="L"):
    c = CTRL[side]
    sx, sy = c["sw"]
    ex = c["edge_x"]
    lever = rect(ex - 3.5, sy - 6.0, ex + 3.5, sy + 6.0)   # access to the slide switch
    g = _base(side).difference(lever)
    g = g.difference(Point(c["wire_hole"]).buffer(1.8, 32))
    return g.simplify(0.01)
