"""Replay a Debian package's patch stack across its last N upstream bumps.

For each bump (last Debian upload of upstream X -> last Debian upload of upstream Y):
  human     what the maintainers did to each patch: kept, refreshed (context only), edited, dropped
  apply     the old patch applied in series to upstream Y: exact, fuzz, absorbed (reverse applies), fail
  rebase    the control: git cherry-pick (3-way, rerere on) of the patch as a commit from X onto Y:
            clean, empty (absorbed), conflict
  touched   whether upstream X..Y changed any file the patch touches
Prints one JSON line per patch per bump.

usage: python3 -I debian/replay.py <bare-repo> <work-dir> <n-bumps> > data/debian/<pkg>.jsonl
"""
import json, os, re, subprocess, sys
from collections import OrderedDict

REPO, WORK, N = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), int(sys.argv[3])


def git(*a, cwd=None, check=True, inp=None):
    r = subprocess.run(["git", *a], cwd=cwd or REPO, input=inp, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()}")
    return r


def show(tag, path):
    r = git("show", f"{tag}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def series(tag):
    text = show(tag, "debian/patches/series") or ""
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.split()[0])
    return out


def upstream_of(deb_tag):
    v = deb_tag.split("/", 1)[1]
    v = v.split("%", 1)[-1]          # epoch, as DEP-14 escapes it
    return "upstream/" + v.rsplit("-", 1)[0]


def final_uploads():
    tags = git("tag").stdout.split()
    keep = [t for t in tags if t.startswith("debian/") and re.fullmatch(r"debian/(\d+%)?[\d.]+(p\d+)?-\d+", t)]
    by_up = OrderedDict()
    for t in sorted(keep, key=lambda t: git("log", "-1", "--format=%ct", t).stdout.strip()):
        by_up[upstream_of(t)] = t     # the last upload of each upstream wins
    ups = [u for u in by_up if git("rev-parse", "-q", "--verify", u + "^{commit}", check=False).returncode == 0]
    return [(u, by_up[u]) for u in ups]


def body(patch, level):
    """level 'full': the diff minus line numbers; 'change': only the +/- lines."""
    out, in_diff = [], False
    for line in patch.splitlines():
        if line.startswith(("--- ", "diff ")):
            in_diff = True
        if not in_diff or line.startswith(("index ", "diff ", "--- ", "+++ ")):
            continue
        if line.startswith("@@"):
            out.append(re.sub(r"@@ [^@]* @@", "@@", line) if level == "full" else "@@")
        elif level == "full" or line[:1] in "+-":
            out.append(line)
    return "\n".join(out)


def files_of(patch):
    fs = set()
    for line in patch.splitlines():
        m = re.match(r"^\+\+\+ (\S+)", line) or re.match(r"^--- (\S+)", line)
        if m and m.group(1) != "/dev/null":
            p = m.group(1)
            fs.add(p.split("/", 1)[1] if "/" in p else p)
    return sorted(fs)


def header(patch):
    h = {}
    for line in patch.splitlines():
        if line.startswith(("--- ", "diff ", "Index:")):
            break
        m = re.match(r"^([A-Za-z-]+):\s*(.*)", line)
        if m:
            h.setdefault(m.group(1).lower(), m.group(2).strip())
    return h


def human(name, old, new_tag, new_names, new_texts):
    if name not in new_names:
        nb = body(old, "change")
        for n in new_names:
            if body(new_texts[n], "change") == nb:
                return "kept", n           # renamed, same change
        return "dropped", None
    new = new_texts[name]
    if body(old, "full") == body(new, "full"):
        return "kept", name
    if body(old, "change") == body(new, "change"):
        return "refreshed", name
    return "edited", name


def worktree(path, ref):
    if os.path.exists(path):
        git("worktree", "remove", "--force", path, check=False)
    git("worktree", "add", "--detach", "--force", path, ref)


