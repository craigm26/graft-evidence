"""Read each Ubuntu change's stated reason and turn it into routing signals.

For every file in the replay, from Ubuntu's last upload on the old base (L):
  upstream_fix      a debian/patches file whose DEP-3 header says it came from upstream (Origin: upstream or
                    backport, Applied-Upstream) or whose name or header names a CVE
  upstream_moved    the upstream version changed between the old and new Debian uploads
  temporary         Ubuntu's changelog lines that mention the file say the change is temporary (until, workaround,
                    temporarily, FTBFS, revert when, for now)
  mentioned         Ubuntu's changelog mentions the file at all
Graft's intent rules:
  likely_absorbed   upstream_fix and upstream_moved: upstream probably has it now, so propose dropping it
  check_reason      temporary: the reason may have gone away, so a person confirms instead of auto-carrying

usage: python3 -I ubuntu/intent.py data/ubuntu/merges.json <work> data/ubuntu/replay-routed.jsonl > data/ubuntu/intent.jsonl
"""
import json, os, re, subprocess, sys

M = json.load(open(sys.argv[1]))
WORK = os.path.abspath(sys.argv[2])
ROWS = [json.loads(l) for l in open(sys.argv[3])]

TEMP = re.compile(r"\b(until|workaround|work around|temporar\w*|ftbfs|revert (?:this )?(?:once|when)|for now|drop (?:this )?(?:once|when))\b", re.I)
CVE = re.compile(r"CVE-\d{4}-\d+", re.I)


def show(pkg, tag, path):
    r = subprocess.run(["git", "-C", os.path.join(WORK, pkg + ".git"), "show", f"import/{tag}:{path}"], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def upstream(v):
    v = v.replace("%", ":").replace("_", "~")
    v = v.split(":", 1)[-1]
    return v.rsplit("-", 1)[0]


def header(text):
    h = {}
    for line in text.splitlines():
        if line.startswith(("--- ", "diff ", "Index:", "===")):
            break
        m = re.match(r"^([A-Za-z-]+):\s*(.*)", line)
        if m:
            h.setdefault(m.group(1).lower(), m.group(2).strip())
    return h


def ubuntu_lines(changelog, pkg):
    """The changelog lines of every Ubuntu entry above the first Debian one."""
    out = []
    for block in changelog.split("\n -- "):
        head = block.strip().split("\n", 1)[0]
        if "ubuntu" not in head and head.startswith(pkg + " ("):
            break
        out.extend(l.strip() for l in block.split("\n")[1:] if l.strip())
    return out


cache = {}
for r in ROWS:
    m = next(x for x in M[r["pkg"]]["merges"][-3:] if x["label"] == r["merge"])
    key = (r["pkg"], m["L"])
    if key not in cache:
        cache[key] = ubuntu_lines(show(r["pkg"], m["L"], "debian/changelog") or "", r["pkg"])
    lines = cache[key]
    base = os.path.basename(r["file"])
    stem = re.sub(r"\.(patch|diff)$", "", base)
    # A changelog line mentions the file when it names it, or its stem for patches; continuation lines count too.
    mention = [l for l in lines if base in l or (r["file"].startswith("debian/patches/") and len(stem) > 6 and stem in l)]
    fix = False
    if r["file"].startswith("debian/patches/") and not r["file"].endswith("series"):
        text = show(r["pkg"], m["L"], r["file"]) or ""
        h = header(text)
        origin = (h.get("origin", "") + " " + h.get("applied-upstream", "")).lower()
        fix = ("upstream" in origin or "backport" in origin or "applied-upstream" in h
               or bool(CVE.search(base)) or bool(CVE.search(h.get("description", "") + h.get("subject", ""))))
    moved = upstream(m["B"]) != upstream(m["R"])
    temporary = any(TEMP.search(l) for l in mention)
    print(json.dumps({
        "pkg": r["pkg"], "merge": r["merge"], "file": r["file"],
        "upstream_fix": fix, "upstream_moved": moved, "temporary": temporary, "mentioned": bool(mention),
        "likely_absorbed": fix and moved, "check_reason": temporary,
    }))
