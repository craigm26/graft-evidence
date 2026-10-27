"""Score the Ubuntu replay: plain 3-way merge vs Graft's routing vs what Ubuntu's merger shipped, plus a token-cost
estimate for the conflicts Graft hands to agents.

usage: python3 -I ubuntu/score.py data/ubuntu/replay.jsonl > data/ubuntu/ubuntu-score.json (also writes replay-routed.jsonl)
"""
import json, sys
from collections import Counter, defaultdict

# Cost model for one conflicted file (all inputs stated, nothing measured from a live agent):
#   one rewrite attempt: input  = 3 x file tokens (base, Ubuntu's, Debian's) + 5,000 (instructions, tests, notes)
#                        output = 2 x Ubuntu's delta tokens + 2,000 (thinking and explanation)
#   three agents race (Claude Sonnet 5.5, $2 / $10 per million tokens)
#   one judge call (Claude Opus 5.5, $4 / $20): input 3 x delta + 2,000, output 500
SONNET = (2.0, 10.0)
OPUS = (4.0, 20.0)
RACE = 3


def cost(r):
    f, d = r["file_tokens"], r["ubuntu_delta_tokens"]
    ai, ao = 3 * f + 5000, 2 * d + 2000
    ji, jo = 3 * d + 2000, 500
    return RACE * (ai * SONNET[0] + ao * SONNET[1]) / 1e6 + (ji * OPUS[0] + jo * OPUS[1]) / 1e6


rows = [json.loads(l) for l in open(sys.argv[1])]
files = [r for r in rows if "file" in r]
errors = [r for r in rows if "error" in r]
skipped = [r for r in rows if "skipped" in r]

for r in files:
    r["control"] = {"absorbed": "drop", "clean": "carry", "conflict": "person"}[r["machine"]]
    touched = r["debian_touched"] or r.get("source_touched", False)
    r["graft"] = ("propose-drop" if r["machine"] == "absorbed" else
                  "race" if r["machine"] == "conflict" else
                  "auto" if not touched else "confirm")
    r["right_alone"] = r["human"] == "kept"  # what a machine shipped alone equals what Ubuntu shipped

# debian/patches/series follows the patches: when anything else in the merge needs a person, so does it.
groups = defaultdict(list)
for r in files:
    groups[(r["pkg"], r["merge"])].append(r)
for rs in groups.values():
    busy = any(x["graft"] != "auto" for x in rs if not x.get("series"))
    for r in rs:
        if r.get("series") and r["graft"] == "auto" and busy:
            r["graft"] = "confirm"

# Earned auto-merge: a file carried right in the two previous merges of its package is carried without asking.
by_pkg = defaultdict(list)
for r in files:
    by_pkg[r["pkg"]].append(r)
for pkg, rs in by_pkg.items():
    order = []
    for r in rs:
        if r["merge"] not in order:
            order.append(r["merge"])
    streak = defaultdict(int)
    for m in order:
        cur = [r for r in rs if r["merge"] == m]
        for r in cur:
            r["granted"] = r["graft"] == "confirm" and streak[r["file"]] >= 2
        for r in cur:
            ok = r["graft"] in ("auto", "confirm") and r["right_alone"]
            streak[r["file"]] = streak[r["file"]] + 1 if ok else 0

n = len(files)
ctl_wrong = [r for r in files if r["control"] in ("carry", "drop") and not r["right_alone"]]
g_wrong = [r for r in files if (r["graft"] == "auto" or r.get("granted")) and not r["right_alone"]]
races = [r for r in files if r["graft"] == "race"]
merges = {(r["pkg"], r["merge"]) for r in files}
race_cost = sum(cost(r) for r in races)

out = {
    "packages": len(by_pkg), "merges": len(merges), "files": n,
    "errors": len(errors), "skipped": [(r["pkg"], r["merge"], r["skipped"]) for r in skipped],
    "machine": Counter(r["machine"] for r in files),
    "human": Counter(r["human"] for r in files),
    "graft": Counter(r["graft"] for r in files),
    "debian_touched": sum(r["debian_touched"] for r in files),
    "control_person": sum(r["control"] == "person" for r in files),
    "control_wrong": len(ctl_wrong),
    "control_wrong_by": Counter(r["machine"] + "/" + r["human"] for r in ctl_wrong),
    "graft_person": sum(r["graft"] != "auto" for r in files),
    "graft_person_granted": sum(r["graft"] != "auto" and not r.get("granted") for r in files),
    "graft_wrong": len(g_wrong),
    "graft_wrong_examples": [(r["pkg"], r["merge"], r["file"], r["human"]) for r in g_wrong[:12]],
    "confirm_right": sum(r["graft"] == "confirm" and r["right_alone"] for r in files),
    "conflicts_ubuntu_dropped": sum(r["graft"] == "race" and r["human"] == "dropped" for r in files),
    "race_cost_usd": round(race_cost, 2),
    "race_cost_per_conflict": round(race_cost / max(1, len(races)), 3),
    "race_cost_per_merge": round(race_cost / max(1, len(merges)), 3),
    "per_package": {p: {"merges": len({r["merge"] for r in rs}), "files": len(rs),
                        "conflicts": sum(r["machine"] == "conflict" for r in rs),
                        "control_wrong": sum(r in ctl_wrong for r in rs),
                        "graft_wrong": sum(r in g_wrong for r in rs),
                        "graft_person": sum(r["graft"] != "auto" and not r.get("granted") for r in rs)}
                    for p, rs in sorted(by_pkg.items())},
}
with open(sys.argv[1].replace(".jsonl", "-routed.jsonl"), "w") as f:
    for r in files:
        f.write(json.dumps(r) + "\n")
json.dump(out, sys.stdout, indent=1)
