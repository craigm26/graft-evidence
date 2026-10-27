"""Replay Ubuntu's last 3 merges with Debian, file by file, for each chosen package.

For a merge, B = the old Debian base, L = the last Ubuntu upload on it, R = the new Debian upload,
H = the first Ubuntu upload on R (what Ubuntu's merger shipped). Every file Ubuntu changed (B..L, without
debian/changelog) is one change to carry. The machine merges it three ways (git merge-file, base B):
  absorbed  R already equals L for the file
  clean     the merge succeeds; its result is compared with H
  conflict  it does not
Ubuntu's outcome per file: kept (H equals the clean merge), dropped (H equals R), edited (anything else).

usage: python3 -I ubuntu/replay.py data/ubuntu/merges.json <work> <n-packages> [pkg,pkg] > data/ubuntu/replay.jsonl
"""
import hashlib, json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

M = json.load(open(sys.argv[1]))
WORK = os.path.abspath(sys.argv[2])
N = int(sys.argv[3])
SKIP = {"live-build"}  # one merge in 15 years; its Ubuntu line is a different program


def git(repo, *a, inp=None, check=True):
    r = subprocess.run(["git", "-C", repo, *a], input=inp, capture_output=True, timeout=1800)
    if check and r.returncode:
        raise RuntimeError(f"{repo}: git {' '.join(a[:3])}: {r.stderr.decode()[-300:]}")
    return r


def fetch(pkg, tags):
    repo = os.path.join(WORK, pkg + ".git")
    if not os.path.exists(repo):
        subprocess.run(["git", "init", "-q", "--bare", repo], check=True)
        git(repo, "remote", "add", "origin", f"https://git.launchpad.net/ubuntu/+source/{pkg}")
        git(repo, "config", "remote.origin.promisor", "true")
        git(repo, "config", "remote.origin.partialclonefilter", "blob:none")
    refspecs = [f"+refs/tags/import/{t}:refs/tags/import/{t}" for t in tags]
    git(repo, "fetch", "-q", "--no-tags", "--depth=1", "--filter=blob:none", "origin", *refspecs)
    return repo


def changed(repo, a, b):
    out = git(repo, "diff", "--no-renames", "--name-only", "-z", f"import/{a}", f"import/{b}").stdout.decode()
    return [p for p in out.split("\0") if p and p != "debian/changelog"]


def blobs(repo, tag, paths):
    """Content of each path at tag (None when absent), fetched in one batch."""
    if not paths:
        return {}
    ls = git(repo, "ls-tree", "-z", f"import/{tag}", "--", *paths).stdout.decode()
    oid = {}
    for ent in ls.split("\0"):
        if ent:
            meta, path = ent.split("\t", 1)
            mode, kind, h = meta.split()
            if kind == "blob":
                oid[path] = h
    if oid:
        # Batch the missing blobs into one fetch.
        git(repo, "-c", "fetch.negotiationAlgorithm=noop", "fetch", "-q", "origin", "--no-tags",
            "--no-write-fetch-head", "--filter=blob:none", "--stdin", inp="\n".join(sorted(set(oid.values()))).encode(), check=False)
    out = {}
    for p in paths:
        out[p] = git(repo, "cat-file", "blob", oid[p]).stdout if p in oid else None
    return out


def merge3(l, b, r):
    """Three-way merge of one file: (result, ok)."""
    if l == r:
        return r, True
    if b == r:
        return l, True
    if b == l:
        return r, True
    if l is None or r is None or b is None:
        return None, False
    with tempfile.TemporaryDirectory() as d:
        fs = []
        for name, data in (("l", l), ("b", b), ("r", r)):
            f = os.path.join(d, name)
            open(f, "wb").write(data)
            fs.append(f)
        p = subprocess.run(["git", "merge-file", "-p", *fs], capture_output=True)
        return p.stdout, p.returncode == 0


def change_lines(data):
    """A patch's +/- lines, without headers or line numbers: equal means the same change, regenerated."""
    if data is None:
        return None
    out = []
    for line in data.decode("utf-8", "replace").splitlines():
        if line[:1] in "+-" and not line.startswith(("+++", "---")):
            out.append(line.rstrip())
    return out


def targets(data):
    fs = set()
    if data is None:
        return fs
    for line in data.decode("utf-8", "replace").splitlines():
        if line.startswith(("+++ ", "--- ")):
            q = line[4:].split("\t")[0].strip()
            if q != "/dev/null" and "/" in q:
                fs.add(q.split("/", 1)[1])
    return fs


def series(data):
    if data is None:
        return None
    return [l.split("#")[0].strip() for l in data.decode("utf-8", "replace").splitlines() if l.split("#")[0].strip()]


def same(path, a, b):
    if a == b:
        return True
    if a is None or b is None:
        return False
    if path.startswith("debian/patches/") and path.endswith("/series") or path == "debian/patches/series":
        return series(a) == series(b)
    if path.startswith("debian/patches/"):
        return change_lines(a) == change_lines(b)
    return False


def tok(x):
    return 0 if x is None else len(x) // 4


def replay(pkg):
    ms = M[pkg]["merges"][-3:]
    tags = sorted({m[k] for m in ms for k in "BLRH"})
    try:
        repo = fetch(pkg, tags)
    except Exception as e:
        return [{"pkg": pkg, "error": str(e)[-300:]}]
    rows = []
    for m in ms:
        try:
            paths = changed(repo, m["B"], m["L"])
            if len(paths) > 400:  # an Ubuntu-only upstream snapshot, not a delta
                rows.append({"pkg": pkg, "merge": m["label"], "skipped": f"{len(paths)} files"})
                continue
            B, L, R, H = (blobs(repo, m[k], paths) for k in "BLRH")
            up = set(git(repo, "diff", "--no-renames", "--name-only", f"import/{m['B']}", f"import/{m['R']}").stdout.decode().split("\n"))
        except Exception as e:
            rows.append({"pkg": pkg, "merge": m["label"], "error": str(e)[-300:]})
            continue
        for p in paths:
            b, l, r, h = B[p], L[p], R[p], H[p]
            if l == r:
                machine, result = "absorbed", r
            else:
                result, ok = merge3(l, b, r)
                machine = "clean" if ok else "conflict"
            if same(p, h, r) and not same(p, l, r):
                human = "dropped"
            elif machine in ("clean", "absorbed") and same(p, h, result):
                human = "kept"
            else:
                human = "edited"
            rows.append({
                "pkg": pkg, "merge": m["label"], "file": p,
                "machine": machine, "human": human, "debian_touched": b != r,
                "source_touched": bool(targets(l) & up) if p.startswith("debian/patches/") else False,
                "series": p.endswith("series"),
                "ubuntu_delta_tokens": tok(l) if b is None else abs(tok(l) - tok(b)) + 1,
                "file_tokens": max(tok(l), tok(r)),
                "delta_id": hashlib.sha256((l or b"") + b"\0" + (b or b"")).hexdigest()[:16] if machine == "conflict" else None,
            })
    return rows


def main():
    pkgs = sys.argv[4].split(",") if len(sys.argv) > 4 else [p for p, v in sorted(M.items(), key=lambda kv: -kv[1]["ubuntu_uploads"]) if len(v["merges"]) >= 3 and p not in SKIP][:N]
    os.makedirs(WORK, exist_ok=True)
    with ThreadPoolExecutor(6) as ex:
        for rows in ex.map(replay, pkgs):
            for row in rows:
                print(json.dumps(row), flush=True)


main()
