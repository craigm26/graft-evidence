"""Grade blind agent rewrites of Ubuntu merge conflicts against what Ubuntu's merger shipped.

Each case directory holds the old Debian file, Ubuntu's file and the new Debian file; the agent never saw answers/.
Per case:
  decision   the agent's keep or drop against Ubuntu's (drop = Ubuntu shipped the new Debian file as is)
  exact      the agent's file is byte for byte Ubuntu's
  same       equal once trailing whitespace and blank lines are ignored (for a series file: the same patch list)
  lines_off  lines in a diff between the agent's file and Ubuntu's, next to the same count for taking Debian's
             new file unchanged, the cheapest baseline

usage: python3 -I ubuntu/grade_rewrites.py <rewrite-dir> [<outputs subdir, default out>] > data/ubuntu/rewrites.json
"""
import difflib, json, os, sys

D = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "out"
index = json.load(open(os.path.join(D, "index.json")))


def read(p):
    return open(p, "rb").read().decode("utf-8", "replace") if os.path.exists(p) else ""


def norm(text, series):
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    if series:
        lines = [l.split("#")[0].strip() for l in lines if l.split("#")[0].strip()]
    return lines


def off(a, b):
    return sum(1 for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
               if l[:1] in "+-" and not l.startswith(("+++", "---")))


cases = []
for x in index:
    cid = x["id"]
    res = read(os.path.join(D, OUT, cid + ".result"))
    meta = json.load(open(os.path.join(D, OUT, cid + ".json")))
    ans = read(os.path.join(D, "answers", cid))
    new = read(os.path.join(D, "cases", cid, "debian-new"))
    series = x["file"].endswith("series")
    ubuntu_drop = x["human"] == "dropped"
    cases.append({
        "id": cid, "pkg": x["pkg"], "file": x["file"], "ubuntu": "drop" if ubuntu_drop else "keep",
        "agent": meta["decision"], "confidence": meta.get("confidence"),
        "decision_right": (meta["decision"] == "drop") == ubuntu_drop,
        "exact": res == ans, "same": norm(res, series) == norm(ans, series),
        "lines_off": off(res, ans), "lines_off_debian_new": off(new, ans),
    })
n = len(cases)
out = {
    "cases": n,
    "decision_right": sum(c["decision_right"] for c in cases),
    "exact": sum(c["exact"] for c in cases),
    "same": sum(c["same"] for c in cases),
    "closer_than_debian_new": sum(c["lines_off"] < c["lines_off_debian_new"] for c in cases),
    "lines_off_total": sum(c["lines_off"] for c in cases),
    "lines_off_debian_new_total": sum(c["lines_off_debian_new"] for c in cases),
    "by_ubuntu": {k: {"n": sum(c["ubuntu"] == k for c in cases),
                      "decision_right": sum(c["decision_right"] for c in cases if c["ubuntu"] == k),
                      "same": sum(c["same"] for c in cases if c["ubuntu"] == k)} for k in ("keep", "drop")},
    "detail": cases,
}
json.dump(out, sys.stdout, indent=1)
