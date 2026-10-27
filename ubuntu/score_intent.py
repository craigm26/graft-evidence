"""Score Graft's routing with the intent rules from ubuntu/intent.py added.

  likely_absorbed  -> propose dropping it (a person confirms), even when it merges cleanly or conflicts
  check_reason     -> a person confirms instead of auto-carrying

usage: python3 -I ubuntu/score_intent.py data/ubuntu/replay-routed.jsonl data/ubuntu/intent.jsonl > data/ubuntu/intent-score.json
"""
import json, sys

R = [json.loads(l) for l in open(sys.argv[1])]
I = [json.loads(l) for l in open(sys.argv[2])]
assert len(R) == len(I) and all(r["file"] == i["file"] and r["merge"] == i["merge"] for r, i in zip(R, I))


def route(r, i):
    alone = r["graft"] == "auto" or r.get("granted")
    if i["likely_absorbed"] and r["graft"] != "propose-drop":
        return "propose-drop"
    if alone and i["check_reason"]:
        return "confirm"
    return "auto" if alone else r["graft"]


before_alone = [r for r in R if r["graft"] == "auto" or r.get("granted")]
rows = [dict(r, intent_route=route(r, i), **{k: i[k] for k in ("likely_absorbed", "check_reason")}) for r, i in zip(R, I)]
alone = [r for r in rows if r["intent_route"] == "auto"]
drops = [r for r in rows if r["intent_route"] == "propose-drop"]
conflict_drops = [r for r in rows if r["machine"] == "conflict" and r["human"] == "dropped"]
out = {
    "files": len(rows),
    "before": {"alone": len(before_alone), "alone_wrong": sum(r["human"] != "kept" for r in before_alone),
               "person": len(rows) - len(before_alone)},
    "after": {"alone": len(alone), "alone_wrong": sum(r["human"] != "kept" for r in alone), "person": len(rows) - len(alone)},
    "propose_drop": {"n": len(drops), "ubuntu_dropped": sum(r["human"] == "dropped" for r in drops),
                     "from_intent": sum(r["likely_absorbed"] for r in drops)},
    "ubuntu_drops": sum(r["human"] == "dropped" for r in rows),
    "ubuntu_drops_proposed": sum(r["human"] == "dropped" and r["intent_route"] == "propose-drop" for r in rows),
    "conflicts_dropped_by_ubuntu": len(conflict_drops),
    "of_those_proposed_by_intent": sum(r["likely_absorbed"] for r in conflict_drops),
}
json.dump(out, sys.stdout, indent=1)