def try_apply(tree, patch):
    run = lambda *a: subprocess.run(a, cwd=tree, input=patch, capture_output=True, text=True)
    if run("git", "apply", "--check", "-p1").returncode == 0:
        run("git", "apply", "-p1")
        return "exact"
    if run("patch", "-p1", "-F2", "--dry-run", "--batch", "--silent").returncode == 0:
        r = run("patch", "-p1", "-F2", "--batch", "--silent")
        return "fuzz" if r.returncode == 0 else "fail"
    if run("git", "apply", "--check", "-R", "-p1").returncode == 0:
        return "absorbed"
    if run("patch", "-p1", "-R", "-F2", "--dry-run", "--batch", "--silent", "-f").returncode == 0:
        return "absorbed"
    return "fail"


def commit_all(tree, msg):
    git("add", "-A", cwd=tree)
    r = git("-c", "user.name=replay", "-c", "user.email=replay@invalid", "commit", "-q", "--allow-empty", "-m", msg, cwd=tree)
    return git("rev-parse", "HEAD", cwd=tree).stdout.strip()


def replay(old_up, old_deb, new_up, new_deb):
    old_names, new_names = series(old_deb), series(new_deb)
    old_texts = {n: show(old_deb, f"debian/patches/{n}") or "" for n in old_names}
    new_texts = {n: show(new_deb, f"debian/patches/{n}") or "" for n in new_names}
    changed = set(git("diff", "--name-only", old_up, new_up).stdout.split())

    # The stack as commits on upstream X: what a fork that keeps a branch would hold.
    base = os.path.join(WORK, "base")
    worktree(base, old_up)
    commits = {}
    for n in old_names:
        how = try_apply(base, old_texts[n])
        commits[n] = commit_all(base, n) if how in ("exact", "fuzz") else None

    # Mechanical: apply the old series to upstream Y, in order.
    mech = os.path.join(WORK, "mech")
    worktree(mech, new_up)
    apply = {n: try_apply(mech, old_texts[n]) for n in old_names}

    # Control: cherry-pick each commit onto Y with rerere, as `git rebase` would.
    ctl = os.path.join(WORK, "ctl")
    worktree(ctl, new_up)
    rebase = {}
    for n in old_names:
        c = commits[n]
        if not c:
            rebase[n] = "no-commit"
            continue
        r = git("-c", "rerere.enabled=true", "-c", "user.name=replay", "-c", "user.email=replay@invalid",
                "cherry-pick", c, cwd=ctl, check=False)
        if r.returncode == 0:
            rebase[n] = "clean"
        elif "empty" in (r.stdout + r.stderr):
            rebase[n] = "empty"
            git("cherry-pick", "--skip", cwd=ctl, check=False)
        else:
            rebase[n] = "conflict"
            git("cherry-pick", "--abort", cwd=ctl, check=False)

    for n in old_names:
        what, now = human(n, old_texts[n], new_deb, new_names, new_texts)
        fs = files_of(old_texts[n])
        h = header(old_texts[n])
        yield {
            "bump": f"{old_up.split('/',1)[1]} -> {new_up.split('/',1)[1]}",
            "from": old_deb, "to": new_deb, "patch": n, "renamed_to": now if now and now != n else None,
            "human": what, "apply": apply[n], "rebase": rebase[n],
            "files": fs, "touched": bool(set(fs) & changed),
            "forwarded": h.get("forwarded"), "origin": h.get("origin"),
            "lines": sum(1 for l in old_texts[n].splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))),
        }
    added = [n for n in new_names if n not in old_names]
    yield {"bump": f"{old_up.split('/',1)[1]} -> {new_up.split('/',1)[1]}", "added": added,
           "upstream_files_changed": len(changed)}


def main():
    os.makedirs(WORK, exist_ok=True)
    ups = final_uploads()[-(N + 1):]
    for (ou, od), (nu, nd) in zip(ups, ups[1:]):
        for row in replay(ou, od, nu, nd):
            print(json.dumps(row), flush=True)


main()
