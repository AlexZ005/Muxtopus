#!/usr/bin/env python3
"""muxhandovers: the reader, the states, the summariser and the fork parser.

Run it:  python3 tests/test_handovers.py     (no dependency beyond python3)

FOUR THINGS ARE PROVEN HERE.

1. THE STATES ARE THE WATCHDOG'S. `lane_state` tests `done/` before the open
   file, exactly as `sched_dep_state` in claude-watchdog.sh does, and the
   order is greped OUT OF THE SHELL and asserted -- so a future reorder on
   that side fails this test rather than making the dashboard promise a hold
   the executor has already released.

2. EVERY SHAPE A REAL HANDOVER HAS is read. tests/fixtures/handovers/ holds a
   trimmed copy of each one measured in the real folder (its README lists
   which is which); no test here reads, writes or moves anything in
   ~/.code/handovers.

3. THE FOUR FILTER COMBINATIONS show what §4 of the plan says they show, and
   what is hidden is always COUNTED -- a filter may hide a row, never the
   fact that the row exists.

4. THE FORK PARSER survives all four ways a QUESTIONS file has been written
   (bulleted options, inline options, `##` headings with no options at all,
   and the older `Q1:` contract), and `write_answer` changes one line and no
   other byte.
"""
import os
import pathlib
import re
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import muxhandovers as mh                      # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "handovers"
n = 0


def ok(cond, what):
    global n
    n += 1
    if not cond:
        print("FAIL %d: %s" % (n, what))
        sys.exit(1)


def eq(got, want, what):
    ok(got == want, "%s\n       got  %r\n       want %r" % (what, got, want))


# A WRITABLE COPY. The fixtures are read-only material; anything that chmods
# or writes works on this and the originals stay exactly as committed.
TMP = pathlib.Path(tempfile.mkdtemp(prefix="muxhandovers-"))
shutil.copytree(FIX, TMP / "fx")
HDIR = TMP / "fx" / "hdir"
LEGACY = TMP / "fx" / "legacy"


# ---- 1. the names ---------------------------------------------------------
eq(mh.slug_of("STATUS-dash-split.md"), ("status", "dash-split", ""), "a plain STATUS name")
eq(mh.slug_of("QUESTIONS-dash-split.md"), ("questions", "dash-split", ""), "a QUESTIONS name")
eq(mh.slug_of("STATUS-lane-b-20260916-120000.md"),
   ("status", "lane-b", "20260916-120000"), "a SECOND finish keeps its stamp")
eq(mh.slug_of("/a/b/STATUS-x.md"), ("status", "x", ""), "a full path")
eq(mh.slug_of("notes.md"), ("", "", ""), "not a handover")
eq(mh.slug_of("STATUS-.md"), ("", "", ""), "an empty slug is not a handover")
eq(mh.slug_of("README"), ("", "", ""), "no extension")
for slug, stamp in (("x", ""), ("a-b-c", ""), ("lane-b", "20260916-120000")):
    eq(mh.slug_of(mh.status_name(slug, stamp)), ("status", slug, stamp),
       "slug_of round-trips status_name(%r, %r)" % (slug, stamp))
    eq(mh.slug_of(mh.questions_name(slug, stamp)), ("questions", slug, stamp),
       "slug_of round-trips questions_name(%r, %r)" % (slug, stamp))


# ---- 2. the states, in the watchdog's order -------------------------------
eq(mh.lane_state(HDIR, "open-lane")[0], "open", "an open handover")
eq(mh.lane_state(HDIR, "done-lane")[0], "done", "one that is in done/")
eq(mh.lane_state(HDIR, "nothing-by-that-name")[0], "none", "no handover at all")
eq(mh.lane_state(HDIR, "shadow-lane")[0], "done",
   "BOTH files: done wins, because that is what after: sees")
ok(mh.lane_state(HDIR, "open-lane")[1] > 0, "an age comes back with the state")
eq(mh.lane_state(HDIR, "nothing-by-that-name")[1], 0.0, "no file, no age")
ok(mh.shadowed(HDIR, "shadow-lane"), "the both-files case is flagged")
ok(not mh.shadowed(HDIR, "open-lane"), "an ordinary open lane is not")
ok(not mh.shadowed(HDIR, "done-lane"), "nor is an ordinary finished one")

