#!/usr/bin/env python3
"""The repo sweep lists unpushed commits too, and says `-` when it cannot know.

    python3 tests/test_repos_sweep.py

WHAT IS FIRED. `sweep_repos` is lifted out of claude-watchdog.sh as it is
written -- not a copy of it -- and run by bash against a temporary HOME whose
~/.code holds one fixture checkout per case, with a bare repo beside them as
the remote. Nothing here touches the network or the real ~/.code: the only
remote is a path, and HOME, REPOS and REPOS_AT all point into a temp dir.

THEN THE READER. The file the sweep just wrote is read back by the
dashboard's `dirty_repos`, alongside hand-written 3- and 6-column rows (an
older daemon's file, and garbage), and the uncommitted panel's cell and
title are checked for ahead, not ahead, and unknown.

THE RULE IT HOLDS. A row is written when a tree is dirty OR ahead of its
upstream. Ahead and behind are `-` -- never 0 -- when there is no upstream,
the HEAD is detached, or the upstream's remote-tracking ref is gone: a 0
there would be a guess, and a guess is worse than a refusal anywhere a
number is reported.
"""
import atexit
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = 0

# The dashboard half imports with a scratch HOME, so nothing here can read
# the real watchdog's files or config.
_DASH_HOME = tempfile.mkdtemp(prefix="mux-repos-dash-")
atexit.register(shutil.rmtree, _DASH_HOME, ignore_errors=True)
os.environ.update(HOME=_DASH_HOME,
                  XDG_CONFIG_HOME=_DASH_HOME + "/.config",
                  XDG_STATE_HOME=_DASH_HOME + "/.local/state",
                  XDG_DATA_HOME=_DASH_HOME + "/.local/share")
for _k in ("MUXTOPUS_CONFIG", "MUXTOPUS_HOME", "MUXTOPUS_DIR",
           "CLAUDE_CONFIG_DIR", "TMUX"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(ROOT))


def ok(cond, what):
    global fails
    if cond:
        print("ok   " + what)
    else:
        fails += 1
        print("FAIL " + what)


def eq(got, want, what):
    ok(got == want, what if got == want else f"{what}: got {got!r}, want {want!r}")


if shutil.which("git") is None:
    print("SKIP no git on this machine -- the sweep has nothing to run either")
    sys.exit(0)

wd = (ROOT / "claude-watchdog.sh").read_text()
m = re.search(r"^sweep_repos\(\) \{.*?^\}\n", wd, re.S | re.M)
ok(m is not None, "sweep_repos is still a top-level function in claude-watchdog.sh")
if m is None:
    sys.exit(1)
SWEEP = m.group(0)

tmp = pathlib.Path(tempfile.mkdtemp(prefix="mux-repos-"))
atexit.register(shutil.rmtree, tmp, ignore_errors=True)
HOME = tmp / "home"
CODE = HOME / ".code"
STATE = tmp / "state"
for p in (CODE, STATE):
    p.mkdir(parents=True)
REPOS = STATE / "repos.tsv"
REPOS_AT = STATE / "repos.at"

