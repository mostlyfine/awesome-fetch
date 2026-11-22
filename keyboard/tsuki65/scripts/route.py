"""Simple 2-layer grid A* autorouter for KiCad 7 boards (pcbnew API).

usage: python3.12 route.py in.kicad_pcb out.kicad_pcb

* 0.25 mm grid, 8-way moves, vias
* every net is routed as an incremental Steiner tree (A* from the next pad to
  the already-routed copper of the same net)
* failed nets are moved to the front and everything is re-routed (rip-up
  and retry), a few passes
"""
import heapq
import math
import sys
import time

import numpy as np
import pcbnew
from matplotlib.path import Path
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union, polygonize

G = 0.25            # grid (mm)
TRACK_W = 0.25
VIA_D, VIA_DRILL = 0.6, 0.3
CLR = 0.2
PAD_INFL = TRACK_W / 2 + CLR + 0.12      # keep track centre away from foreign copper
HOLE_INFL = TRACK_W / 2 + 0.25 + 0.12    # hole-to-copper
EDGE_INFL = TRACK_W / 2 + 0.3 + 0.1
TRACK_KEEP = TRACK_W + CLR + 0.12        # centre-to-centre keepout between nets
VIA_KEEP = VIA_D / 2 + CLR + TRACK_W / 2 + 0.1
VIA_COST = 12
DIAG = math.sqrt(2)


def mm(v):
    return pcbnew.ToMM(v)


class Grid:
    def __init__(self, board):
        self.board = board
        bb = board.GetBoardEdgesBoundingBox()
        self.x0 = mm(bb.GetLeft()) - 1
        self.y0 = mm(bb.GetTop()) - 1
        self.nx = int((mm(bb.GetRight()) + 1 - self.x0) / G) + 1
        self.ny = int((mm(bb.GetBottom()) + 1 - self.y0) / G) + 1
        # owner: 0 free, -1 blocked, >0 net code (only that net may use)
        self.own = np.zeros((2, self.ny, self.nx), dtype=np.int32)
        self.core = np.zeros((2, self.ny, self.nx), dtype=np.int32)  # pad copper (net)
        xs = self.x0 + np.arange(self.nx) * G
        ys = self.y0 + np.arange(self.ny) * G
        self.X, self.Y = np.meshgrid(xs, ys)

    def ij(self, x, y):
        return int(round((y - self.y0) / G)), int(round((x - self.x0) / G))

    def xy(self, i, j):
        return self.x0 + j * G, self.y0 + i * G

    def window(self, geom, r):
        x0, y0, x1, y1 = geom.bounds
        i0, j0 = self.ij(x0 - r, y0 - r)
        i1, j1 = self.ij(x1 + r, y1 + r)
        i0, j0 = max(i0 - 1, 0), max(j0 - 1, 0)
        i1, j1 = min(i1 + 2, self.ny), min(j1 + 2, self.nx)
        return i0, i1, j0, j1

    def mask(self, geom, r):
        """boolean mask (window) of grid points within r of geom."""
        i0, i1, j0, j1 = self.window(geom, r)
        g = geom.buffer(r, 16) if r > 0 else geom
        m = np.zeros((i1 - i0, j1 - j0), dtype=bool)
        for poly in getattr(g, "geoms", [g]):
            if poly.is_empty:
                continue
            path = Path(np.asarray(poly.exterior.coords))
            pts = np.column_stack([self.X[i0:i1, j0:j1].ravel(), self.Y[i0:i1, j0:j1].ravel()])
            mm_ = path.contains_points(pts).reshape(m.shape)
            for hole in poly.interiors:
                mm_ &= ~Path(np.asarray(hole.coords)).contains_points(pts).reshape(m.shape)
            m |= mm_
        return (i0, i1, j0, j1), m

    def claim(self, layer, geom, r, net):
        (i0, i1, j0, j1), m = self.mask(geom, r)
        sub = self.own[layer, i0:i1, j0:j1]
        if net <= 0:
            sub[m] = -1
        else:
            cur = sub[m]
            cur = np.where((cur == 0) | (cur == net), net, -1)
            sub[m] = cur

    def set_core(self, layer, geom, net):
        (i0, i1, j0, j1), m = self.mask(geom, 0.0)
        if not m.any():  # tiny pad: take nearest grid point
            c = geom.centroid
            i, j = self.ij(c.x, c.y)
            self.core[layer, i, j] = net
            self.own[layer, i, j] = net
            return
        self.core[layer, i0:i1, j0:j1][m] = net
        self.own[layer, i0:i1, j0:j1][m] = net