# THE MIRROR. sched_dep_state decides whether `after: <slug>` is satisfied,
# and it tests done/ FIRST. If that is ever reordered, a lane with both files
# becomes "open" to the executor and "done" here, which is precisely the
# disagreement this module exists to end -- so it fails here, in python,
# where somebody is looking.
wd = (ROOT / "claude-watchdog.sh").read_text()
body = re.search(r"^sched_dep_state\(\) \{(.*?)^\}", wd, re.S | re.M).group(1)
i_done = body.index('done/STATUS-$dep.md')
i_open = body.index('"$HANDOVERS/STATUS-$dep.md"')
ok(i_done < i_open,
   "sched_dep_state still tests done/ before the open file (mirror of lane_state)")


# ---- 3. what one row says -------------------------------------------------
title, gist = mh.summarise((HDIR / "STATUS-open-lane.md").read_text())
eq(title, "STATUS: open-lane", "a heading is the title, hashes off")
eq(gist, "Phase 2 done, stopped as instructed. Nothing half-finished.",
   "the gist is the first line of prose under it")
eq(mh.said(title, gist, "open-lane"), gist,
   "a title that is only the slug and the word STATUS yields to the gist")

title, gist = mh.summarise((HDIR / "STATUS-verdict-lane.md").read_text())
eq(mh.said(title, gist, "verdict-lane"),
   "Lane verdict-lane — phase 3 (the hardening) — COMPLETE",
   "a title carrying the verdict is kept")

title, gist = mh.summarise((HDIR / "STATUS-prose-lane.md").read_text())
ok(title.startswith("VERDICT: NOT ours"),
   "a file that opens with a paragraph has that paragraph as its title")
eq(gist, "Read-only lane. Nothing committed, nothing pushed.",
   "the HEADING under it is skipped like any other -- the gist is prose")

title, gist = mh.summarise((HDIR / "STATUS-fenced-lane.md").read_text())
eq(gist, "The first line of prose is this one, under the fence and the table.",
   "a fence, its contents and a table are not the gist")
eq(mh.summarise(""), ("", ""), "an empty file says nothing")
eq(mh.summarise("\n\n\n"), ("", ""), "nor does a blank one")
eq(mh.summarise("# only a heading\n"), ("only a heading", ""), "a heading and no body")


# ---- 4. questions: answered, and the forks --------------------------------
marked = (HDIR / "QUESTIONS-marked-lane.md").read_text()
opened = (HDIR / "QUESTIONS-open-lane.md").read_text()
eq(mh.question_state(marked), "answered", "the ANSWERED marker is the state")
eq(mh.question_state(opened), "unanswered", "without it a file is unanswered")
eq(mh.question_state("ANSWERED 2026-09-17: yes"), "answered", "a bare marker counts")
eq(mh.question_state("**ANSWERED 2026-09-17: yes**"), "answered",
   "and so does the bolded one the user actually types")
eq(mh.question_state("nothing ANSWERED here"), "unanswered",
   "the word mid-line is not a marker")

count, first = mh.forks(opened)
eq(count, 3, "three numbered forks")
ok(first.startswith("1. What esc does"), "and the first one's line: %r" % first)
eq(mh.forks((HDIR / "QUESTIONS-prose-lane.md").read_text())[0], 2, "## headings count")
eq(mh.forks((LEGACY / "QUESTIONS-legacy-lane.md").read_text())[0], 1, "Q1: counts")
eq(mh.forks("no forks here at all\n"), (0, ""), "a file with none")
eq(mh.forks("```\n1. not a fork, a transcript\n```\n")[0], 0,
   "a numbered line inside a fence is not a fork")


# ---- 5. scan: every file, both folders ------------------------------------
rows = mh.scan(HDIR, LEGACY)
# A ROW IS A FILE, not a lane: `shadow-lane` has two of them, which is the
# whole point of the both-files case, so the key carries the state as well.
by = {(r["kind"], r["slug"], r["stamp"], r["state"]): r for r in rows}
eq(len(rows), len(by), "no FILE is listed twice")
eq(len(rows), 13, "every file in both folders is a row")
ok(("status", "open-lane", "", "open") in by, "an open handover is a row")
ok(("status", "done-lane", "", "done") in by, "a finished one is a row")
ok(("status", "rerun-lane", "20260917-101500", "done") in by,
   "a stamped second finish is a done row of the same lane")
ok(("questions", "legacy-lane", "", "unanswered") in by, "the legacy folder is read too")
ok(by[("questions", "legacy-lane", "", "unanswered")]["legacy"], "and its row says so")
ok(not by[("questions", "open-lane", "", "unanswered")]["legacy"],
   "an ordinary one does not")
