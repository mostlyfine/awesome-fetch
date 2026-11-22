"""Panelize the two halves inside a frame with mouse-bite tabs (shapely only)."""
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union
from shapely import affinity

GAP = 2.0          # routing gap between boards / frame
FRAME = 5.0        # frame (rail) width
TAB_W = 5.0        # tab width
TAB_MAX = 9.0      # longest tab we accept
HOLE_D = 0.6       # mouse-bite hole diameter
HOLE_PITCH = 0.95


def place_right(left, right_mirrored):
    """Vertical offset that puts the (already mirrored) right half under the
    left half with at least GAP between them."""
    ly1 = left.bounds[3]
    ry0 = right_mirrored.bounds[1]
    dy = ly1 - ry0 + GAP
    while affinity.translate(right_mirrored, 0, dy - 0.25).distance(left) >= GAP + 0.3:
        dy -= 0.25
    return dy


def frame_for(geoms):
    x0, y0, x1, y1 = unary_union(geoms).bounds
    outer = box(x0 - GAP - FRAME, y0 - GAP - FRAME, x1 + GAP + FRAME, y1 + GAP + FRAME)
    inner = box(x0 - GAP, y0 - GAP, x1 + GAP, y1 + GAP)
    return outer.difference(inner)


def _tabs_between(a, frame_and_others, n_wanted, direction_sets):
    """Find tabs from polygon a to any of others along axis rays."""
    tabs = []
    x0, y0, x1, y1 = a.bounds
    cands = []
    for d in direction_sets:
        if d in ("up", "down"):
            xs = [x0 + TAB_W + i * 1.0 for i in range(int((x1 - x0 - 2 * TAB_W) / 1.0) + 1)]
            for x in xs:
                cands.append((d, x))
        else:
            ys = [y0 + TAB_W + i * 1.0 for i in range(int((y1 - y0 - 2 * TAB_W) / 1.0) + 1)]
            for y in ys:
                cands.append((d, y))
    scored = []
    for d, t in cands:
        r = _ray_tab(a, frame_and_others, d, t)
        if r:
            scored.append((r[0], d, t, r[1]))
    # pick well spread tabs per direction
    by_dir = {}
    for s in scored:
        by_dir.setdefault(s[1], []).append(s)
    for d, lst in by_dir.items():
        lst.sort(key=lambda s: s[2])
        if not lst:
            continue
        span = lst[-1][2] - lst[0][2]
        n = n_wanted.get(d, 2)
        targets = [lst[0][2] + span * (i + 0.5) / n for i in range(n)] if n > 1 else [lst[0][2] + span / 2]
        used = []
        for tg in targets:
            best = min(lst, key=lambda s: (abs(s[2] - tg) + 3 * s[0]))
            if all(abs(best[2] - u) > TAB_W * 2 for u in used):
                used.append(best[2])
                tabs.append(best[3])
    return tabs


def _ray_tab(a, others, d, t):
    """Return (length, (tab_polygon, edgeA_line, edgeB_line)) or None."""
    big = 1000
    h = TAB_W / 2
    if d == "up":
        lines = [LineString([(t + o, -big), (t + o, big)]) for o in (-h, 0, h)]
    elif d == "down":
        lines = [LineString([(t + o, -big), (t + o, big)]) for o in (-h, 0, h)]
    elif d == "left":
        lines = [LineString([(-big, t + o), (big, t + o)]) for o in (-h, 0, h)]
    else:
        lines = [LineString([(-big, t + o), (big, t + o)]) for o in (-h, 0, h)]
    ea, eb = [], []
    for ln in lines:
        ia = ln.intersection(a.exterior)
        pts = [ia] if ia.geom_type == "Point" else list(getattr(ia, "geoms", []))
        pts = [p for p in pts if p.geom_type == "Point"]
        if not pts:
            return None
        if d == "up":
            pa = min(pts, key=lambda p: p.y)
        elif d == "down":
            pa = max(pts, key=lambda p: p.y)
        elif d == "left":
            pa = min(pts, key=lambda p: p.x)
        else:
            pa = max(pts, key=lambda p: p.x)
        # walk outward to next geometry
        best = None
        for o in others:
            io = ln.intersection(o)
            if io.is_empty:
                continue
            for g in getattr(io, "geoms", [io]):
                for c in (list(g.coords) if hasattr(g, "coords") else []):
                    p = Point(c)
                    if d == "up" and p.y < pa.y - 0.01:
                        dist = pa.y - p.y
                    elif d == "down" and p.y > pa.y + 0.01:
                        dist = p.y - pa.y
                    elif d == "left" and p.x < pa.x - 0.01:
                        dist = pa.x - p.x
                    elif d == "right" and p.x > pa.x + 0.01:
                        dist = p.x - pa.x
                    else:
                        continue
                    if best is None or dist < best[0]:
                        best = (dist, p)
        if best is None:
            return None
        ea.append(pa)
        eb.append(best[1])
    lens = [Point(p).distance(q) for p, q in zip(ea, eb)]
    if max(lens) > TAB_MAX or max(lens) - min(lens) > 0.05 or min(lens) < GAP - 0.05:
        return None  # edges must be flat & parallel across the tab
    # check the tab is clear of the board itself
    if d in ("up", "down"):
        ya, yb = ea[1].y, eb[1].y
        tab = box(t - h, min(ya, yb), t + h, max(ya, yb))
        edge_a = LineString([(t - h, ya), (t + h, ya)])
        edge_b = LineString([(t - h, yb), (t + h, yb)])
    else:
        xa, xb = ea[1].x, eb[1].x
        tab = box(min(xa, xb), t - h, max(xa, xb), t + h)
        edge_a = LineString([(xa, t - h), (xa, t + h)])
        edge_b = LineString([(xb, t - h), (xb, t + h)])
    if tab.buffer(-0.05).intersection(a).area > 0.01:
        return None
    return lens[1], (tab, edge_a, edge_b)


def mousebite_holes(edge):
    """Hole centres along an edge line (slightly inside the board)."""
    L = edge.length
    n = int((L - HOLE_D) / HOLE_PITCH) + 1
    start = (L - (n - 1) * HOLE_PITCH) / 2
    return [edge.interpolate(start + i * HOLE_PITCH) for i in range(n)]


def build(left, right, n_tabs=None):
    """left/right: polygons already in panel coordinates.
    Returns (panel_polygon, hole_points)."""
    fr = frame_for([left, right])
    tabs, holes = [], []
    for me, other, dirs in ((left, right, ("up", "left", "right", "down")),
                            (right, left, ("down", "left", "right"))):
        found = _tabs_between(me, [fr, other], n_tabs or {"up": 3, "down": 2, "left": 2, "right": 2}, dirs)
        for tab, ea, eb in found:
            tabs.append(tab)
            # board-side edge -> holes on the board edge line
            holes += mousebite_holes(ea)
            # other side: only drill if it is a board (not the frame)
            if other.distance(eb) < 0.05:
                holes += mousebite_holes(eb)
    panel = unary_union([left, right, fr] + tabs)
    return panel, holes, tabs
