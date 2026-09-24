#!/usr/bin/env python3
"""The slug limit is ONE number, written in three files that cannot import
each other -- and this is what stops them drifting.

Run it:  .venv/bin/python tests/test_slug_limit.py

WHY THREE. The executor is bash (claude-watchdog.sh `MAX_SLUG=`), the
dashboard is Python (dashboard/naming.py `MAX_SLUG`, which
dashboard/schedules.py imports), and muxstats.py stands alone and keeps a
copy (`_MAX_SLUG`). A slug the executor cuts at one length and the dashboard
at another is a lane whose window, handover file and tree row the two halves
name differently -- the exact failure the slug rule exists to prevent. So
the shell value is GREPPED out of the script, the way tests/test_handovers.py
greps the executor's dependency order, and all three are asserted equal.

WHY 32. The live tree.tsv (2026-09-22) held three slugs at exactly the old
limit of 22, one of them cut in silence from its entry's name; a wave names
its lanes `<orchestrator>-<lane>`, and `orchestrate-plan-` alone is 17.

WHAT ELSE IS PROVEN, on the Python side (tests/test_lane_names.sh proves the
same through `claude-watchdog.sh --check` and a real launch):

  - no literal slug length is left in the code that cuts a slug: every cut
    reads the constant;
  - sanitise_slug on a 40-character title gives 32 characters;
  - slug_warning says "truncated" at 33 characters and says nothing at 23,
    the first length the old rule cut.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard import naming                                # noqa: E402
from dashboard.schedules import sanitise_slug, slug_warning  # noqa: E402
import muxstats                                             # noqa: E402

n = 0
fails = 0


def ok(cond, what):
    global n, fails
    n += 1
    if cond:
        print("ok   " + what)
    else:
        fails += 1
        print("FAIL " + what)


wd = (ROOT / "claude-watchdog.sh").read_text()
m = re.findall(r"^MAX_SLUG=(\d+)$", wd, re.M)
ok(len(m) == 1, "claude-watchdog.sh sets MAX_SLUG exactly once: %r" % m)
shell = int(m[0]) if m else None

ok(naming.MAX_SLUG == 32, "dashboard.naming.MAX_SLUG is 32: %r" % naming.MAX_SLUG)
ok(shell == naming.MAX_SLUG,
   "the shell and Python limits agree: %r vs %r" % (shell, naming.MAX_SLUG))
ok(muxstats._MAX_SLUG == naming.MAX_SLUG,
   "muxstats.py's copy agrees: %r" % muxstats._MAX_SLUG)

# ---- every cut reads the constant ------------------------------------------
# The function bodies, not the whole file: a comment may say "22" when it is
# recording what the limit used to be.
body = re.search(r"^sched_sanitise\(\) \{(.*?)^\}", wd, re.S | re.M).group(1)
ok("${s:0:MAX_SLUG}" in body and not re.search(r":0:\d", body),
   "sched_sanitise cuts at MAX_SLUG, not at a literal")
warn = re.search(r"^sched_slug_warn\(\) \{(.*?)^\}", wd, re.S | re.M).group(1)
ok('-gt "$MAX_SLUG"' in warn and "${raw:0:MAX_SLUG}" in warn
   and not re.search(r"-gt \d|:0:\d", warn),
   "sched_slug_warn's truncation test reads MAX_SLUG too")
py = (ROOT / "dashboard" / "schedules.py").read_text()
ok(not re.search(r"\[:\d+\]|> \d+ and", py),
   "dashboard/schedules.py has no literal slug length left")

# ---- what the rule does at the new limit -----------------------------------
t40 = "a-title-of-exactly-forty-characters-long"
ok(len(t40) == 40, "fixture is 40 characters (%d)" % len(t40))
ok(sanitise_slug(t40) == t40[:32], "sanitise_slug cuts a 40-character title to 32: %r"
   % sanitise_slug(t40))
ok(muxstats._sched_slug(t40) == sanitise_slug(t40),
   "and muxstats counts it under the same name")

f = pathlib.Path("x.md")
t23 = "twenty-three-characters"
t32 = "a-lane-name-of-exactly-32-chars-"
t33 = t32 + "x"
ok((len(t23), len(t32), len(t33)) == (23, 32, 33), "fixture lengths 23/32/33")
ok(slug_warning({"title": t23, "file": f}) == "",
   "a 23-character title draws no warning (the old rule cut it)")
ok(slug_warning({"slug": t32, "file": f}) == "",
   "a 32-character slug: is taken whole")
w = slug_warning({"title": t33, "file": f})
ok("truncated" in w and repr(t32) in w,
   "a 33-character title is truncated to 32, and said: %r" % w)

print()
print("%d checks, %d failed" % (n, fails))
sys.exit(1 if fails else 0)
