#!/usr/bin/env python3
"""PageUp / PageDown / Home / End move a list, and DO NOT LEAVE THE VIEW.

Run it:  .venv/bin/python tests/test_view_paging.py   (no pytest; needs rich)

The reported bug, as a test. The user pressed End in the schedule view and
the schedule view closed; pressed Home on the dashboard and the muxtopus menu
opened. Both because decode_key turned every escape sequence it could not
name into "\\x1b", which is exactly those two keys.

So every case here starts from the BYTES a terminal sends and goes through
decode_key into the real view's on_key -- not from the string "END". THE
COUNTERFACTUAL IS THE BUG: revert decode_key to the four-arrow version and
this file goes red with "the view exited" and "a menu opened", which is the
report. `--counterfactual` runs it against that old decode_key on purpose and
passes only when the old bug is still there to be seen.

The views are driven directly with their rows set, rather than through a
rendered frame: what a page DOES to a cursor is arithmetic, and the picture
it makes is tests/sandbox/goldens.sh's job.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from rich.console import Console          # noqa: E402

import deck_status as d                   # noqa: E402
from dashboard.app import App             # noqa: E402
from dashboard.views.main import MainView            # noqa: E402
from dashboard.views.schedules import ScheduleView   # noqa: E402
import dashboard.views.handovers                     # noqa: E402
from dashboard.views.insights import InsightsView    # noqa: E402

OLD = "--counterfactual" in sys.argv

FAILS = 0
PASSES = 0

# The bytes, as measured in tests/test_decode_key.py's header.
KEYS = {"PGUP": b"\x1b[5~", "PGDN": b"\x1b[6~",
        "HOME": b"\x1b[1~", "END": b"\x1b[4~",
        "HOME-ss3": b"\x1bOH", "END-ss3": b"\x1bOF",
        "UP": b"\x1b[A", "DOWN": b"\x1b[B"}


def old_decode_key(data: bytes) -> str:
    """decode_key as it was before this lane: the final byte, four arrows,
    and a bare Escape for everything else. Kept here so the counterfactual is
    the real thing and not a description of it."""
    if data.startswith((b"\x1b[", b"\x1bO")):
        for b in data[2:]:
            if 0x40 <= b <= 0x7E:
                return {0x41: "UP", 0x42: "DOWN",
                        0x43: "RIGHT", 0x44: "LEFT"}.get(b, "\x1b")
        return "\x1b"
    return data[:1].decode("utf-8", "replace")


def press(name):
    """The key name the dashboard's reader produces for that keypress."""
    return (old_decode_key if OLD else d.decode_key)(KEYS[name])


def check(cond, what):
    global FAILS, PASSES
    if cond:
        PASSES += 1
        print("  ok   %s" % what)
    else:
        FAILS += 1
        print("  FAIL %s" % what)


class Recorder(App):
    """The real App, with the two things a page key must never trigger
    recorded instead of done: leaving the view, and opening a menu."""

    def __init__(self):
        super().__init__(2.0, Console(width=140, height=40, force_terminal=False))
        self.left_to = None
        self.opened = None

    def switch_to(self, name):
        self.left_to = name

    def open_menu(self, kind, i=0):
        self.opened = kind

    def say(self, msg):
        pass

    def hidden_tabs(self):
        return set()

    def calm(self):
        """Nothing leaked from the last keypress."""
        self.left_to = self.opened = None

    def escaped(self):
        return self.left_to is not None or self.opened is not None


def rows(n):
    return [{"i": i} for i in range(n)]


def at(state):
    """`state["i"]`, or None when the submode is gone -- which is what the
    old decoder DID to it, and the counterfactual run has to survive
    asserting about it rather than crash on a None."""
    return state["i"] if state else None


# ---------------------------------------------------------------- schedules
print("== the schedule view (s): the screen the user named")
a = Recorder()
v = ScheduleView(a)
v.rows = rows(40)
v._page = 10                # what build_sched measured for the table
v.i = 0

v.on_key(a, press("PGDN"))
check(v.i == 10, "PageDown from the top moves ONE PAGE (0 -> 10, got %d)" % v.i)
check(not a.escaped(), "...and the view is still open")
a.calm()

