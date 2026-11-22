"""Minimal S-expression parser/writer for KiCad files."""
import re

_tok = re.compile(r'\s*(?:(\()|(\))|("(?:[^"\\]|\\.)*")|([^\s()"]+))')


class Sym(str):
    """Unquoted atom."""


def parse(text):
    stack = [[]]
    pos = 0
    n = len(text)
    while pos < n:
        m = _tok.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                break
            raise ValueError("parse error at %d" % pos)
        pos = m.end()
        if m.group(1):
            stack.append([])
        elif m.group(2):
            e = stack.pop()
            stack[-1].append(e)
        elif m.group(3) is not None:
            s = m.group(3)[1:-1]
            stack[-1].append(s.replace('\\"', '"').replace('\\\\', '\\'))
        else:
            stack[-1].append(Sym(m.group(4)))
    return stack[0][0]


def q(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def dump(e, ind=0):
    if isinstance(e, list):
        if all(not isinstance(x, list) for x in e):
            return "(" + " ".join(dump(x) for x in e) + ")"
        out = "("
        first = True
        for x in e:
            if isinstance(x, list):
                out += "\n" + "  " * (ind + 1) + dump(x, ind + 1)
            else:
                out += ("" if first else " ") + dump(x)
            first = False
        return out + ")"
    if isinstance(e, Sym):
        return str(e)
    if isinstance(e, bool):
        return "yes" if e else "no"
    if isinstance(e, (int, float)):
        return fmtnum(e)
    return q(e)


def fmtnum(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def find(e, key):
    for x in e:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


def findall(e, key):
    return [x for x in e if isinstance(x, list) and x and x[0] == key]