# A git with no user config, no system config and a fixed identity, so the
# fixtures build the same on a CI runner as on a box with a signing hook.
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
ENV.update(HOME=str(HOME), GIT_CONFIG_NOSYSTEM="1",
           GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@t", LC_ALL="C")


def git(cwd, *args):
    return subprocess.run(["git", "-c", "init.defaultBranch=main",
                           "-c", "advice.detachedHead=false", *args],
                          cwd=cwd, env=ENV, check=True, capture_output=True,
                          text=True).stdout


def commit(repo, msg):
    f = pathlib.Path(repo) / "f.txt"
    f.write_text(f.read_text() + msg + "\n" if f.exists() else msg + "\n")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-qm", msg)


def dirty(repo):
    f = pathlib.Path(repo) / "f.txt"
    f.write_text(f.read_text() + "uncommitted\n")


# The remote, with one commit on main, outside ~/.code so the sweep never
# sees it (it is bare anyway, and has no .git).
BARE = tmp / "remote.git"
seed = tmp / "seed"
seed.mkdir()
git(tmp, "init", "-q", "--bare", str(BARE))
git(seed, "init", "-q")
commit(seed, "base")
git(seed, "remote", "add", "origin", str(BARE))
git(seed, "push", "-q", "origin", "main")


def clone(name):
    d = CODE / name
    git(tmp, "clone", "-q", str(BARE), str(d))
    return d


# (a) dirty, with an upstream, level with it.
a = clone("a-dirty")
dirty(a)
# (b) clean and two commits ahead of its upstream.
b = clone("b-ahead")
commit(b, "one")
commit(b, "two")
# (c) clean, no upstream at all, one local commit.
c = CODE / "c-noup"
c.mkdir()
git(c, "init", "-q")
commit(c, "local")
# (c') the same, but dirty: listed, and its counts are `-`.
c2 = CODE / "c2-noup-dirty"
c2.mkdir()
git(c2, "init", "-q")
commit(c2, "local")
dirty(c2)
# (d) a detached HEAD, clean; (d') detached and dirty.
d = clone("d-detached")
git(d, "checkout", "-q", "--detach")
d2 = clone("d2-detached-dirty")
git(d2, "checkout", "-q", "--detach")
dirty(d2)
# (e) clean and level: nothing to lose, not listed.
e = clone("e-level")
# (f) dirty, one ahead AND one behind -- the order of the two columns. The
# remote moves on from another clone, and f fetches it: behind is against the
# LAST FETCH, which is the only thing the sweep may look at.
f = clone("f-both")
other = tmp / "other"
git(tmp, "clone", "-q", str(BARE), str(other))
commit(other, "theirs")
git(other, "push", "-q", "origin", "main")
commit(f, "ours")
git(f, "fetch", "-q")
dirty(f)
# (g) dirty, upstream configured but its remote-tracking ref is gone (the
# branch was deleted on the remote and pruned): rev-list fails, so `-`.
g = clone("g-gone")
git(g, "checkout", "-q", "-b", "feature")
git(g, "config", "branch.feature.remote", "origin")
git(g, "config", "branch.feature.merge", "refs/heads/feature")
dirty(g)
# (h) a worktree two levels down (~/.code/*/*/), whose .git is a FILE, one
# ahead of the upstream it tracks.
parent = CODE / "hparent"
parent.mkdir()
h = parent / "h-worktree"
git(e, "worktree", "add", "-q", "-b", "wt", str(h), "origin/main")
commit(h, "wt-one")


def sweep(every=120, stamp=None):
    if stamp is None:
        REPOS_AT.unlink(missing_ok=True)
    else:
        REPOS_AT.write_text(f"{stamp}\n")
    script = f'{SWEEP}\nsweep_repos\n'
    env = dict(ENV, REPOS=str(REPOS), REPOS_AT=str(REPOS_AT), REPO_EVERY=str(every))
    r = subprocess.run(["bash", "-c", 'REPOS="$REPOS"; REPOS_AT="$REPOS_AT"; ' + script],
                       env=env, capture_output=True, text=True)
    return r


r = sweep()
eq(r.returncode, 0, "the sweep runs")
eq(r.stderr, "", "..and says nothing on stderr")
rows = {}
for line in REPOS.read_text().splitlines():
    fields = line.split("\t")
    eq(len(fields), 6, f"row {fields[1] if len(fields) > 1 else line!r} has six columns")
    rows[fields[1]] = fields
print("   repos.tsv:\n" + "".join(f"     {l}\n" for l in REPOS.read_text().splitlines()))

# The old three columns first, in their old order: an older dashboard's
# positional reader must keep every field it knew.
eq(rows.get("a-dirty"), [str(a), "a-dirty", "1", "main", "0", "0"],
   "(a) dirty with an upstream: listed, level, with its branch")
eq(rows.get("b-ahead"), [str(b), "b-ahead", "0", "main", "2", "0"],
   "(b) clean and 2 ahead: listed, changed a TRUE 0, ahead 2, behind 0")
ok("c-noup" not in rows, "(c) clean, no upstream: not listed")
eq(rows.get("c2-noup-dirty"), [str(c2), "c2-noup-dirty", "1", "main", "-", "-"],
   "(c') dirty, no upstream: listed, ahead and behind `-`, never 0")
ok("d-detached" not in rows, "(d) detached and clean: not listed")
eq(rows.get("d2-detached-dirty"), [str(d2), "d2-detached-dirty", "1", "-", "-", "-"],
   "(d') detached and dirty: branch, ahead and behind all `-`")
ok("e-level" not in rows, "(e) clean and level: not listed")
eq(rows.get("f-both"), [str(f), "f-both", "1", "main", "1", "1"],
   "(f) one ahead, one behind: behind is the LAST column (left of ...HEAD is upstream)")
eq(rows.get("g-gone"), [str(g), "g-gone", "1", "feature", "-", "-"],
   "(g) an upstream whose ref is gone: `-`, not 0")
eq(rows.get("h-worktree"), [str(h), "h-worktree", "0", "wt", "1", "0"],
   "(h) a worktree two levels down: found, 1 ahead")
eq(len(rows), 7, "and nothing else is listed")
ok(not (STATE / "repos.tsv.tmp").exists(), "the .tmp was moved into place, not left")
SWEPT = REPOS.read_text()

# The clock: inside REPO_EVERY the file is not rewritten.
REPOS.write_text("sentinel\n")
sweep(every=120, stamp=int(time.time()))
eq(REPOS.read_text(), "sentinel\n", "a sweep inside REPO_EVERY leaves repos.tsv alone")

# Pushing b makes it level: it drops off the list at the next sweep. (The
# remote moved on under it for (f), and both histories touch the same file,
# so this fixture's remote is simply overwritten.)
git(b, "push", "-qf", "origin", "main")
sweep()
names = [l.split("\t")[1] for l in REPOS.read_text().splitlines()]
ok("b-ahead" not in names, "(b) pushed: clean and level, so no longer listed")


# ---- the reader ------------------------------------------------------------
from dashboard import data as dd                              # noqa: E402
from dashboard.data import Repo                               # noqa: E402
from dashboard.views.main import files_cell, uncommitted_title  # noqa: E402

TSV = tmp / "read.tsv"
dd.WATCHDOG_REPOS = TSV


def read(text):
    TSV.write_text(text)
    return dd.dirty_repos()


got = {r.name: r for r in read(SWEPT)}
eq(set(got), set(rows), "the reader keeps every row the sweep wrote")
eq(got["b-ahead"], Repo(str(b), "b-ahead", 0, "main", "2", "0"),
   "(b) read back: 0 files, 2 ahead")
eq(got["d2-detached-dirty"].ahead_n, None, "(d') read back: `-` is None, not 0")
eq(got["f-both"].behind, "1", "(f) read back: behind 1")

eq(read("/p/old\told\t7\n"), [Repo("/p/old", "old", 7, "-", "-", "-")],
   "an OLDER daemon's 3-column row: every new field `-`")
eq(read("/p/new\tnew\t3\tmain\t2\t1\n"), [Repo("/p/new", "new", 3, "main", "2", "1")],
   "a 6-column row: all six fields")
eq(read("/p/x\tx\t3\t\tbad\t-1\n"), [Repo("/p/x", "x", 3, "-", "-", "-")],
   "an empty branch and counts that are not counts read as `-`, never a number")
eq(read("/p/y\ty\tmany\tmain\t2\t0\nshort\t1\n"), [],
   "a row whose changed is not a number, or with fewer than three fields, is skipped")
eq(read("/p/w\tw\t3\tmain\t2\t0\textra\n")[0].ahead, "2",
   "a NEWER writer's seventh column does not move the six this reader knows")
order = [r.name for r in read("/p/a\tclean-ahead-1\t0\tm\t1\t0\n"
                              "/p/b\tdirty-2\t2\n"
                              "/p/c\tclean-ahead-5\t0\tm\t5\t0\n"
                              "/p/d\tdirty-9\t9\tm\t-\t-\n")]
eq(order, ["dirty-9", "dirty-2", "clean-ahead-5", "clean-ahead-1"],
   "most files first, as before; clean-but-ahead trees below them, most ahead first")
eq(dd.dirty_for("/p/c/sub", read("/p/c\tc\t0\tm\t5\t0\n/p\tp\t4\n")), 0,
   "a session in a clean-but-ahead worktree has 0 dirty files, not its parent's 4")

# ---- the panel -------------------------------------------------------------
eq(files_cell(Repo("/p", "p", 3, "main", "2", "0")).plain, "3 ↑2",
   "dirty and ahead: the count, then ↑n")
eq(files_cell(Repo("/p", "p", 0, "main", "2", "0")).plain, "0 ↑2",
   "clean and ahead: a true 0, then ↑n")
eq(files_cell(Repo("/p", "p", 3, "main", "0", "4")).plain, "3",
   "level with the upstream (behind or not): no arrow")
eq(files_cell(Repo("/p", "p", 3, "-", "-", "-")).plain, "3",
   "unknown: nothing drawn, not ↑0")
eq(files_cell(Repo("/p", "p", 3)).plain, "3", "an old 3-column row: the cell it always was")
old = [Repo("/a", "a", 7), Repo("/b", "b", 3)]
eq(uncommitted_title(old),
   "[bold]uncommitted[/] [grey42]· 2 tree(s) · 10 file(s)",
   "nothing ahead: the title it always had")
eq(uncommitted_title(old + [Repo("/c", "c", 0, "m", "2", "0"), Repo("/d", "d", 1, "-", "-", "-")]),
   "[bold]uncommitted[/] [grey42]· 4 tree(s) · 11 file(s) · 2 commit(s) unpushed",
   "something ahead: the unpushed commits are counted, the unknown one is not")

print(f"\n{'FAILED' if fails else 'passed'}: {fails} failure(s)")
sys.exit(1 if fails else 0)
