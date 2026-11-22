"""Shared geometry for tsuki65 (all units: mm, KiCad coords: x right, y down).

Both halves are defined in "local" coordinates where the controller block is
on the +x side; the right half is placed on the board mirrored
(x_board = MX - x_local).  Footprints are never mirrored (same as
torabo-tsuki LP): only their positions are.  The key layout is row-staggered,
so the two halves are NOT mirror images of each other.
"""
from shapely.geometry import Polygon, box, MultiPoint
from shapely.ops import unary_union

P = 17.0                      # key pitch (x and y)

# ---- row-staggered 65% split (ANSI-like stagger, all keys 1U) ---------------
# Visual layout in key units (U = 17 mm): (row, x of the key's left edge, label)
ROW_OFF = [0.0, 0.5, 0.75, 1.25]   # number / top / home / bottom row stagger
LEFT_ROWS = [
    ["Esc", "1", "2", "3", "4", "5", "6"],
    ["Tab", "Q", "W", "E", "R", "T"],
    ["Ctrl", "A", "S", "D", "F", "G"],
    ["Shift", "Z", "X", "C", "V", "B"],
]
LEFT_R4 = [(0, "Fn"), (1, "Gui"), (2, "Alt"), (3, "Lower"), (4, "BS"), (5, "Spc")]
RIGHT_ROWS = [  # first key's left edge in U, labels
    (7.0, ["7", "8", "9", "0", "-", "=", "BS"]),
    (6.5, ["Y", "U", "I", "O", "P", "[", "]"]),
    (6.75, ["H", "J", "K", "L", ";", "'", "Ent"]),
    (7.25, ["N", "M", ",", ".", "/", "Shift", "Up"]),
]
RIGHT_R4 = [(7.25, "Spc"), (8.25, "Raise"), (9.25, "Alt"), (12.25, "Left"), (13.25, "Down"), (14.25, "Right")]
TB_SLOT = (1, 5.5)            # right half: row 1, just inside "Y" -> 14 mm trackball

# Local coordinates: left half x = xv * P (xv = key centre in U).
# Right half is stored mirrored (x_local = KR - xv * P) so that, as before, the
# controller block sits at +x and board_x = MX - x_local.
INNER_EDGE = 7.25 * P         # innermost key edge of the left half (B key)
KR = INNER_EDGE + 5.5 * P     # right half: TB slot inner edge maps to INNER_EDGE

# ---- controller block copied from torabo-tsuki LP M (left half) -------------
# Origin O = upper battery-holder pin.  Keeps compatibility with
# torabo-tsuki LP 3d-models/STL/controller-cover-aa-Body(.stl / -mirror.stl).
# 2 mm gap so the (unmirrored) socket pads stay clear of the BMP pins.
OX = INNER_EDGE + 2.0 + 28.5
OY = -P / 2 + 2.0


def keys(side="L"):
    """Return list of dicts {r, c, x, y, xv, label, tb} (local coords).
    c = matrix column (COL0 = outer), None for the trackball slot."""
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
        k["x"] = k["xv"] * P if side == "L" else KR - k["xv"] * P
    return out


SPACER_HOLE = 5.0
PLATE_HOLE = 2.2
LUG_R = 4.6


def _keepout(side):
    """Areas a 5 mm spacer hole must stay 2.7 mm away from (local coords)."""
    ko = []
    for k in keys(side):
        a, b = (10.0, 7.2) if side == "L" else (7.2, 10.0)   # socket pad 1 side
        ko.append(rect(k["x"] - a, k["y"] - 7.2, k["x"] + b, k["y"] + 7.8))
    return unary_union(ko)


def _cover():
    """Footprint of the controller cover (+ margin) - no top plate there."""
    return rect(OX - 31.0, OY - 15, OX + 15, OY + 70)


def holes(side="L"):
    """Spacer positions, found automatically around the key area."""
    from shapely.geometry import Point
    cells = unary_union([cell(k) for k in keys(side)])
    keys_ko = _keepout(side)
    ko = unary_union([keys_ko, _cover()])
    fixed = [O(-20.5, 63.6)]                                   # torabo position under the cover
    hull = unary_union([cells, module_rect()]).convex_hull
    targets = []
    ring = hull.exterior
    n = max(6, int(ring.length / 70))
    for i in range(n):
        targets.append(ring.interpolate(ring.length * i / n))
    body = unary_union([cells, module_rect(), _fill(side)])
    res = [p for p in fixed if keys_ko.distance(Point(p)) >= 2.7]
    for t in targets:
        best = None
        for dx in range(-24, 25):
            for dy in range(-24, 25):
                p = Point(t.x + dx * 0.5, t.y + dy * 0.5)
                if ko.distance(p) < 2.7 or ko.contains(p) or body.distance(p) > 3.0:
                    continue
                if any(p.distance(Point(q)) < 30 for q in res):
                    continue
                cost = p.distance(t) + (0 if cells.buffer(-2.8).contains(p) else 2.0)
                if best is None or cost < best[0]:
                    best = (cost, (round(p.x, 2), round(p.y, 2)))
        if best:
            res.append(best[1])
    return res


def lugs(side="L"):
    from shapely.geometry import Point
    return unary_union([Point(h).buffer(LUG_R, 32) for h in holes(side)])


def O(dx, dy):
    return (OX + dx, OY + dy)


def rect(x0, y0, x1, y1):
    return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def cell(k, grow=0.0):
    h = P / 2 + grow
    return rect(k["x"] - h, k["y"] - h, k["x"] + h, k["y"] + h)


def _close(g, d=1.5):
    return g.buffer(d, join_style=2).buffer(-d, join_style=2)


def module_rect():
    return rect(OX - 28.5, OY - 2.0, OX + 2.5, OY + 67.0)


def battery_notch():
    return rect(OX - 8.5, OY + 2.0, OX + 2.6, OY + 59.0)


def pad_lugs(side):
    """Socket pad 1 sticks out 1.5 mm beyond the 17 mm cell (on the left of
    each key in board coordinates).  In LEFT-local coordinates that is the
    -x side for the left half and the +x side for the right half."""
    out = []
    for k in keys(side):
        if k["tb"]:
            continue
        if side == "L":
            out.append(rect(k["x"] - 10.7, k["y"] + 1.5, k["x"], k["y"] + 5.9))
        else:
            out.append(rect(k["x"], k["y"] + 1.5, k["x"] + 10.7, k["y"] + 5.9))
    return unary_union(out)


def _fill(side):
    """Fill between the ragged inner edge of the keys and the controller block."""
    ks = keys(side)
    pts = list(module_rect().exterior.coords)
    for r in range(5):
        row = [k for k in ks if k["r"] == r]
        inner = max(row, key=lambda k: k["x"])
        pts += list(cell(inner).exterior.coords)
    return MultiPoint(pts).convex_hull


def _base(side):
    cells = unary_union([cell(k) for k in keys(side)] + [
        unary_union([cell(k) for k in keys(side) if k["r"] == 4]).envelope])
    g = unary_union([cells, module_rect(), _fill(side), lugs(side), pad_lugs(side)])
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
MX = OX + 2.5


def mirror_x():
    return MX
