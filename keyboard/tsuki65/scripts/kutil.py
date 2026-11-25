"""Small helpers around the KiCad 7 pcbnew API."""
import os
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "pcb", "tsuki65.pretty")


def mm(v):
    return pcbnew.FromMM(float(v))


def V(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def new_board(thickness=1.6):
    b = pcbnew.BOARD()
    ds = b.GetDesignSettings()
    ds.SetBoardThickness(mm(thickness))
    ds.m_TrackMinWidth = mm(0.2)
    ds.m_MinClearance = mm(0.2)
    ds.m_ViasMinSize = mm(0.6)
    ds.m_MinThroughDrill = mm(0.3)
    ds.m_HoleClearance = mm(0.25)
    ds.m_CopperEdgeClearance = mm(0.3)
    nc = ds.m_NetSettings.m_DefaultNetClass
    nc.SetClearance(mm(0.2))
    nc.SetTrackWidth(mm(0.25))
    nc.SetViaDiameter(mm(0.6))
    nc.SetViaDrill(mm(0.3))
    return b


class Nets:
    def __init__(self, board):
        self.b = board
        self.m = {}

    def __call__(self, name):
        if name not in self.m:
            ni = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(ni)
            self.m[name] = ni
        return self.m[name]


def place(board, name, ref, x, y, rot=0.0, back=False, value=None):
    fp = pcbnew.FootprintLoad(LIB, name)
    if fp is None:
        raise RuntimeError("footprint not found: " + name)
    fp.SetFPID(pcbnew.LIB_ID("tsuki65", name))
    fp.SetReference(ref)
    if name.startswith("MountingHole") or name.startswith("Hole"):
        fp.Reference().SetVisible(False)
    if value:
        fp.SetValue(value)
    board.Add(fp)
    fp.SetPosition(V(x, y))
    if back:
        fp.Flip(fp.GetPosition(), False)
    fp.SetOrientationDegrees(rot)
    return fp


def set_pad_nets(fp, nets, mapping):
    for p in fp.Pads():
        n = p.GetNumber()
        if n in mapping and mapping[n] is not None:
            p.SetNet(nets(mapping[n]))


def seg(board, a, b, layer, width=0.1):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(V(*a))
    s.SetEnd(V(*b))
    s.SetLayer(layer)
    s.SetWidth(mm(width))
    board.Add(s)


def draw_polygon_edges(board, geom, layer=None):
    layer = pcbnew.Edge_Cuts if layer is None else layer
    polys = getattr(geom, "geoms", [geom])
    for p in polys:
        for ring in [p.exterior] + list(p.interiors):
            c = list(ring.coords)
            for a, b in zip(c, c[1:]):
                if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-4:
                    seg(board, a, b, layer)


def npth(board, ref, x, y, d):
    """Bare NPTH hole as a tiny footprint."""
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference(ref)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    fp.SetAttributes(pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_BOARD_ONLY)
    pad = pcbnew.PAD(fp)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(pcbnew.VECTOR2I(mm(d), mm(d)))
    pad.SetDrillSize(pcbnew.VECTOR2I(mm(d), mm(d)))
    pad.SetLayerSet(pad.UnplatedHoleMask())
    fp.Add(pad)
    board.Add(fp)
    fp.SetPosition(V(x, y))
    return fp


def text(board, s, x, y, size=1.5, layer=None, rot=0, mirror=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetPosition(V(x, y))
    t.SetLayer(pcbnew.F_SilkS if layer is None else layer)
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(size * 0.15))
    t.SetTextAngleDegrees(rot)
    t.SetMirrored(mirror)
    board.Add(t)
    return t


def thpads(board, ref, x, y, pads, drill=1.0, size=1.8):
    """Simple footprint with plated through-hole solder pads [(number, dx)]."""
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference(ref)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    fp.SetValue("battery leads")
    fp.SetAttributes(pcbnew.FP_THROUGH_HOLE | pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_EXCLUDE_FROM_BOM)
    for num, dx in pads:
        pad = pcbnew.PAD(fp)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetShape(pcbnew.PAD_SHAPE_RECT if num == "1" else pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetSize(pcbnew.VECTOR2I(mm(size), mm(size)))
        pad.SetDrillSize(pcbnew.VECTOR2I(mm(drill), mm(drill)))
        pad.SetLayerSet(pad.PTHMask())
        pad.SetNumber(num)
        pad.SetPos0(V(dx, 0))
        pad.SetPosition(V(x + dx, y))
        fp.Add(pad)
    fp.SetPosition(V(x, y))
    board.Add(fp)
    return fp