def pad_shape(pad):
    """shapely polygon of a pad's copper (approximate for roundrect)."""
    poly = pad.GetEffectivePolygon()
    out = []
    for k in range(poly.OutlineCount()):
        ol = poly.Outline(k)
        pts = [(mm(ol.CPoint(n).x), mm(ol.CPoint(n).y)) for n in range(ol.PointCount())]
        if len(pts) >= 3:
            out.append(Polygon(pts))
    return unary_union(out)


def hole_shape(pad):
    p = pad.GetPosition()
    d = pad.GetDrillSize()
    dx, dy = mm(d.x), mm(d.y)
    c = Point(mm(p.x), mm(p.y))
    if abs(dx - dy) < 1e-3:
        return c.buffer(dx / 2, 16)
    ang = pad.GetOrientationDegrees()
    L = abs(dx - dy) / 2
    r = min(dx, dy) / 2
    if dx > dy:
        seg = LineString([(-L, 0), (L, 0)])
    else:
        seg = LineString([(0, -L), (0, L)])
    from shapely import affinity
    seg = affinity.rotate(seg, -ang, origin=(0, 0))
    seg = affinity.translate(seg, c.x, c.y)
    return seg.buffer(r, 16)


def board_outline(board):
    """Material region of the board: faces of the Edge.Cuts arrangement whose
    interior point lies inside an odd number of edge loops (ray casting)."""
    segs = []
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_SEGMENT:
            a, b = d.GetStart(), d.GetEnd()
            segs.append(((mm(a.x), mm(a.y)), (mm(b.x), mm(b.y))))
    faces = list(polygonize(unary_union([LineString(s) for s in segs])))
    S = np.array([[a[0], a[1], b[0], b[1]] for a, b in segs])
    keep = []
    for f in faces:
        p = f.representative_point()
        x, y = p.x, p.y
        y1, y2 = S[:, 1], S[:, 3]
        cross = (y1 > y) != (y2 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = S[:, 0] + (y - y1) * (S[:, 2] - S[:, 0]) / (y2 - y1)
        n = np.count_nonzero(cross & (xi > x))
        if n % 2 == 1:
            keep.append(f)
    return unary_union(keep)


class Router:
    def __init__(self, board):
        self.board = board
        self.g = Grid(board)
        self.pads = {}     # net -> list of (layers, shape, pad)
        self.paths = {}    # net -> list of paths [(l,i,j),...]
        self.vias = {}
        self._build()

    def fanout(self):
        """Fan fine-pitch pads (e.g. 0.5 mm FPC connector) out to a 1.25 mm
        pitch with short 0.2 mm stubs, so the grid router can reach them."""
        stubs = []
        self.fanned = set()
        for fp in self.board.GetFootprints():
            small = [p for p in fp.Pads() if p.GetNetCode() > 0 and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                     and min(p.GetSize().x, p.GetSize().y) < pcbnew.FromMM(0.4)]
            if len(small) < 3:
                continue
            shapes = [pad_shape(p) for p in small]
            b = [sh.bounds for sh in shapes]
            w = b[0][2] - b[0][0]
            h = b[0][3] - b[0][1]
            axis = (0, 1) if h > w else (1, 0)      # pad long axis
            perp = (axis[1], axis[0])
            plen = max(w, h)
            cen = [sh.centroid for sh in shapes]
            fpc = (mm(fp.GetPosition().x), mm(fp.GetPosition().y))
            mx_ = sum(c.x for c in cen) / len(cen)
            my_ = sum(c.y for c in cen) / len(cen)
            sgn = 1 if ((mx_ - fpc[0]) * axis[0] + (my_ - fpc[1]) * axis[1]) > 0 else -1
            d = (axis[0] * sgn, axis[1] * sgn)
            order = sorted(range(len(small)), key=lambda k: cen[k].x * perp[0] + cen[k].y * perp[1])
            n = len(order)
            pm = mx_ * perp[0] + my_ * perp[1]
            layer = pcbnew.F_Cu if small[0].IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
            dls = {}
            for rank, k in enumerate(order):
                c = cen[k]
                cur = c.x * perp[0] + c.y * perp[1]
                dls[k] = pm + (rank - (n - 1) / 2) * 1.25 - cur
            for rank, k in enumerate(order):
                self.fanned.add((fp.GetReference(), small[k].GetNumber()))
                c = cen[k]
                dl = dls[k]
                # pins with a larger lateral move turn first (no parallel diagonals too close)
                outer = sum(1 for kk in dls if dls[kk] * dl > 0 and abs(dls[kk]) > abs(dl))
                s0 = plen / 2 + 0.3 + 0.3 * outer
                p0 = (c.x, c.y)
                p1 = (c.x + d[0] * s0, c.y + d[1] * s0)
                p2 = (p1[0] + perp[0] * dl + d[0] * abs(dl), p1[1] + perp[1] * dl + d[1] * abs(dl))
                p3 = (p2[0] + d[0] * 0.5, p2[1] + d[1] * 0.5)
                net = small[k].GetNetCode()
                for a_, b_ in ((p0, p1), (p1, p2), (p2, p3)):
                    if abs(a_[0] - b_[0]) + abs(a_[1] - b_[1]) < 1e-6:
                        continue
                    t = pcbnew.PCB_TRACK(self.board)
                    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(float(a_[0])), pcbnew.FromMM(float(a_[1]))))
                    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(float(b_[0])), pcbnew.FromMM(float(b_[1]))))
                    t.SetWidth(pcbnew.FromMM(0.2))
                    t.SetLayer(layer)
                    t.SetNet(self.board.FindNet(net))
                    self.board.Add(t)
                stubs.append((net, 0 if layer == pcbnew.F_Cu else 1, LineString([p0, p1, p2, p3]), p3))
        return stubs

    def _build(self):
        g = self.g
        stubs = self.fanout()
        outline = board_outline(self.board)
        self.outline = outline
        # outside / near edge -> blocked on both layers
        inner = outline.buffer(-EDGE_INFL)
        (i0, i1, j0, j1), m = g.mask(inner, 0)
        allowed = np.zeros((g.ny, g.nx), dtype=bool)
        allowed[i0:i1, j0:j1] = m
        g.own[:, ~allowed] = -1
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                net = pad.GetNetCode()
                attr = pad.GetAttribute()
                if pad.GetDrillSize().x > 0:
                    g.claim(0, hole_shape(pad), HOLE_INFL, -1 if attr == pcbnew.PAD_ATTRIB_NPTH else net)
                    g.claim(1, hole_shape(pad), HOLE_INFL, -1 if attr == pcbnew.PAD_ATTRIB_NPTH else net)
                if attr == pcbnew.PAD_ATTRIB_NPTH:
                    continue
                shp = pad_shape(pad)
                layers = []
                if pad.IsOnLayer(pcbnew.F_Cu):
                    layers.append(0)
                if pad.IsOnLayer(pcbnew.B_Cu):
                    layers.append(1)
                for l in layers:
                    g.claim(l, shp, PAD_INFL, net if net > 0 else -1)
                if net > 0 and (fp.GetReference(), pad.GetNumber()) not in self.fanned:
                    self.pads.setdefault(net, []).append((layers, shp, pad))
        for net, l, line, end in stubs:
            g.claim(l, line.buffer(0.1), PAD_INFL, net)
            self.pads.setdefault(net, []).append(([l], Point(end).buffer(0.13), None))
        # pad cores last so they are never blocked by neighbours' inflation
        for net, lst in self.pads.items():
            for layers, shp, pad in lst:
                for l in layers:
                    g.set_core(l, shp, net)

    # ------------------------------------------------------------------
    def astar(self, net, sources, targets, bbox):
        g = self.g
        own = g.own
        i0, i1, j0, j1 = bbox
        tset = targets
        # heuristic: distance to nearest target (use bbox of targets centre)
        tl = np.array([(i, j) for (_, i, j) in tset])
        ti, tj = tl[:, 0], tl[:, 1]
        tmin_i, tmax_i, tmin_j, tmax_j = ti.min(), ti.max(), tj.min(), tj.max()

        def h(i, j):
            di = 0 if tmin_i <= i <= tmax_i else min(abs(i - tmin_i), abs(i - tmax_i))
            dj = 0 if tmin_j <= j <= tmax_j else min(abs(j - tmin_j), abs(j - tmax_j))
            return max(di, dj) + (DIAG - 1) * min(di, dj)

        openh = []
        best = {}
        prev = {}
        for s in sources:
            best[s] = 0.0
            heapq.heappush(openh, (h(s[1], s[2]), 0.0, s))
            prev[s] = None
        moves = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
                 (-1, -1, DIAG), (-1, 1, DIAG), (1, -1, DIAG), (1, 1, DIAG)]
        n_exp = 0
        while openh:
            f, c, s = heapq.heappop(openh)
            if c > best.get(s, 1e18):
                continue
            if s in tset:
                path = []
                while s is not None:
                    path.append(s)
                    s = prev[s]
                return path[::-1]
            n_exp += 1
            if n_exp > 600000:
                return None
            l, i, j = s
            pd = prev[s]
            for di, dj, w in moves:
                ni, nj = i + di, j + dj
                if not (i0 <= ni < i1 and j0 <= nj < j1):
                    continue
                o = own[l, ni, nj]
                if o != 0 and o != net:
                    continue
                if di and dj:  # no corner cutting
                    o1 = own[l, i, nj]
                    o2 = own[l, ni, j]
                    if (o1 != 0 and o1 != net) or (o2 != 0 and o2 != net):
                        continue
                nc = c + w
                # small bend penalty for tidy traces
                if pd is not None and pd[0] == l and (i - pd[1], j - pd[2]) != (di, dj):
                    nc += 0.3
                ns = (l, ni, nj)
                if nc < best.get(ns, 1e18):
                    best[ns] = nc
                    prev[ns] = s
                    heapq.heappush(openh, (nc + h(ni, nj), nc, ns))
            # via
            ol = 1 - l
            if self.via_ok(net, i, j):
                ns = (ol, i, j)
                nc = c + VIA_COST
                if nc < best.get(ns, 1e18):
                    best[ns] = nc
                    prev[ns] = s
                    heapq.heappush(openh, (nc + h(i, j), nc, ns))
        return None

    def via_ok(self, net, i, j):
        own = self.g.own
        r = 2
        if i - r < 0 or j - r < 0 or i + r >= self.g.ny or j + r >= self.g.nx:
            return False
        for l in (0, 1):
            sub = own[l, i - r:i + r + 1, j - r:j + r + 1]
            if np.any((sub != 0) & (sub != net)):
                return False
        # don't drill through pad copper of the same net on smd-only pads
        return True

    # ------------------------------------------------------------------
    def pad_cells(self, net, idx):
        layers, shp, pad = self.pads[net][idx]
        g = self.g
        out = set()
        (i0, i1, j0, j1), m = g.mask(shp, 0)
        ii, jj = np.nonzero(m)
        for l in layers:
            for a, b in zip(ii, jj):
                if g.core[l, i0 + a, j0 + b] == net:
                    out.add((l, int(i0 + a), int(j0 + b)))
        if not out:
            c = shp.centroid
            i, j = g.ij(c.x, c.y)
            for l in layers:
                out.add((l, i, j))
        return out

    def commit(self, net, path):
        g = self.g
        pts = []
        for k, (l, i, j) in enumerate(path):
            pts.append((l, i, j))
        # tracks
        by_layer = {}
        for (l, i, j) in path:
            by_layer.setdefault(l, []).append(g.xy(i, j))
        for k in range(len(path) - 1):
            a, b = path[k], path[k + 1]
            if a[0] != b[0]:
                x, y = g.xy(a[1], a[2])
                for l in (0, 1):
                    g.claim(l, Point(x, y), VIA_KEEP, net)
                self.vias.setdefault(net, []).append((x, y))
            else:
                pa, pb = g.xy(a[1], a[2]), g.xy(b[1], b[2])
                g.claim(a[0], LineString([pa, pb]), TRACK_KEEP, net)
        self.paths.setdefault(net, []).append(path)
        # mark the path itself as core so later branches can attach anywhere
        for (l, i, j) in path:
            g.core[l, i, j] = net

    def route_net(self, net):
        pads = self.pads[net]
        if len(pads) < 2:
            return True
        g = self.g
        cells = [self.pad_cells(net, k) for k in range(len(pads))]
        centers = [p[1].centroid for p in pads]
        done = {0}
        tree = set(cells[0])
        ok = True
        while len(done) < len(pads):
            # nearest pad to the tree
            cand = min((k for k in range(len(pads)) if k not in done),
                       key=lambda k: min(centers[k].distance(centers[d]) for d in done))
            # bbox
            tpts = [g.xy(i, j) for (_, i, j) in tree] + [(centers[cand].x, centers[cand].y)]
            xs = [p[0] for p in tpts]
            ys = [p[1] for p in tpts]
            path = None
            for margin in (6, 20, 400):
                gb = box(min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
                i0, i1, j0, j1 = g.window(gb, 0)
                # restrict target set to cells near the candidate to keep A* fast
                path = self.astar(net, list(cells[cand]), tree, (i0, i1, j0, j1))
                if path:
                    break
            if path is None:
                ok = False
                done.add(cand)
                continue
            self.commit(net, path)
            tree |= set(path) | cells[cand]
            done.add(cand)
        return ok

    def write(self, board):
        g = self.g
        for net, paths in self.paths.items():
            ni = board.FindNet(net)
            for path in paths:
                # merge collinear runs
                k = 0
                while k < len(path) - 1:
                    a = path[k]
                    if path[k + 1][0] != a[0]:
                        k += 1
                        continue
                    d = (path[k + 1][1] - a[1], path[k + 1][2] - a[2])
                    m = k + 1
                    while (m + 1 < len(path) and path[m + 1][0] == a[0]
                           and (path[m + 1][1] - path[m][1], path[m + 1][2] - path[m][2]) == d):
                        m += 1
                    t = pcbnew.PCB_TRACK(board)
                    xa, ya = g.xy(a[1], a[2])
                    xb, yb = g.xy(path[m][1], path[m][2])
                    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(float(xa)), pcbnew.FromMM(float(ya))))
                    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(float(xb)), pcbnew.FromMM(float(yb))))
                    t.SetWidth(pcbnew.FromMM(TRACK_W))
                    t.SetLayer(pcbnew.F_Cu if a[0] == 0 else pcbnew.B_Cu)
                    t.SetNet(ni)
                    board.Add(t)
                    k = m
        for net, vl in self.vias.items():
            ni = board.FindNet(net)
            for (x, y) in vl:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(float(x)), pcbnew.FromMM(float(y))))
                v.SetWidth(pcbnew.FromMM(VIA_D))
                v.SetDrill(pcbnew.FromMM(VIA_DRILL))
                v.SetNet(ni)
                board.Add(v)


def net_order(board, router, priority):
    nets = list(router.pads.keys())

    def key(n):
        name = board.FindNet(n).GetNetname()
        span = unary_union([p[1] for p in router.pads[n]]).bounds
        length = (span[2] - span[0]) + (span[3] - span[1])
        return (priority.get(n, 1), -length if "GND" in name else length)
    return sorted(nets, key=key)


def main(src, dst, passes=4):
    t0 = time.time()
    priority = {}
    for p in range(passes):
        board = pcbnew.LoadBoard(src)
        r = Router(board)
        order = net_order(board, r, priority)
        failed = []
        for n in order:
            if not r.route_net(n):
                failed.append(n)
        names = [board.FindNet(n).GetNetname() for n in failed]
        print(f"pass {p}: failed {len(failed)} {names}  ({time.time() - t0:.0f}s)", flush=True)
        if not failed or p == passes - 1:
            r.write(board)
            board.Save(dst)
            return failed
        for n in failed:
            priority[n] = priority.get(n, 1) - 1


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
