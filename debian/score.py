"""Score the control (git rebase + rerere) and Graft's routing against what the maintainers actually did.

usage: python3 -I debian/score.py data/debian/curl.jsonl data/debian/openssh.jsonl > data/debian/data.json
"""
import json, sys
from collections import Counter, defaultdict


def control(r):
    return {"clean": "carry", "empty": "drop", "conflict": "person", "no-commit": "person"}[r["rebase"]]


def graft(r):
    # Absorbed upstream: propose dropping it; a person confirms.
    if r["rebase"] == "empty" or r["apply"] == "absorbed":
        return "propose-drop"
    # Upstream never touched these files and the change applies byte for byte: nothing to decide.
    if r["rebase"] == "clean" and r["apply"] == "exact" and not r["touched"]:
        return "auto"
    # Applies, but upstream changed the same files: checks run, then one click for a person.
    if r["rebase"] == "clean":
        return "confirm"
    return "race"


def right(truth, call):
    """Was a call made without a person right? Only 'carry' and 'drop' are calls made alone."""
    if call == "carry":
        return truth in ("kept", "refreshed")
    if call == "drop":
        return truth == "dropped"
    return None


out = {"packages": {}}
for path in sys.argv[1:]:
    name = path.split("/")[-1].split(".")[0]
    rows = [json.loads(l) for l in open(path)]
    patches = [r for r in rows if "patch" in r]
    bumps = [r for r in rows if "added" in r]
    for r in patches:
        r["control"] = control(r)
        r["graft"] = graft(r)
    silent_control = [r for r in patches if right(r["human"], r["control"]) is False]
    silent_graft = [r for r in patches if r["graft"] == "auto" and r["human"] not in ("kept", "refreshed")]
    out["packages"][name] = {
        "bumps": bumps,
        "rows": patches,
        "n": len(patches),
        "human": Counter(r["human"] for r in patches),
        "apply": Counter(r["apply"] for r in patches),
        "rebase": Counter(r["rebase"] for r in patches),
        "graft": Counter(r["graft"] for r in patches),
        "control_person": sum(r["control"] == "person" for r in patches),
        "control_silent_wrong": [(r["bump"], r["patch"], r["human"]) for r in silent_control],
        "graft_person": sum(r["graft"] != "auto" for r in patches),
        "graft_silent_wrong": [(r["bump"], r["patch"], r["human"]) for r in silent_graft],
        "fuzz_reapplies_absorbed": [(r["bump"], r["patch"]) for r in patches if r["apply"] == "fuzz" and r["rebase"] == "empty"],
        "forwarded": Counter(("upstream" if (r["forwarded"] or "").lower().startswith(("yes", "http")) else (r["forwarded"] or "unset").lower()) for r in patches),
    }
# Earned auto-merge: a change carried right in the two previous releases is carried without asking.
for d in out["packages"].values():
    streak = defaultdict(int)
    for b in [x["bump"] for x in d["bumps"]]:
        rows = [r for r in d["rows"] if r["bump"] == b]
        for r in rows:
            r["granted"] = r["graft"] == "confirm" and streak[r["patch"]] >= 2
        for r in rows:
            ok = r["graft"] in ("auto", "confirm") and r["human"] in ("kept", "refreshed")
            streak[r["patch"]] = streak[r["patch"]] + 1 if ok else 0
    g = [r for r in d["rows"] if r["granted"]]
    d["grant_auto"] = len(g)
    d["grant_wrong"] = [(r["bump"], r["patch"], r["human"]) for r in g if r["human"] not in ("kept", "refreshed")]
    d["graft_person_granted"] = d["graft_person"] - len(g)
json.dump(out, sys.stdout, indent=1)