v.on_key(a, press("PGDN"))
check(v.i == 20, "...and again (got %d)" % v.i)
a.calm()

v.on_key(a, press("PGUP"))
check(v.i == 10, "PageUp comes back (got %d)" % v.i)
a.calm()

v.on_key(a, press("END"))
check(v.i == 39, "End is the LAST entry (got %d)" % v.i)
check(not a.escaped(), "...and the view is STILL OPEN -- this is the report")
a.calm()

v.on_key(a, press("PGDN"))
check(v.i == 39, "PageDown at the bottom clamps, it does not wrap (got %d)" % v.i)
a.calm()

v.on_key(a, press("HOME"))
check(v.i == 0, "Home is the first entry (got %d)" % v.i)
check(not a.escaped(), "...and the view is still open")
a.calm()

v.on_key(a, press("PGUP"))
check(v.i == 0, "PageUp at the top clamps to the first (got %d)" % v.i)
a.calm()

v.on_key(a, press("END-ss3"))
check(v.i == 39, "the SS3 form of End works too (a dashboard outside tmux)")
a.calm()
v.on_key(a, press("HOME-ss3"))
check(v.i == 0, "...and of Home")
a.calm()

# esc has to keep meaning esc: this lane must not have taken the key away.
v.on_key(a, "\x1b")
check(a.left_to == "main", "and a REAL esc still leaves the view, as it must")
a.calm()

v.rows = []
v.i = 0
for k in ("PGDN", "END", "HOME", "PGUP"):
    v.on_key(a, press(k))
check(v.i == 0 and not a.escaped(), "an empty table: the keys do nothing, safely")
a.calm()

# ------------------------------------------------------------------- main
print("== the main dashboard list")
a = Recorder()
m = MainView(a)
m.sids = ["s%02d" % i for i in range(30)]
m.cursor = m.sids[0]
m._page = 8

m.on_key(a, press("PGDN"))
check(m.cursor == "s08", "PageDown moves one page (got %s)" % m.cursor)
check(not a.escaped(), "...and NO muxtopus menu opened -- the other half of the report")
a.calm()

m.on_key(a, press("END"))
check(m.cursor == "s29", "End is the last row (got %s)" % m.cursor)
check(not a.escaped(), "...and no menu")
a.calm()

m.on_key(a, press("PGDN"))
check(m.cursor == "s29", "clamped at the bottom")
a.calm()

m.on_key(a, press("HOME"))
check(m.cursor == "s00", "Home is the first row")
check(not a.escaped(), "...and no menu")
a.calm()

m.on_key(a, press("PGUP"))
check(m.cursor == "s00", "clamped at the top")
a.calm()

m.on_key(a, "\x1b")
check(a.opened == "mux", "and a REAL esc still opens the muxtopus menu")
a.calm()

m.sids = []
m.cursor = ""
for k in ("PGDN", "END", "HOME", "PGUP"):
    m.on_key(a, press(k))
check(m.cursor == "" and not a.escaped(), "no sessions at all: safe")
a.calm()

# -------------------------------------------------------------- handovers
print("== the handovers tab, which has the same UP/DOWN pair")
a = Recorder()
# Its filters are settings, and the view reads them as it is built, so the
# module's register() has to have declared them -- the same order the
# dashboard starts in.
dashboard.views.handovers.register(a)
h = a.view_of("handovers")
h.rows = rows(25)
h._page = 6
h.i = 0
h.on_key(a, press("PGDN"))
check(h.i == 6, "PageDown moves one page (got %d)" % h.i)
check(not a.escaped(), "...and the tab is still open")
a.calm()
h.on_key(a, press("END"))
check(h.i == 24 and not a.escaped(), "End is the last row, and the tab stays")
a.calm()
h.on_key(a, press("HOME"))
check(h.i == 0 and not a.escaped(), "Home is the first row, and the tab stays")
a.calm()
h.on_key(a, "\x1b")
check(a.left_to == "main", "and a real esc still goes back")
a.calm()

