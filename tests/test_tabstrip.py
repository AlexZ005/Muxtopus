#!/usr/bin/env python3
"""tabstrip -- the strip fitted to a width: its invariants, over every case.

Run it:  .venv/bin/python tests/test_tabstrip.py     (no pytest; needs rich)

What is promised, and checked for 1..12 tabs, every active tab and every
width from 16 to 200:

  * the strip never takes more columns than it was given (from 24 up, which
    is a 30-column terminal: under that the locked initials alone do not
    fit, and the module says so)
  * the ACTIVE tab is always drawn
  * the first six are always drawn -- they are LOCKED
  * drawn + off-left + off-right = every tab: nothing is lost uncounted, and
    a count is drawn on each side that has one
  * labels degrade before tabs disappear: nothing scrolls while initials fit
  * a narrower width never draws LONGER labels (the tier only goes up)

and then through Rich: a Panel whose title is the strip draws it WHOLE on
its top line, at App.strip_width() of an 80, 60, 40 and 30 column console.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from rich import box  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.text import Text  # noqa: E402

from dashboard.tabstrip import LOCKED, SEP, fit  # noqa: E402

fails = []
count = 0


def check(cond, what, quiet=False):
    global count
    count += 1
    if not cond:
        fails.append(what)
        print("  FAIL " + what)
    elif not quiet:
        print("  ok   " + what)


def tabs_of(n):
    names = ["schedules 6", "handovers 4 open · 3 ?", "deployments 12",
             "alerts 3", "pages", "backups 1", "certificates", "queues 40",
             "workers 7", "notes", "logs 2", "zones"]
    out = []
    for i in range(n):
        full = names[i]
        out.append((full, full.split()[0][:5] + ("".join(" " + w for w in full.split()[1:2])),
                    full[0]))
    return out


def plain(strip):
    return Text.from_markup(strip.markup).plain


print("== the invariants, over every case")
cases = 0
for n in range(1, 13):
    tabs = tabs_of(n)
    for active in range(n):
        last_tier = -1
        for width in range(200, 15, -1):
            s = fit(tabs, active, width)
            p = plain(s)
            cases += 1
            if width >= 24:
                check(len(p) <= width, "n=%d a=%d w=%d fits (%d) %r"
                      % (n, active, width, len(p), p), quiet=True)
            check(active in s.shown, "n=%d a=%d w=%d active drawn" % (n, active, width),
                  quiet=True)
            check(all(i in s.shown for i in range(min(LOCKED, n))),
                  "n=%d a=%d w=%d locked drawn" % (n, active, width), quiet=True)
            check(len(s.shown) + s.left + s.right == n,
                  "n=%d a=%d w=%d counted" % (n, active, width), quiet=True)
            check(("«%d" % s.left in p) == bool(s.left) and ("%d»" % s.right in p) == bool(s.right),
                  "n=%d a=%d w=%d markers match the counts: %r" % (n, active, width, p),
                  quiet=True)
            if s.scrolled:
                every = fit(tabs, active, 10 ** 6)
                initials = sum(len(t[2]) for t in tabs) + len(SEP) * (n - 1) + 1
                check(initials > width, "n=%d a=%d w=%d scrolled although initials fit"
                      % (n, active, width), quiet=True)
                check(every.left == every.right == 0, "wide never scrolls", quiet=True)
            check(s.tier >= last_tier, "n=%d a=%d w=%d tier only goes up"
                  % (n, active, width), quiet=True)
            last_tier = s.tier
check(not fails, "%d cases: fits, active drawn, locked drawn, counted, "
      "markers true, degrade before scroll, tier monotone" % cases)

print("== the degrade order, by example")
t = tabs_of(9)
check(plain(fit(t, 0, 500)).startswith("▸schedules 6 │ handovers 4 open"), "wide: full labels")
s = fit(t, 0, 90)
check(s.tier == 1 and "▸sched 6" in plain(s), "narrower: short labels  %r" % plain(s))
s = fit(t, 0, 40)
check(s.tier in (2, 3) and not s.scrolled, "narrower still: initials, still all nine  %r" % plain(s))
s = fit(t, 8, 30)
check(not s.scrolled and "│▸w" in plain(s),
      "at 30, one-column separators keep all nine  %r" % plain(s))
t = tabs_of(12)
s = fit(t, 9, 24)
check(s.scrolled and plain(s).replace(" ", "").startswith("s│h│d│a│p│b│"),
      "narrowest: the six locked, then a window  %r" % plain(s))
check("▸" in plain(s) and "«" in plain(s), "...holding the tenth, with a count to its left")
s = fit(t, 0, 24)
check(s.right and not s.left and plain(s).endswith("%d»" % s.right),
      "on a locked tab the window starts at the seventh, count to the right  %r" % plain(s))

print("== through Rich: the title is drawn whole")
for cols in (80, 60, 40, 30):
    bad = 0
    con = Console(width=cols, record=True, color_system=None)
    width = max(10, cols - 6)          # App.strip_width
    for n in (2, 9, 12):
        for active in range(n):
            s = fit(tabs_of(n), active, width)
            with con.capture() as cap:
                con.print(Panel("x", title=s.markup, title_align="left", box=box.ROUNDED))
            top = cap.get().splitlines()[0]
            good = plain(s) in top and len(top) <= cols
            bad += not good
            check(good, "%d cols, %d tabs, active %d: %r" % (cols, n, active, top), quiet=True)
    check(not bad, "%d columns: every strip whole on the top border" % cols)

print("\n%d checks, %d failed" % (count, len(fails)))
sys.exit(1 if fails else 0)
