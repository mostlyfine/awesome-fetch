"""Generate the (unrouted) main PCB panel: pcb/tsuki65-main-unrouted.kicad_pcb"""
import os
import sys

import pcbnew
from shapely import affinity

sys.path.insert(0, os.path.dirname(__file__))
import layout as L  # noqa: E402
import panel  # noqa: E402
from kutil import Nets, new_board, place, set_pad_nets, draw_polygon_edges, npth, text, thpads  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "pcb")

# BMP (BLE Micro Pro / BMP Boost) pin assignment, identical to torabo-tsuki LP
BMP_PINS = {
    "1": "GND", "2": "VCC", "3": "LED", "4": "GND", "5": None,
    "6": "SCLK", "7": "SDIO", "8": "MOTION", "9": "CS",
    "10": "COL0", "11": "COL2", "12": "COL4", "13": "COL6",
    "14": "COL5", "15": "COL3", "16": "COL1",
    "17": "ROW4", "18": "ROW3", "19": "ROW2", "20": "ROW1", "21": "ROW0",
    "22": None, "23": "BOOT", "24": "GND", "25": None, "26": "BATT",
}

# LCSC part numbers for JLCPCB assembly (written into footprint fields)
LCSC = {
    "CHOC_V2_SOCKET_HANDSOLDERING": ("Kailh CPG135001S30", "C5333465"),
    "D_SOD-123": ("1N4148W", "C81598"),
    "GT-F0501SR10-06S1101": ("GT-F0501SR10-06S1101", "C22380676"),
    "SW-SMD_K3-1280S-F1": ("K3-1280S-F1", "C92658"),
    "LED_0603_1608Metric": ("LED red 0603", "C2286"),
    "R_0402_1005Metric": ("1k 0402", "C11702"),
}


def make_xform(side, dx, dy):
    if side == "L":
        return lambda x, y: (x, y)
    return lambda x, y: (x + dx, y + dy)


def lcsc(fp, name):
    fp.SetValue(LCSC[name][0])
    fp.SetProperty("LCSC", LCSC[name][1])


