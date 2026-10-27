"""List git-ubuntu import tags for every package with an outstanding merge in Ubuntu main.

usage: python3 -I ubuntu/tags.py data/ubuntu/main.json > data/ubuntu/tags.json
(main.json is https://merges.ubuntu.com/main.json)
"""
import json, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
pkgs = sorted({m["source_package"] for m in json.load(open(sys.argv[1]))})
def tags(p):
    r = subprocess.run(["git", "ls-remote", "--tags", f"https://git.launchpad.net/ubuntu/+source/{p}"], capture_output=True, text=True, timeout=120)
    out = []
    for line in r.stdout.splitlines():
        sha, ref = line.split("\t")
        if ref.endswith("^{}"): continue
        m = re.match(r"refs/tags/import/(.+)$", ref)
        if m: out.append(m.group(1))
    return p, out
with ThreadPoolExecutor(10) as ex:
    res = dict(ex.map(tags, pkgs))
json.dump(res, sys.stdout)
print(sum(1 for v in res.values() if v), "with tags", file=sys.stderr)
