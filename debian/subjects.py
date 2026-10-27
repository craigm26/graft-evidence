"""The Subject or Description line of each patch in a replay, for the demo.

usage: python3 -I debian/subjects.py <bare-repo> data/debian/curl.jsonl > data/debian/curl-subjects.json
"""
import json, re, subprocess, sys

repo, rows = sys.argv[1], [json.loads(l) for l in open(sys.argv[2])]
out = {}
for r in rows:
    if "patch" not in r or r["patch"] in out:
        continue
    t = subprocess.run(["git", "show", f"{r['from']}:debian/patches/{r['patch']}"], cwd=repo, capture_output=True, text=True).stdout
    m = re.search(r"^(?:Subject|Description):\s*(?:\[PATCH[^\]]*\]\s*)?(.+)$", t, re.M)
    out[r["patch"]] = m.group(1).strip() if m else r["patch"]
json.dump(out, sys.stdout, indent=1)
