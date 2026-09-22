#!/usr/bin/env python3
"""Settings ▸ Tabs -- hiding a tab, and what it must NOT do.

Run it:  .venv/bin/python tests/test_tabs_hidden.py   (no pytest; needs rich)

A temporary HOME and config: the menu WRITES dashboard.conf, and this test
must never reach the real one.

What is promised:
  * a hidden tab leaves the strip and the ←→ cycle, and it is written to
    DASHBOARD_TABS_HIDDEN and read back from disk;
  * nothing becomes unreachable: the group's key still gets in, a hidden
    tab's key lands on the first shown tab (or on itself when all are
    hidden), and "Open ... once" goes to it without unhiding it -- after
    which it is in the strip, marked, and ←→ leaves it;
  * HIDDEN WINS OVER LOCKED: the six a narrow strip keeps are the first
    six SHOWN, so hiding one of the first six lets the seventh in;
  * a name that is not a view name is refused, and a name for a view that
    did not load is kept.
"""
import os
import pathlib
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="mxtabs-")
os.environ["HOME"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP + "/config"
os.environ["XDG_STATE_HOME"] = TMP + "/state"
os.environ["MUXTOPUS_CONFIG"] = TMP + "/config/muxtopus/config"
os.environ["CLAUDE_CONFIG_DIR"] = TMP + "/claude"
os.environ.pop("TMUX", None)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402
from rich.panel import Panel      # noqa: E402
from rich.text import Text        # noqa: E402

import muxsettings                # noqa: E402
from dashboard.app import App, View   # noqa: E402
from dashboard.core import PROFILE    # noqa: E402
from dashboard.menus import tabs as tabsmod   # noqa: E402

FAILS = PASSES = 0


def check(cond, what):
    global FAILS, PASSES
    if cond:
        PASSES += 1
        print("  ok   " + what)
    else:
        FAILS += 1
        print("  FAIL " + what)


class Tab(View):
    def __init__(self, name, order, key=None):
        self.name, self.order, self.key, self.group = name, order, key, "s"

    def tab_label(self, app):
        return "%s tab" % self.name

    def build(self, app):
        return [(self.name, Panel(Text(self.name)))]


class Main(View):
    name = "main"


def fresh(width=160):
    a = App(2.0, Console(width=width, height=30, force_terminal=False))
    a.add_view(Main())
    for i, n in enumerate(["sched", "handovers", "c3", "c4", "c5", "c6", "c7", "c8"]):
        a.add_view(Tab(n, i, key="s" if n == "sched" else None))
    tabsmod.register(a)
    # One config file on disk for every App in this process: each scenario
    # starts with nothing hidden.
    muxsettings.put("DASHBOARD_TABS_HIDDEN", "", PROFILE)
    return a


def names(a):
    return [v.name for v in a.tabs_of(a.view_of())]


def row(a, starts):
    return next(it for it in a.menu_entries() if it.get("label", "").startswith(starts))


a = fresh()
print("== the menu: one row per tab, reached from Settings")
a.menu = {"kind": "tabs", "i": 0}
rows = [it for it in a.menu_entries() if "(tab of s)" in it.get("label", "")]
check(len(rows) == 8 and all(r["on"] for r in rows), "eight rows, all SHOWN")
# ON THE DESCRIPTION, not the label, since the label sweep: the row says
# which tab it is and whether it is SHOWN (state), and why that matters on a
# narrow strip is the sentence drawn under the cursor.
check("locked" in row(a, "c6")["desc"] and "scrolls" in row(a, "c7")["desc"],
      "the first six say locked, the seventh says it scrolls")
check("hidden wins" in a.menu_hint(), "the hint says which wins: %r" % a.menu_hint())

print("== hiding one")
msg = row(a, "handovers")["act"]()
check("handovers hidden" in msg, "the notice: %r" % msg)
conf = muxsettings.dashboard_conf_path(PROFILE).read_text()
check('DASHBOARD_TABS_HIDDEN="handovers"' in conf, "written to dashboard.conf")
a.forget_hidden()
check(a.hidden_tabs() == {"handovers"}, "and read back from disk")
a.menu = None
a.switch_to("sched")
check("handovers" not in names(a), "gone from the strip")
seen = []
for _ in range(8):
    a.route_key("RIGHT")
    seen.append(a.view)
check("handovers" not in seen and len(set(seen)) == 7, "→ walks the seven shown, never it")
sub = a.build().renderables[0].subtitle
check("1 hidden" in sub, "the strip's subtitle counts it: %r" % sub)

print("== hidden wins over locked")
narrow = fresh(width=30)
narrow.switch_to("sched")
before = narrow.fit_strip(narrow.view_of())
row_ = [it for it in (narrow.open_menu("tabs") or narrow.menu_entries())
        if it.get("label", "").startswith("c3")][0]
row_["act"]()
narrow.menu = None
after = narrow.fit_strip(narrow.view_of())
t_before = [v.name for v in narrow.group_tabs(narrow.view_of())]
t_after = names(narrow)
check("c7" not in [t_before[i] for i in before.shown][:6],
      "before: c7 is not among the locked six")
check([t_after[i] for i in range(6)] == ["sched", "handovers", "c4", "c5", "c6", "c7"]
      and all(i in after.shown for i in range(6)),
      "after hiding c3: the locked six are the first six SHOWN, c7 among them")

print("== nothing becomes unreachable")
b = fresh()
b.open_menu("tabs")
row(b, "sched")["act"]()
b.menu = None
check(b.open_view_key("s") and b.view == "handovers",
      "s, with its own tab hidden, opens the first SHOWN tab of the group")
b.switch_to("main")
b.open_menu("tabs")
for n in ["handovers", "c3", "c4", "c5", "c6", "c7", "c8"]:
    row(b, n)["act"]()
b.menu = None
check(b.open_view_key("s") and b.view == "sched",
      "every tab hidden: s still opens its own view")
check(names(b) == ["sched"], "...alone in the strip, because it is where you are")
check("(hidden)" in b.fit_strip(b.view_of()).markup, "...and marked hidden")
b.switch_to("main")
b.open_menu("tabs")
row(b, "sched")["act"]()          # sched shown again; the rest still hidden
opener = row(b, "Open c5 once")
opener["act"]()
check(b.view == "c5" and b.menu is None, "Open c5 once goes to it and closes the menu")
check("c5" in b.hidden_tabs(), "...without unhiding it")
check(names(b) == ["sched", "c5"], "the strip holds it while you are on it")
b.route_key("RIGHT")
check(b.view == "sched", "→ leaves it for a shown tab")
b.route_key("RIGHT")
check(b.view == "sched", "...and it is gone from the cycle once left")

print("== the value")
check(muxsettings.put("DASHBOARD_TABS_HIDDEN", "a b", PROFILE) != "",
      "a name with a space is refused")
c = fresh()
check(muxsettings.put("DASHBOARD_TABS_HIDDEN", "gone-module,c3", PROFILE) == "",
      "a name for a view that is not loaded is accepted")
c.forget_hidden()
c.open_menu("tabs")
row(c, "c4")["act"]()
check("gone-module" in c.hidden_tabs(), "...and kept when another tab is toggled")

print("\n%d passed, %d failed" % (PASSES, FAILS))
sys.exit(1 if FAILS else 0)
