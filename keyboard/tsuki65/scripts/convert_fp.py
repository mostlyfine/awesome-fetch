"""Convert KiCad 8/9 footprints (.kicad_mod) to KiCad 7 format."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from sexpr import parse, dump, Sym, find

DROP = {"uuid", "generator_version", "embedded_fonts", "teardrops", "unlocked",
        "tstamp", "duplicate_pad_numbers_are_jumpers", "tenting"}


def conv(e):
    if not isinstance(e, list):
        return e
    if e and e[0] == "property":
        name = e[1]
        if name not in ("Reference", "Value"):
            return None
        kind = Sym("reference" if name == "Reference" else "value")
        out = [Sym("fp_text"), kind, e[2]]
        hidden = False
        rest = []
        for x in e[3:]:
            if isinstance(x, list) and x[0] in DROP:
                continue
            if isinstance(x, list) and x[0] == "hide":
                hidden = len(x) < 2 or x[1] == "yes"
                continue
            c = conv(x)
            if c is not None:
                rest.append(c)
        at = [r for r in rest if isinstance(r, list) and r[0] == "at"]
        layer = [r for r in rest if isinstance(r, list) and r[0] == "layer"]
        others = [r for r in rest if r not in at and r not in layer]
        out += at + layer + ([Sym("hide")] if hidden else []) + others
        return out
    out = []
    for x in e:
        if isinstance(x, list):
            if x and x[0] in DROP:
                continue
            if x and x[0] in ("bold", "italic", "hide") and len(x) == 2:
                if x[1] == "yes":
                    out.append(Sym(x[0]))
                continue
            if x and x[0] in ("remove_unused_layers", "keep_end_layers") and len(x) == 2:
                if x[1] == "yes":
                    out.append([Sym(x[0])])
                continue
            if x and x[0] == "fill" and len(x) == 2 and x[1] in ("yes", "no"):
                out.append([Sym("fill"), Sym("solid" if x[1] == "yes" else "none")])
                continue
            c = conv(x)
            if c is not None:
                out.append(c)
        else:
            out.append(x)
    if out and out[0] == "version":
        out = [Sym("version"), Sym("20221018")]
    if out and out[0] == "fp_text" and out[1] in ("user",):
        pass
    return out


def main(src, dst):
    e = parse(open(src).read())
    e = conv(e)
    open(dst, "w").write(dump(e) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
