"""Write Ubuntu's stated reasons into each rewrite case: every changelog entry in Ubuntu's upload (L) above the
Debian upload it was based on (B), whole. The first run of the rewrites cut these to header lines (a bug).

usage: python3 -I ubuntu/case_reasons.py data/ubuntu/merges.json <work> data/ubuntu/rewrites
"""
import json, os, re, subprocess, sys

M = json.load(open(sys.argv[1]))
WORK, D = os.path.abspath(sys.argv[2]), sys.argv[3]


def unescape(t):
    return t.replace("%", ":").replace("_", "~")


for x in json.load(open(os.path.join(D, "index.json"))):
    m = next(y for y in M[x["pkg"]]["merges"][-3:] if y["label"] == x["merge"])
    text = subprocess.run(["git", "-C", os.path.join(WORK, x["pkg"] + ".git"), "show", f"import/{m['L']}:debian/changelog"],
                          capture_output=True, text=True, check=True).stdout
    base = unescape(m["B"])
    entries, cur = [], []
    for line in text.splitlines():
        h = re.match(r"^\S+ \(([^)]+)\)", line)
        if h:
            if h.group(1) == base:
                break
            if cur:
                entries.append("\n".join(cur))
            cur = [line]
        elif cur:
            cur.append(line)
    if cur:
        entries.append("\n".join(cur))
    out = "\n\n".join(e.rstrip() for e in entries)
    open(os.path.join(D, "cases", x["id"], "ubuntu-changelog.txt"), "w").write(out[:20000] + "\n")
    print(x["id"], x["pkg"], len(entries), "entries", len(out), "chars")
