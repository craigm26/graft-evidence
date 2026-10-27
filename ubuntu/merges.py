"""Find Ubuntu's merges with Debian from git-ubuntu import tags, and pick the packages to replay.

A merge: the first Ubuntu upload on a new Debian base, after Ubuntu uploads on an older base.
usage: python3 -I ubuntu/merges.py data/ubuntu/tags.json > data/ubuntu/merges.json
"""
import json, re, sys
from functools import cmp_to_key


def order(c):
    if c == "~": return -1
    if c.isalpha(): return ord(c)
    return ord(c) + 256 if c else 0


def cmp_part(a, b):
    while a or b:
        na = re.match(r"^\D*", a).group(); nb = re.match(r"^\D*", b).group()
        for i in range(max(len(na), len(nb))):
            ca = na[i] if i < len(na) else ""; cb = nb[i] if i < len(nb) else ""
            if order(ca) != order(cb): return order(ca) - order(cb)
        a, b = a[len(na):], b[len(nb):]
        da = re.match(r"^\d*", a).group(); db = re.match(r"^\d*", b).group()
        if int(da or 0) != int(db or 0): return int(da or 0) - int(db or 0)
        a, b = a[len(da):], b[len(db):]
    return 0


def split(v):
    e, _, rest = v.rpartition(":") if ":" in v else ("0", "", v)
    up, _, rev = rest.rpartition("-") if "-" in rest else (rest, "", "")
    return int(e or 0), up, rev


def vcmp(a, b):
    ea, ua, ra = split(a); eb, ub, rb = split(b)
    return (ea - eb) or cmp_part(ua, ub) or cmp_part(ra, rb)


def unescape(t):
    return t.replace("%", ":").replace("_", "~").replace(".#", ".")


def base(v):
    m = re.match(r"^(.*-[^-]*?)ubuntu\d.*$", v)
    if not m: return None
    b = m.group(1)
    return None if b.endswith("-0") else b


tags = json.load(open(sys.argv[1]))
out = {}
for pkg, ts in tags.items():
    vs = {unescape(t): t for t in ts}
    deb = {v for v in vs if "ubuntu" not in v and "build" not in v}
    ub = sorted((v for v in vs if base(v)), key=cmp_to_key(vcmp))
    merges, prev = [], None
    for v in ub:
        b = base(v)
        if prev and b != base(prev) and vcmp(b, base(prev)) > 0 and b in deb and base(prev) in deb:
            merges.append({"B": vs[base(prev)], "L": vs[prev], "R": vs[b], "H": vs[v], "label": f"{base(prev)} -> {b}"})
        prev = v
    out[pkg] = {"ubuntu_uploads": len(ub), "merges": merges}
json.dump(out, sys.stdout, indent=1)
