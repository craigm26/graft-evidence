"""How many downstream patches are the same change in another distro?

For each package: Ubuntu's delta patches (debian/patches files Ubuntu changed or added at its latest merge),
Debian's patches at that merge's Debian upload, and Fedora's *.patch files on rawhide. A patch counts as shared
with another distro when at least half of its hunks (hunks with 2+ changed lines, compared on their +/- lines
with whitespace stripped) appear among that distro's hunks.

usage: python3 -I ubuntu/sharing.py data/ubuntu/merges.json <work> <fedora-dir> <pkg,pkg,...> > data/ubuntu/sharing.json
"""
import hashlib, json, os, re, subprocess, sys

M = json.load(open(sys.argv[1]))
WORK, FED = os.path.abspath(sys.argv[2]), os.path.abspath(sys.argv[3])
FEDORA = {"apache2": "httpd", "bind9": "bind", "xorg-server": "xorg-x11-server", "gst-plugins-bad1.0": "gstreamer1-plugins-bad-free",
          "exim4": "exim", "gtk+3.0": "gtk3", "shadow": "shadow-utils", "procps": "procps-ng", "gdm3": "gdm",
          "open-iscsi": "iscsi-initiator-utils", "multipath-tools": "device-mapper-multipath", "tiff": "libtiff"}


def hunks(text):
    out, cur = set(), []
    def flush():
        if len(cur) >= 2:
            out.add(hashlib.sha1("\n".join(cur).encode()).hexdigest())
        cur.clear()
    for line in text.splitlines():
        if line.startswith("@@") or line.startswith("diff ") or line.startswith("--- "):
            flush()
        elif line[:1] in "+-" and not line.startswith(("+++", "---")):
            s = re.sub(r"\s+", "", line[1:])
            if s:
                cur.append(line[0] + s)
    flush()
    return out


def shared(patch_hunks, pool):
    return bool(patch_hunks) and sum(h in pool for h in patch_hunks) * 2 >= len(patch_hunks)


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, timeout=900)


def patches_at(repo, tag, only=None):
    ls = git(repo, "ls-tree", "-r", "--name-only", f"import/{tag}", "--", "debian/patches").stdout.decode().split("\n")
    out = {}
    for p in ls:
        if not p or p.endswith("/series") or (only is not None and p not in only):
            continue
        r = git(repo, "show", f"import/{tag}:{p}")
        if r.returncode == 0:
            out[p] = r.stdout.decode("utf-8", "replace")
    return out


def fedora(pkg):
    name = FEDORA.get(pkg, pkg)
    d = os.path.join(FED, name)
    if not os.path.exists(d):
        r = subprocess.run(["git", "clone", "-q", "--depth=1", f"https://src.fedoraproject.org/rpms/{name}.git", d], capture_output=True, timeout=900)
        if r.returncode:
            return None
    out = {}
    for f in os.listdir(d):
        if f.endswith((".patch", ".diff")):
            out[f] = open(os.path.join(d, f), errors="replace").read()
    return out


res = {}
for pkg in sys.argv[4].split(","):
    m = M[pkg]["merges"][-1]
    repo = os.path.join(WORK, pkg + ".git")
    delta = set(git(repo, "diff", "--no-renames", "--name-only", f"import/{m['B']}", f"import/{m['L']}").stdout.decode().split("\n"))
    ub = patches_at(repo, m["L"], only={p for p in delta if p.startswith("debian/patches/")})
    deb = patches_at(repo, m["R"])
    fed = fedora(pkg)
    if fed is None:
        res[pkg] = {"error": "no fedora package"}
        continue
    pools = {"debian": set().union(*map(hunks, deb.values())) if deb else set(),
             "fedora": set().union(*map(hunks, fed.values())) if fed else set()}
    ubh = {p: hunks(t) for p, t in ub.items()}
    debh = {p: hunks(t) for p, t in deb.items()}
    res[pkg] = {
        "fedora_name": FEDORA.get(pkg, pkg), "fedora_patches": len(fed), "debian_patches": len(deb),
        "ubuntu_delta_patches": len([p for p in ubh if ubh[p]]),
        "ubuntu_shared_fedora": sorted(p for p, h in ubh.items() if shared(h, pools["fedora"])),
        "ubuntu_shared_debian": sorted(p for p, h in ubh.items() if shared(h, pools["debian"])),
        "debian_shared_fedora": sorted(p for p, h in debh.items() if shared(h, pools["fedora"])),
        "debian_with_hunks": len([p for p in debh if debh[p]]),
    }
    print(pkg, {k: (len(v) if isinstance(v, list) else v) for k, v in res[pkg].items()}, file=sys.stderr, flush=True)
json.dump(res, sys.stdout, indent=1)
