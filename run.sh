#!/bin/sh
# Rebuild every result from public git history. Needs git, patch, python3 and network access to
# salsa.debian.org, git.launchpad.net, src.fedoraproject.org and merges.ubuntu.com.
# Clones and worktrees go to $WORK (default ./work, git-ignored). The results land in data/.
# Note: upstream histories move, so a fresh run replays the latest five releases and three merges, not the ones
# recorded in data/ (2026-10-27).
set -eu
WORK=${WORK:-work}
mkdir -p "$WORK/forks"

# 1. Debian: curl and openssh, the last five upstream releases of each.
[ -d "$WORK/forks/curl.git" ] || git clone -q --bare https://salsa.debian.org/debian/curl.git "$WORK/forks/curl.git"
[ -d "$WORK/forks/openssh.git" ] || git clone -q --bare https://salsa.debian.org/ssh-team/openssh.git "$WORK/forks/openssh.git"
python3 -I debian/replay.py "$WORK/forks/curl.git" "$WORK/debian-curl" 5 > data/debian/curl.jsonl
python3 -I debian/replay.py "$WORK/forks/openssh.git" "$WORK/debian-openssh" 5 > data/debian/openssh.jsonl
python3 -I debian/score.py data/debian/curl.jsonl data/debian/openssh.jsonl > data/debian/data.json
python3 -I debian/subjects.py "$WORK/forks/curl.git" data/debian/curl.jsonl > data/debian/curl-subjects.json

# 2. Ubuntu: the 50 packages in main with the most Ubuntu uploads, their last three merges with Debian.
curl -fsS -o data/ubuntu/main.json https://merges.ubuntu.com/main.json
python3 -I ubuntu/tags.py data/ubuntu/main.json > data/ubuntu/tags.json
python3 -I ubuntu/merges.py data/ubuntu/tags.json > data/ubuntu/merges.json
python3 -I ubuntu/replay.py data/ubuntu/merges.json "$WORK/ubuntu" 50 > data/ubuntu/replay.jsonl
python3 -I ubuntu/score.py data/ubuntu/replay.jsonl > data/ubuntu/ubuntu-score.json
PKGS=$(python3 -I -c "
import json; M = json.load(open('data/ubuntu/merges.json'))
print(','.join([p for p, v in sorted(M.items(), key=lambda kv: -kv[1]['ubuntu_uploads']) if len(v['merges']) >= 3 and p != 'live-build'][:50]))")
mkdir -p "$WORK/fedora"
python3 -I ubuntu/sharing.py data/ubuntu/merges.json "$WORK/ubuntu" "$WORK/fedora" "$PKGS" > data/ubuntu/sharing.json

