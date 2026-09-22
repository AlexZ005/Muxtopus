#!/usr/bin/env python3
"""The header says so when the checkout is ahead of the tag its VERSION names.

dashboard.menus.update.checkout_state. On a machine that develops muxtopus the
`muxtopus` on PATH is a symlink into the checkout, so between a merge and a tag
the dashboard runs code the version number does not describe. This is the note
that says which commit, and how many merged changes are waiting for a number.

It must be SILENT on an installed release -- a tarball has no .git -- and
silent on the day of a release, when HEAD is the tag. Those two are most of
what this file asserts, because a note that will not go away is worse than no
note at all.

Each case is a REAL repository in a temporary directory, built with real
commits and real tags, because the whole function is a question about git and
a fake answer would prove nothing about the command lines it runs.

    python3 tests/test_unreleased.py
"""
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

fails = 0


def ok(cond, what):
    global fails
    if cond:
        print("ok   " + what)
    else:
        fails += 1
        print("FAIL " + what)


def git(cwd, *args):
    subprocess.run(("git", "-C", str(cwd)) + args, check=True,
                   capture_output=True, text=True)


def build(tmp, version="1.2.3", tag_at_head=False, extra_commit=True,
          changes=(), init=True):
    """A checkout with a v1.2.3 tag and, unless told otherwise, a commit after it."""
    d = pathlib.Path(tmp)
    (d / "VERSION").write_text(version + "\n")
    (d / "changes").mkdir(exist_ok=True)
    for name in changes:
        (d / "changes" / name).write_text("# %s\n" % name)
    if not init:
        return d
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "t@example.invalid")
    git(d, "config", "user.name", "t")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "one")
    # ANNOTATED, like a real release tag -- an annotated tag's own sha is
    # never a commit sha, which is what the ^{commit} in the lookup is for.
    git(d, "tag", "-a", "v" + version, "-m", "v" + version)
    if extra_commit and not tag_at_head:
        (d / "after.txt").write_text("landed after the tag\n")
        git(d, "add", "-A")
        git(d, "commit", "-qm", "two")
    return d


def state_of(d):
    """checkout_state with SCRIPTS pointed at d, and the cache defeated."""
    import dashboard.core as core
    from dashboard.menus import update
    before = core.SCRIPTS
    core.SCRIPTS = update.SCRIPTS = pathlib.Path(d)
    try:
        update._CO["at"] = 0.0
        return update.checkout_state()
    finally:
        core.SCRIPTS = update.SCRIPTS = before


print("== a checkout ahead of its tag names the commit")
with tempfile.TemporaryDirectory() as t:
    d = build(t)
    head = subprocess.run(("git", "-C", t, "rev-parse", "HEAD"),
                          capture_output=True, text=True).stdout.strip()
    got = state_of(d)
    ok(got.startswith("unreleased · "), "it says unreleased: %r" % got)
    ok(head[:7] in got, "the short sha is the one git reports: %s" % head[:7])
    ok("change" not in got, "no count when changes/ is empty: %r" % got)

print("== and counts the fragments waiting for a number")
with tempfile.TemporaryDirectory() as t:
    d = build(t, changes=("a.md", "b.md", "c.md", "README.md"))
    got = state_of(d)
    # README.md is the folder's documentation, not a fragment: the release
    # consumes the fragments and leaves it, so counting it would say 4 the
    # day after a release that consumed everything.
    ok(got.endswith("· 3 changes"), "README.md is not a fragment: %r" % got)

with tempfile.TemporaryDirectory() as t:
    d = build(t, changes=("only.md",))
    ok(state_of(d).endswith("· 1 change"), "one fragment is singular")

print("== and is silent whenever the question does not arise")
with tempfile.TemporaryDirectory() as t:
    d = build(t, tag_at_head=True)
    ok(state_of(d) == "", "HEAD is the tag -- the day of a release")

with tempfile.TemporaryDirectory() as t:
    d = build(t, init=False)
    ok(state_of(d) == "", "no .git -- an installed release")

with tempfile.TemporaryDirectory() as t:
    d = build(t, version="9.9.9")
    # Tagged v9.9.9 and VERSION says 9.9.9, but pretend the bump landed
    # before anyone tagged it: no tag by that name exists yet.
    git(d, "tag", "-d", "v9.9.9")
    ok(state_of(d) == "", "no tag by that name yet -- a bump before its tag")

with tempfile.TemporaryDirectory() as t:
    d = build(t)
    (d / "VERSION").write_text("\n")
    ok(state_of(d) == "", "an empty VERSION says nothing rather than guessing")

print("== the real checkout answers without raising")
got = state_of(ROOT)
ok(isinstance(got, str), "a string either way: %r" % got)

print()
print("%d FAILED" % fails if fails else "all passed")
sys.exit(1 if fails else 0)