# --------------------------------------------------------------- insights
print("== the insights breakdown, where End is worth the most")
a = Recorder()
n = InsightsView(a)
n._page = 12
n.report = lambda: {"breakdown": [{"key": "k%d" % i} for i in range(500)]}
n.cur = 0
n.on_key(a, press("PGDN"))
check(n.cur == 12, "PageDown moves one page (got %d)" % n.cur)
a.calm()
n.on_key(a, press("END"))
check(n.cur == 499, "End reaches row 500 in ONE keypress (got %d)" % n.cur)
check(not a.escaped(), "...and the screen is still up")
a.calm()
n.on_key(a, press("HOME"))
check(n.cur == 0 and not a.escaped(), "Home comes back to the top")
a.calm()

# ------------------------------------------------------- the App's own lists
print("== the menu, the picker and the options table -- the same four keys")
a = App(2.0, Console(width=140, height=40, force_terminal=False))
items = [{"label": "row %d" % i} for i in range(20)]
items[0] = {"label": "----", "sep": True}
items[5] = {"label": "not now", "disabled": "no session"}
a.add_menu("big", lambda: items)
a.open_menu("big")
a._menu_page = 7
a.menu["i"] = 1
a.route_key(press("PGDN"))
check(at(a.menu) == 8, "PageDown pages an open menu (got %s)" % at(a.menu))
a.route_key(press("END"))
check(at(a.menu) == 19, "End is its last row (got %s)" % at(a.menu))
a.route_key(press("HOME"))
check(at(a.menu) == 1, "Home is its first SELECTABLE row, not the separator")
if a.menu:
    a.menu["i"] = 12
a.route_key(press("PGUP"))
check(at(a.menu) == 4,
      "PageUp landing on the disabled row 5 keeps going the way it moved (-> 4)")
check(a.menu is not None, "and the menu never closed")

a.menu = None
a.picker = {"options": ["a", "b", "c", "d"], "i": -1, "fn": lambda c: ""}
a.route_key(press("END"))
check(at(a.picker) == 3, "End picks the last option (got %s)" % at(a.picker))
a.route_key(press("HOME"))
check(at(a.picker) == 0, "Home picks the first")
a.route_key(press("PGUP"))
check(at(a.picker) == 0, "and PageUp clamps there")
check(a.picker is not None, "the picker never cancelled")

a.picker = None
v = ScheduleView(a)
opts = [{"head": "SECTION"}] + [{"label": "o%d" % i, "opt": {}} for i in range(9)]
v.option_rows = lambda: opts
a.modal = {"i": 1, "key": v.options_key, "mode": "reopen",
           "on": {}, "fn": lambda st: ""}
a.route_key(press("END"))
check(at(a.modal) == 9, "End in the options table (got %s)" % at(a.modal))
a.route_key(press("HOME"))
check(at(a.modal) == 1, "Home skips its heading row")
check(a.modal is not None, "and the table was never cancelled")

# ------------------------------------------------- what used to quit a view
print("== and the keys that were never asked for but had the same bug")
a = Recorder()
v = ScheduleView(a)
v.rows = rows(5)
v.i = 2
for seq, why in ((b"\x1b[15~", "F5"), (b"\x1b[2~", "Insert"),
                 (b"\x1b[3~", "Delete"), (b"\x1b[Z", "shift-Tab")):
    key = (old_decode_key if OLD else d.decode_key)(seq)
    claimed = v.on_key(a, key)
    check(not a.escaped() and v.i == 2 and not claimed,
          "%s does nothing at all, and the view stays" % why)
    a.calm()

print()
if OLD:
    # Inverted: run against the old decoder, every assertion above SHOULD
    # fail, and a green run here would mean the counterfactual proves nothing.
    print("counterfactual: %d of %d assertions still pass against the OLD "
          "decode_key" % (PASSES, PASSES + FAILS))
    print("the bug is reproduced" if FAILS else
          "NOTHING FAILED -- this test does not prove what it says it does")
    sys.exit(0 if FAILS else 1)
print("%d assertions passed" % PASSES if not FAILS
      else "%d passed, %d FAILED" % (PASSES, FAILS))
sys.exit(1 if FAILS else 0)