ok(not any(r["slug"] == "notes" for r in rows), "notes.md is not a lane")
ok(not any("draft" in str(r["path"]) for r in rows), "nor is anything in a subfolder")

ok(("status", "shadow-lane", "", "open") in by,
   "the open file of a both-files lane is drawn open")
ok(by[("status", "shadow-lane", "", "open")]["shadowed"],
   "...and flagged, because after: already sees it as done")
ok(("status", "shadow-lane", "", "done") in by, "its done/ twin is a row of its own")
ok(not by[("status", "shadow-lane", "", "done")]["shadowed"],
   "and the twin is not itself flagged")

ok(("questions", "marked-lane", "", "answered") in by, "a marked file is answered")
ok(("questions", "open-lane", "", "unanswered") in by, "an unmarked one is not")
eq(by[("questions", "open-lane", "", "unanswered")]["said"].split(" · ")[0], "3 forks",
   "a QUESTIONS row says how many forks, not what the file is called")
eq(by[("questions", "legacy-lane", "", "unanswered")]["said"].split(" · ")[0], "1 fork",
   "and it counts in the singular when there is one")

eq(mh.counts(rows)["open"], 5, "five open handovers in the fixture")
eq(mh.counts(rows)["unanswered"], 4, "four unanswered question files")
eq(mh.counts(rows)["done"], 3, "three finished ones")

# ORDER: what is owed, first.
states = [r["state"] for r in rows]
eq(states, sorted(states, key=lambda s: mh.RANK[s]),
   "unanswered questions, then open, then answered, then done")
opens = [r["mtime"] for r in rows if r["state"] == "open"]
eq(opens, sorted(opens, reverse=True), "and newest first within a state")

# The cache re-reads only what changed.
cache = {}
mh.scan(HDIR, LEGACY, cache)
eq(len(cache), len(rows), "every file is remembered by (mtime, size)")
before = dict(cache)
mh.scan(HDIR, LEGACY, cache)
eq(cache, before, "a second scan of an unchanged folder reads nothing new")
p = HDIR / "STATUS-open-lane.md"
p.write_text(p.read_text() + "\none more line, so the size changed\n")
mh.scan(HDIR, LEGACY, cache)
ok(cache[str(p)]["at"] != before[str(p)]["at"], "a changed file is re-read")

# AN UNREADABLE FILE IS STILL A ROW. Dropping it silently is how a handover
# goes missing without anybody being told.
bad = HDIR / "STATUS-unreadable-lane.md"
bad.write_text("# STATUS: unreadable-lane\n")
os.chmod(bad, 0o000)
try:
    rows2 = mh.scan(HDIR, LEGACY)
    row = next((r for r in rows2 if r["slug"] == "unreadable-lane"), None)
    ok(row is not None, "the unreadable file is still a row")
    ok(row["error"], "with the reason on it: %r" % (row or {}).get("error"))
    ok("cannot read" in row["said"], "and the row says so out loud")
finally:
    os.chmod(bad, 0o644)
    bad.unlink()

eq(mh.scan(TMP / "nope", None), [], "a folder that is not there is no rows, not a crash")


# ---- 6. the two filters, all four combinations ----------------------------
rows = mh.scan(HDIR, LEGACY)
kinds = lambda rs: (sum(1 for r in rs if r["kind"] == "questions"),    # noqa: E731
                    sum(1 for r in rs if r["state"] in ("done", "answered")))

qs, dn = kinds(mh.visible(rows, False, True))
ok(qs > 0 and dn == 0, "done off, asks on -- THE DEFAULT: what is owed")
ok(all(r["state"] in ("open", "unanswered") for r in mh.visible(rows, False, True)),
   "...and nothing finished is in it")
qs, dn = kinds(mh.visible(rows, True, True))
ok(qs > 0 and dn > 0, "done on, asks on -- everything")
eq(len(mh.visible(rows, True, True)), len(rows), "...which is every row")
qs, dn = kinds(mh.visible(rows, False, False))
ok(qs == 0 and dn == 0, "done off, asks off -- open handovers only")
qs, dn = kinds(mh.visible(rows, True, False))
ok(qs == 0 and dn > 0, "done on, asks off -- open and done handovers, no questions")
ok(all(r["kind"] == "status" for r in mh.visible(rows, True, False)),
   "...and not one question row")

