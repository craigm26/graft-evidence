# Graft evidence

Before selling a service that carries a team's fork onto each new upstream release, we wanted to know two things. How often is a clean rebase actually the right one? And can agents resolve the conflicts well enough to be worth a person's review?

Debian and Ubuntu answer both questions for free. They carry thousands of changes on top of upstream projects, and every decision their maintainers made is public. So we replayed their releases and checked each call against what the maintainers actually shipped. This repository holds the scripts, the recorded data and the method, so you can check every number on [graftfork.com](https://graftfork.com).

## What the replays found (2026-10-27)

**Debian's own patch stacks.** curl and openssh, the last 5 upstream releases of each, 145 patch carries:
- Plain `git rebase` shipped 3 changes unchanged that Debian changed before release.
- 7 patches that upstream had already absorbed still applied with `patch` fuzz, so they would have gone in twice.
- Graft asked a person far more often than plain rebase (102 vs 19), but 74 of its 76 one-click confirmations were "keep it".
- With auto-merge earned after two releases carried unchanged, Graft asked about 64, with no new mistakes.

**Ubuntu's merges with Debian.** 50 packages, 3 merges each (149 merges), 3,459 changed files:
- 863 files (25%) merged cleanly, but Ubuntu shipped something else.
- Graft's rule for carrying a change without asking: nothing it touches changed, or it was carried right twice in a row. Ubuntu changed 268 of the 2,070 files that rule would carry (13%; 10% without grub2).
- Half of those 268 are Ubuntu deciding to stop carrying a change, which no diff shows. On stacks like Ubuntu's, auto-merge has to rest on each change's recorded reason, not on a rule.

**Intent from patch headers** (`ubuntu/intent.py`, `ubuntu/score_intent.py`):
- A change whose header says it came from upstream (`Origin: upstream` or `backport`, `Applied-Upstream`, or a CVE fix), in a merge where the upstream version moved, was dropped by Ubuntu 327 times out of 349 (94%).
- That rule proposes 327 of Ubuntu's 675 drops. A plain merge would carry those silently.

**Blind agent rewrites** (`data/ubuntu/rewrites/`). Agents resolved 24 real Ubuntu conflicts, sampled at random with at most two per package. Each case directory holds the old Debian file, Ubuntu's file, the new Debian file and Ubuntu's changelog entries. Ubuntu's answer sits in `answers/`, which the agents never saw.

| | Diffs only (`out/`) | With Ubuntu's reasons (`out-reasons/`) |
| --- | --- | --- |
| Keep-or-drop calls matching Ubuntu | 22 of 24 | 22 of 24 |
| Files byte for byte what Ubuntu shipped | 13 | 14 |
| Lines away from Ubuntu's files | 89 | 84 |

Taking Debian's new file unchanged is 321 lines away. Both runs miss the same two cases, bash's `etc.bash.bashrc` and dbus's `debian/control`, where Ubuntu shipped Debian's new file as is. For dbus the only Ubuntu change was the Maintainer field, which Ubuntu normally keeps, so that one may be an artifact of the replay.

**Sharing.** 5 of Ubuntu's 466 delta patches match a Fedora patch, and 76 of Debian's 589 do, almost all where one distro adopted another's patch set.

## Check the numbers

The recorded results are in `data/`. Re-scoring them takes Python 3.11+ and a few seconds:

```
python3 -I debian/score.py data/debian/curl.jsonl data/debian/openssh.jsonl > /tmp/data.json
python3 -I ubuntu/score.py data/ubuntu/replay.jsonl > /tmp/ubuntu-score.json
python3 -I ubuntu/grade_rewrites.py data/ubuntu/rewrites out-reasons > /tmp/rewrites.json
```

Compare them with `data/debian/data.json`, `data/ubuntu/ubuntu-score.json` and `data/ubuntu/rewrites-reasons.json`.

To replay from scratch, run `./run.sh`. It needs git, `patch`, Python 3.11+ and network access to salsa.debian.org, git.launchpad.net, src.fedoraproject.org and merges.ubuntu.com, plus a few GB of disk for the clones in `./work`. Upstream history moves, so a fresh run replays the latest releases, not the ones recorded here.

## How the replays work

**Debian** (`debian/replay.py`). For each upstream release, the patch series from the last Debian upload of the previous release is applied to the new upstream tag in three ways:
- in order, with `git apply` then `patch -F2` (exact, fuzz, absorbed when it applies in reverse, or fail);
- as `git cherry-pick` commits with rerere on, the plain-rebase control (clean, empty or conflict);
- through Graft's routing, which `debian/score.py` spells out in `graft()`.

Each patch is then compared with the next Debian upload (kept, refreshed, edited or dropped), and `debian/score.py` scores the calls.

**Ubuntu** (`ubuntu/`):
1. `tags.py` lists git-ubuntu's import tags.
2. `merges.py` finds each merge: the last Ubuntu upload on an old Debian base (L) and the first on a new one (H).
3. `replay.py` takes every file Ubuntu changed from the old Debian upload B to L, except `debian/changelog`, merges each one three ways onto the new Debian upload R with `git merge-file`, and compares the result with H. A regenerated patch with the same change counts as kept.
4. `score.py` scores plain merge against Graft's routing.
5. `sharing.py` compares patch hunks with Fedora's dist-git.
6. `case_reasons.py` writes Ubuntu's changelog entries into each rewrite case, and `grade_rewrites.py` grades the agents' answers.

**What a replay doesn't check:** whether the result builds or passes tests. A carried change that differs from what the maintainers shipped counts as a difference, not as a bug. And for some packages, the "last Ubuntu upload on the old base" is a stable-release security update rather than the development series, because merges are ordered by version.

## Layout

```
debian/   replay.py, score.py, subjects.py
ubuntu/   tags.py, merges.py, replay.py, score.py, intent.py, score_intent.py, sharing.py, case_reasons.py, grade_rewrites.py
data/     the recorded results, 2026-10-27
run.sh    rebuild everything from public history
```

The scripts are Apache 2.0 (`LICENSE`). Files under `data/ubuntu/rewrites/cases/` and `answers/` are excerpts of Debian and Ubuntu packaging, under each package's own license.