def build_half(board, nets, side, T):
    n = lambda s: f"{side}_{s}"  # noqa: E731
    ref0 = 100 if side == "L" else 200

    # ---- keys -------------------------------------------------------------
    ks = [k for k in L.keys(side) if not k["tb"]]
    for i, k in enumerate(sorted(ks, key=lambda k: (k["r"], k["xv"]))):
        idx = ref0 + i + 1
        dk = f"D{idx}_K"
        X, Y = T(k["x"], k["y"])
        sw = place(board, "CHOC_V2_SOCKET_HANDSOLDERING", f"SW{idx}", X, Y, k["rot"], True)
        lcsc(sw, "CHOC_V2_SOCKET_HANDSOLDERING")
        set_pad_nets(sw, nets, {"1": n(f"COL{k['c']}"), "2": n(dk)})
        # diode NE of the switch centre (torabo-tsuki LP); SW when the socket is rotated
        if k["rot"] == 0:
            d = place(board, "D_SOD-123", f"D{idx}", X + 3.6, Y - 3.2, 90, True)
        else:
            d = place(board, "D_SOD-123", f"D{idx}", X - 3.6, Y + 3.2, 270, True)
        lcsc(d, "D_SOD-123")
        set_pad_nets(d, nets, {"1": n(dk), "2": n(f"ROW{k['r']}")})
    for k in L.keys(side):
        if not k["tb"]:
            continue
        # 14 mm trackball slot (maghold case in a 14 x 14 plate hole): no switch,
        # a 4.8 mm hole for the FFC and the FPC connector (contacts facing east).
        X, Y = T(k["x"], k["y"])
        npth(board, f"HTB{side}", X, Y, 4.8)
        j = place(board, "GT-F0501SR10-06S1101", f"J{ref0 + 1}", X + 4.3, Y - 5.8, 90, True)
        lcsc(j, "GT-F0501SR10-06S1101")
        set_pad_nets(j, nets, {"1": n("GND"), "2": n("SCLK"), "3": n("SDIO"), "4": n("MOTION"),
                               "5": n("CS"), "6": n("VCC"), "MP": n("GND")})

    # ---- controller block on the outer side ------------------------------------
    c = L.CTRL[side]
    X, Y = T(*c["bmp"])
    u = place(board, "BLEMicroPro", f"U{ref0 + 1}", X, Y, 0, False)
    u.SetValue("BMP Boost")
    set_pad_nets(u, nets, {k: (n(v) if v else None) for k, v in BMP_PINS.items()})

    X, Y = T(*c["sw"])
    s = place(board, "SW-SMD_K3-1280S-F1", f"SW{ref0}", X, Y, c["sw_rot"], True)
    lcsc(s, "SW-SMD_K3-1280S-F1")
    set_pad_nets(s, nets, {"1": n("BATN"), "2": n("GND"), "3": n("BOOT")})

    # battery: lead-wire AA holder under the bottom plate -> two solder pads
    X, Y = T(*c["bat"])
    bt = thpads(board, f"BT{ref0 + 1}", X, Y, [("1", -1.27), ("2", 1.27)])
    set_pad_nets(bt, nets, {"1": n("BATT"), "2": n("BATN")})
    text(board, "+", X - 1.27, Y - 2.0, 1.0, pcbnew.B_SilkS, 0, True)
    text(board, "-", X + 1.27, Y - 2.0, 1.0, pcbnew.B_SilkS, 0, True)
    text(board, "+", X - 1.27, Y - 2.0, 1.0, pcbnew.F_SilkS)
    text(board, "-", X + 1.27, Y - 2.0, 1.0, pcbnew.F_SilkS)

    X, Y = T(*c["led"])
    led = place(board, "LED_0603_1608Metric", f"LED{ref0 + 1}", X, Y, 0, True)
    lcsc(led, "LED_0603_1608Metric")
    set_pad_nets(led, nets, {"1": n("LEDK"), "2": n("LED")})
    X, Y = T(*c["res"])
    r = place(board, "R_0402_1005Metric", f"R{ref0 + 1}", X, Y, 0, True)
    lcsc(r, "R_0402_1005Metric")
    set_pad_nets(r, nets, {"1": n("LEDK"), "2": n("GND")})

    # spacer holes
    for i, h in enumerate(L.holes(side)):
        X, Y = T(*h)
        place(board, "MountingHole_5mm", f"H{ref0 + 60 + i}", X, Y)

    # label (bottom silk, between the BMP pin rows)
    bx, by = c["bmp"]
    X, Y = T(bx, by + 16)
    text(board, "tsuki65 " + ("LEFT" if side == "L" else "RIGHT"), X, Y, 1.2, pcbnew.B_SilkS, 90, True)


def outlines():
    """Return (left, right, dx, dy) for the main PCB (right half in panel coords)."""
    left = L.main_outline("L")
    right0 = L.main_outline("R")
    dx = left.bounds[0] - right0.bounds[0]
    rs = affinity.translate(right0, dx, 0)
    dy = panel.place_right(left, rs)
    return left, affinity.translate(rs, 0, dy), dx, dy


def main():
    board = new_board(1.6)
    nets = Nets(board)
    left, right, dx, dy = outlines()
    build_half(board, nets, "L", make_xform("L", dx, dy))
    build_half(board, nets, "R", make_xform("R", dx, dy))
    pnl, holes, tabs = panel.build(left, right)
    draw_polygon_edges(board, pnl)
    for i, p in enumerate(holes):
        npth(board, f"MB{i}", p.x, p.y, panel.HOLE_D)
    text(board, "tsuki65 main PCB  (JLCPCB: 2 layers, 1.6 mm)", pnl.bounds[0] + 30,
         pnl.bounds[1] + 2.5, 1.5, pcbnew.F_SilkS)
    out = os.path.join(OUT, "tsuki65-main-unrouted.kicad_pcb")
    board.Save(out)
    print("saved", out, "panel", [round(v, 1) for v in pnl.bounds], "tabs", len(tabs), "holes", len(holes))


if __name__ == "__main__":
    main()