# A FILTER MAY HIDE A ROW; IT MAY NEVER HIDE THE FACT THAT IT EXISTS.
h = mh.hidden(rows, False, True)
eq(h["done"], mh.counts(rows)["done"] + 1, "the hidden count names every finished row")
eq(mh.hidden(rows, True, True)["total"], 0, "nothing hidden when both are on")
eq(mh.hidden(rows, False, False)["questions"], 5,
   "with asks off, every question row is counted as hidden -- answered ones too")


# ---- 7. the forks, parsed -------------------------------------------------
fk = mh.parse_forks(opened)
eq(len(fk), 3, "three forks in the bulleted file")
eq([f["id"] for f in fk], [mh.fork_id(f["title"]) for f in fk],
   "an id is a function of the title, so inserting a fork above does not move it")
eq(len(set(f["id"] for f in fk)), 3, "and the three are distinct")
eq([o["key"] for o in fk[0]["options"]], ["a", "b"], "bulleted options are found")
eq(fk[0]["options"][0]["text"],
   "RECOMMENDED: esc cancels on reopen, changes nothing; enter saves.",
   "a bulleted option is its own line, not the argument under it")
ok(fk[0]["options"][0]["rec"], "RECOMMENDED marks the recommendation")
ok(not fk[0]["options"][1]["rec"], "and only it")
eq(fk[0]["answer"], "", "an unanswered fork")
ok(fk[1]["answer"].startswith("**Answer taken:**"), "an answered one keeps its line")
ok(fk[1]["options"][1]["rec"], "RECOMMENDED found mid-list")

inline = mh.parse_forks((HDIR / "QUESTIONS-inline-lane.md").read_text())
eq([o["text"] for o in inline[0]["options"]],
   ["RECOMMENDED tabs inside s on the arrows", "a top-level key of its own",
    "a toggle inside the current view."],
   "an inline option wraps to the next line and stops at the next letter")
eq([o["key"] for o in inline[1]["options"]], ["a", "b", "c"], "three inline options")
eq(inline[1]["options"][2]["text"], "true UTC via a time server.",
   "the LAST inline option stops at the block after it")
ok(inline[1]["options"][0]["rec"],
   "a `Recommendation: (a)` line names the option when no text says RECOMMENDED")

prose = mh.parse_forks((HDIR / "QUESTIONS-prose-lane.md").read_text())
eq(len(prose), 2, "## headings are forks")
eq(prose[0]["options"], [], "a fork with no options offers none")
ok(all(f["answer"] for f in prose), "both carry the lane's own answer")

legacy = mh.parse_forks((LEGACY / "QUESTIONS-legacy-lane.md").read_text())
eq(len(legacy), 1, "the older Q1: contract parses too")
eq(legacy[0]["options"], [], "its `- a)` options are not the (a) shape, so: none")
eq(legacy[0]["answer"], "", "and its `Answer: (reply ...)` line is not an answer")

eq(mh.parse_forks(""), [], "an empty file has no forks")
ok(not mh.all_answered([]), "no forks is not `all answered`")
ok(mh.all_answered(prose), "every fork answered")
ok(not mh.all_answered(fk), "one of three answered is not")
# `(see (b) above)` must not invent an option.
aside = mh.parse_forks("1. A fork with (a) one option and an aside (see (b) above)\n")
eq([o["key"] for o in aside[0]["options"]], ["a", "b"], "letters in order are options")
aside = mh.parse_forks("1. A fork whose only paren is (z) a stray letter\n")
eq(aside[0]["options"], [], "a letter out of sequence is not an option")


# ---- 8. write_answer: one line, and no other byte -------------------------
DATE = "2026-09-18"
out = mh.write_answer(opened, fk[0]["id"], "(a) — because esc means back out", DATE)
lines_before, lines_after = opened.splitlines(), out.splitlines()
eq(len(lines_after), len(lines_before) + 1, "exactly one line was added")
added = [l for l in lines_after if l not in lines_before]
eq(added, ["**Answer (user, 2026-09-18):** (a) — because esc means back out"],
   "and it is the answer line")
after = mh.parse_forks(out)
eq(after[0]["answer"], added[0], "which lands inside the fork it answers")
eq(after[1]["answer"], fk[1]["answer"], "the fork below is untouched")
eq([f["id"] for f in after], [f["id"] for f in fk], "and no fork changed identity")
eq(out.count("\n"), opened.count("\n") + 1, "the file still ends the way it did")

