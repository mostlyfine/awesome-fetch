"""Generate the (unrouted) main PCB panel: pcb/tsuki65-main-unrouted.kicad_pcb"""
import os
import sys

import pcbnew
from shapely import affinity

sys.path.insert(0, os.path.dirname(__file__))
import layout as L  # noqa: E402
import panel  # noqa: E402
from kutil import Nets, new_board, place, set_pad_nets, draw_polygon_edges, npth, text, mm  # noqa: E402

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


def make_xform(side, dy, mx):
    if side == "L":
        return lambda x, y: (x, y)
    return lambda x, y: (mx - x, y + dy)


def build_half(board, nets, side, T):
    n = lambda s: f"{side}_{s}"  # noqa: E731
    ref0 = 100 if side == "L" else 200

    def put(name, ref, x, y, rot=0, back=False, pads=None, value=None):
        X, Y = T(x, y)
        fp = place(board, name, ref, X, Y, rot, back, value)
        if name in LCSC:
            fp.SetValue(LCSC[name][0])
            fp.SetProperty("LCSC", LCSC[name][1])
        if pads:
            set_pad_nets(fp, nets, {k: (n(v) if v else None) for k, v in pads.items()})
        return fp

    # ---- keys -------------------------------------------------------------
    for i, k in enumerate(sorted(L.keys(), key=lambda k: (k["r"], k["c"]))):
        idx = ref0 + i + 1
        dk = f"D{idx}_K"
        sw = put("CHOC_V2_SOCKET_HANDSOLDERING", f"SW{idx}", k["x"], k["y"], 0, True,
                 {"1": f"COL{k['c']}", "2": dk})
        # diode NE of the switch centre (same relative place as torabo-tsuki LP);
        # x offset is not mirrored because the socket footprint is not mirrored.
        X, Y = T(k["x"], k["y"])
        d = place(board, "D_SOD-123", f"D{idx}", X + 3.6, Y - 3.2, 90, True)
        d.SetValue(LCSC["D_SOD-123"][0])
        d.SetProperty("LCSC", LCSC["D_SOD-123"][1])
        set_pad_nets(d, nets, {"1": n(dk), "2": n(f"ROW{k['r']}")})
        if k["tb"]:
            # FPC connector for the 14 mm sensor module (cable goes through the
            # switch centre hole).  North-west of the centre, clear of the
            # socket; contacts face west (into the gap between columns).
            j = place(board, "GT-F0501SR10-06S1101", f"J{ref0 + 1}", X - 4.3, Y - 5.8, 270, True)
            j.SetValue(LCSC["GT-F0501SR10-06S1101"][0])
            j.SetProperty("LCSC", LCSC["GT-F0501SR10-06S1101"][1])
            set_pad_nets(j, nets, {"1": n("GND"), "2": n("SCLK"), "3": n("SDIO"), "4": n("MOTION"),
                                   "5": n("CS"), "6": n("VCC"), "MP": n("GND")})

    # ---- controller block (torabo-tsuki LP geometry) ------------------------
    sgn = 1 if side == "L" else -1
    bx, by = L.O(-19, 0.4)
    X, Y = T(bx, by)
    u = place(board, "BLEMicroPro", f"U{ref0 + 1}", X, Y, 0, False)
    u.SetValue("BMP Boost")
    set_pad_nets(u, nets, {k: (n(v) if v else None) for k, v in BMP_PINS.items()})

    sx, sy = L.O(-19, 3.5)
    X, Y = T(sx, sy)
    s = place(board, "SW-SMD_K3-1280S-F1", f"SW{ref0}", X, Y, 90, True)
    s.SetValue(LCSC["SW-SMD_K3-1280S-F1"][0])
    s.SetProperty("LCSC", LCSC["SW-SMD_K3-1280S-F1"][1])
    if side == "L":
        set_pad_nets(s, nets, {"1": n("BATN"), "2": n("GND"), "3": n("BOOT")})
    else:
        set_pad_nets(s, nets, {"1": n("BOOT"), "2": n("GND"), "3": n("BATN")})

    X, Y = T(*L.O(0, 30.5))
    bt = place(board, "battery_holder", f"BT{ref0 + 1}", X, Y, -90, True)
    bt.SetValue("AA battery holder")
    set_pad_nets(bt, nets, {"1": n("BATT"), "2": n("BATN")})

    # relief holes at the battery notch corners (as torabo-tsuki LP)
    for dy_ in (2.0, 59.3):
        X, Y = T(*L.O(-8.5, dy_))
        npth(board, f"H{side}{dy_}", X, Y, 1.0)

    # cover screw hole (M2)
    X, Y = T(*L.O(-19, 36.3))
    place(board, "MountingHole_2.2mm_M2", f"H{ref0 + 50}", X, Y)

    # status LED + resistor (bottom side, near the lower edge of the cover)
    X, Y = T(*L.O(-12.0, 64.0))
    led = place(board, "LED_0603_1608Metric", f"LED{ref0 + 1}", X, Y, 0, True)
    led.SetValue(LCSC["LED_0603_1608Metric"][0])
    led.SetProperty("LCSC", LCSC["LED_0603_1608Metric"][1])
    set_pad_nets(led, nets, {"1": n("LEDK"), "2": n("LED")})
    X, Y = T(*L.O(-12.0, 61.8))
    r = place(board, "R_0402_1005Metric", f"R{ref0 + 1}", X, Y, 0, True)
    r.SetValue(LCSC["R_0402_1005Metric"][0])
    r.SetProperty("LCSC", LCSC["R_0402_1005Metric"][1])
    set_pad_nets(r, nets, {"1": n("LEDK"), "2": n("GND")})

    # spacer holes
    for i, h in enumerate(L.HOLES):
        X, Y = T(*h)
        place(board, "MountingHole_5mm", f"H{ref0 + 60 + i}", X, Y)

    # labels
    X, Y = T(*L.O(-19, 50))
    text(board, "tsuki65 " + ("LEFT" if side == "L" else "RIGHT"), X, Y, 1.2,
         pcbnew.B_SilkS, 0, True)
    X, Y = T(*L.O(-19, 46))
    text(board, "17mm / Choc V2 / 14mm TB", X, Y, 1.0, pcbnew.B_SilkS, 0, True)
    return sgn


def outlines():
    """Return (left, right, dy, mx) for the main PCB."""
    left = L.main_outline("L")
    mx = L.mirror_x()
    rm = affinity.scale(L.main_outline("R"), xfact=-1, yfact=1, origin=(mx / 2, 0))
    dy = panel.place_right(left, rm)
    right = affinity.translate(rm, 0, dy)
    return left, right, dy, mx


def main():
    board = new_board(1.6)
    nets = Nets(board)
    left, right, dy, mx = outlines()
    build_half(board, nets, "L", make_xform("L", dy, mx))
    build_half(board, nets, "R", make_xform("R", dy, mx))
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