again = mh.write_answer(out, fk[0]["id"], "(b) — changed my mind", DATE)
eq(len(again.splitlines()), len(out.splitlines()),
   "answering the same fork again REPLACES our line rather than stacking one")
ok("(b) — changed my mind" in again, "with the new answer")
ok("because esc means back out" not in again, "and not the old one")

# The lane's own `**Answer taken:**` is its record; ours is the user's.
both = mh.write_answer(opened, fk[1]["id"], "(a) — actually the rows", DATE)
ok("**Answer taken:** (b)" in both, "somebody else's answer line is left where it is")
ok("**Answer (user, 2026-09-18):** (a) — actually the rows" in both, "ours is added")

last = mh.write_answer(opened, fk[2]["id"], "(a)", DATE)
eq(mh.parse_forks(last)[2]["answer"], "**Answer (user, 2026-09-18):** (a)",
   "the LAST fork is answered inside itself, not after the file")
ok(mh.all_answered(mh.parse_forks(
    mh.write_answer(mh.write_answer(opened, fk[0]["id"], "(a)", DATE),
                    fk[2]["id"], "(b)", DATE))),
   "answering the two open forks answers the file")

try:
    mh.write_answer(opened, "nosuchid", "(a)", DATE)
    ok(False, "an unknown fork id is refused")
except KeyError:
    ok(True, "an unknown fork id is refused rather than written somewhere")

# THE CHANGED-UNDERNEATH RE-APPLY. A live lane rewrites its QUESTIONS file
# whenever it likes, including inserting a fork ABOVE the one being answered.
# The id is a function of the fork's TITLE precisely so the answer still
# lands in the fork it was read from; a positional id would put it in the
# lane's new one.
grown = opened.replace(
    "1. **What `esc` does",
    "0. **A fork the lane added while you were reading.** (a) yes; (b) no.\n\n"
    "1. **What `esc` does", 1)
after_grown = mh.parse_forks(grown)
eq(len(after_grown), 4, "the lane's file now has four forks")
eq([f["id"] for f in after_grown][1:], [f["id"] for f in fk],
   "and the three that were there kept their ids")
moved = mh.write_answer(grown, fk[0]["id"], "(a)", DATE)
target = mh.parse_forks(moved)
eq(target[0]["answer"], "", "the fork the LANE added is not the one answered")
eq(target[1]["answer"], "**Answer (user, 2026-09-18):** (a)",
   "the answer landed in the fork it was read from, one row further down")

nofinal = "1. A fork\n2. Another"
got = mh.write_answer(nofinal, mh.parse_forks(nofinal)[1]["id"], "(a)", DATE)
ok(not got.endswith("\n"), "a file with no final newline does not gain one")


# ---- 9. the ANSWERED marker, for the folder handover.sh does not own ------
marked2 = mh.mark_answered(opened, DATE)
eq(mh.question_state(marked2), "answered", "the marker makes the file answered")
ok("**ANSWERED 2026-09-18** (marked from the dashboard)" in marked2, "and it says who")
eq(marked2.splitlines()[0], opened.splitlines()[0], "the title stays the title")
eq(mh.mark_answered(marked, DATE), marked, "a file that already has one is untouched")
eq(mh.parse_forks(marked2)[0]["title"], fk[0]["title"], "no fork moved")

# ---- 10. the two filter keys exist in BOTH halves of the contract --------
# tests/test_settings.py compares the whole lists name for name; this is the
# narrower claim that the two names the handovers tab actually reads are in
# them, so renaming a constant in dashboard/views/handovers.py without
# touching the lists fails here rather than silently writing a value the
# shell half never reads.
import muxconfig                             # noqa: E402
for key, default in (("DASHBOARD_HANDOVERS_DONE", "off"),
                     ("DASHBOARD_HANDOVERS_QUESTIONS", "on")):
    ok(key in muxconfig.KEYS, "%s is a config key" % key)
    eq(muxconfig.KEYS[key], default, "%s defaults to %r" % (key, default))
    ok(re.search(r"^%s=%s$" % (key, default),
                 (ROOT / "profile.sh").read_text(), re.M),
       "%s is in profile.sh's MUX_CONFIG_KEYS with the same default" % key)

shutil.rmtree(TMP, ignore_errors=True)
print("muxhandovers: %d checks green" % n)
