#!/usr/bin/env python3
"""Settings ▸ Columns and Settings ▸ Panels: the rows, and what enter does.

Run it:  .venv/bin/python tests/test_columns_menu.py   (no pytest; needs rich)

A temporary HOME and config, as tests/test_tabs_hidden.py has: these menus
WRITE dashboard.conf and this test must never reach the real one.

What is promised:
  * the rows SAY THE STATE, and the state is the frame's, not the file's:
    a column off the right of the table behind the menu reads "off-screen
    right (shift-→)";
  * enter cycles shown → pinned → hidden → shown, and the value round-trips
    through dashboard.conf -- read back from disk, not from a cache;
  * unpinning the last column stays unpinned, which is what the NONE
    sentinel is for: an empty value deletes the key, and a deleted key means
    the DEFAULT rather than nothing;
  * the desktop-extras row appears ONLY while the system line is hidden, and
    calls the main view's own toggle_extras;
  * a bad item is refused with its text, and a name for a column that is not
    in this frame is kept (that is ACCOUNT under a filtered lanes table);
  * COLUMNS here does not drift from the view's specs: every name listed,
    ACCOUNT aside, is a column of the real wide frame.

toggle_extras is REPLACED for the one check that presses it: the real one
runs deck-ram.sh against this machine, which a test may not do. What is
being tested is that the row reaches the main view's method at all, which
is the whole reason the row exists.
"""
import os
import pathlib
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="mxcolmenu-")
os.environ["HOME"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP + "/config"
os.environ["XDG_STATE_HOME"] = TMP + "/state"
os.environ["MUXTOPUS_CONFIG"] = TMP + "/config/muxtopus/config"
os.environ["CLAUDE_CONFIG_DIR"] = TMP + "/claude"
os.environ.pop("TMUX", None)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from rich.console import Console        # noqa: E402

import muxsettings                      # noqa: E402
from dashboard.app import App           # noqa: E402
from dashboard import columns as columnsmod         # noqa: E402
from dashboard.core import PROFILE                  # noqa: E402
from dashboard.data import ClaudeSession            # noqa: E402
from dashboard.views import main as mainmod         # noqa: E402
from dashboard.menus import columns as menumod      # noqa: E402

FAILS = PASSES = 0


def check(cond, what):
    global FAILS, PASSES
    if cond:
        PASSES += 1
        print("  ok   " + what)
    else:
        FAILS += 1
        print("  FAIL " + what)


def session(sid, window, ctx):
    return ClaudeSession(sid=sid, window=window, pane="", ver="1", ctx=ctx,
                         state="working", reset="", action="", spent=1000,
                         model="opus", idle=60, job="bg", cwd=TMP, pid=os.getpid())


SESSIONS = [session("aaaaaaaa-1", "lane-one", 300000)]
mainmod.claude_sessions = lambda: (list(SESSIONS), 1.0)
mainmod.drop_dead = lambda sessions, procs: sessions


def fresh(width=200, height=60):
    app = App(2.0, Console(width=width, height=height, force_terminal=False))
    view = mainmod.MainView(app)
    app.add_view(view)
    menumod.register(app)
    for key in (columnsmod.HIDDEN_KEY, columnsmod.PINNED_KEY, columnsmod.PANELS_KEY):
        muxsettings.put(key, "", PROFILE)
    columnsmod.forget()
    view.build_main()
    return app, view


def rows(app, kind):
    app.menu = {"kind": kind, "i": 0}
    return app.menu_entries()


def row(app, kind, starts):
    return next(it for it in rows(app, kind)
                if it.get("label", "").startswith(starts))


def conf():
    return muxsettings.dashboard_conf_path(PROFILE).read_text()


# ========================================================== the column rows
print("== one row per named column, both tables, in list order")
app, view = fresh()
items = [it for it in rows(app, "columns") if "·" in it.get("label", "")
         and not it.get("sep")]
labels = [it["label"] for it in items]
check(len(labels) == len(menumod.COLUMNS["lanes"]) + len(menumod.COLUMNS["claude"]),
      "%d rows, one per named column" % len(labels))
check(labels[0].startswith("lanes · PORT") and labels[-1].startswith("claude · RESUMED"),
      "lanes first, then claude, each in the table's own order")
check(not any(l.startswith("lanes ·  ") for l in labels),
      'the unnamed marker column is never listed')
check("hidden wins" in app.menu_hint() and "esc back" in app.menu_hint(),
      "the hint states the rule: %r" % app.menu_hint())

print("== the rows say what is true THIS frame")
check("WINDOW   pinned" in row(app, "columns", "claude · WINDOW")["label"],
      "WINDOW is pinned by default: %r" % row(app, "columns", "claude · WINDOW")["label"])
check("on screen" in row(app, "columns", "claude · SPENT")["label"],
      "at 200 columns SPENT is on screen")

narrow, nview = fresh(width=80)
lab = row(narrow, "columns", "claude · RESUMED")["label"]
check("off-screen right (shift-→)" in lab,
      "at 80 columns RESUMED says which side it is off: %r" % lab)
nview.cursor = SESSIONS[0].sid
for _ in range(3):
    nview.scroll_columns(1)
nview.build_main()
lab = row(narrow, "columns", "claude · MON")["label"]
check("off-screen left (shift-←)" in lab,
      "...and after three shift-→ MON says it went left: %r" % lab)

print("== ACCOUNT is listed even when the lanes table has not got it")
app, view = fresh()
view.lanes_all = False
view.build_main()
lab = row(app, "columns", "lanes · ACCOUNT")["label"]
check("only with f: all accounts" in lab, "the row says when it appears: %r" % lab)

print("== COLUMNS does not drift from the view's specs")
wide, wview = fresh(width=260)
wview.lanes_all = True
wview.build_main()
plans = wview.column_plans()
drift = [(t, n) for t in columnsmod.TABLES for n in menumod.COLUMNS[t]
         if n not in plans[t][0] + plans[t][1] + plans[t][2]]
check(not drift, "every listed column is a column of the real frame (%r)" % drift)

# ============================================================== enter cycles
print("== enter cycles shown -> pinned -> hidden -> shown, through the file")
app, view = fresh()
msg = row(app, "columns", "claude · SPENT")["act"]()
check("SPENT pinned" in msg, "shown -> pinned: %r" % msg)
check('DASHBOARD_COLUMNS_PINNED="' in conf() and "claude:SPENT" in conf(),
      "written to dashboard.conf")
columnsmod.forget()
check("SPENT" in columnsmod.pinned_columns(PROFILE)["claude"],
      "...and read back from disk")
check(row(app, "columns", "claude · SPENT")["act"]().endswith("dashboard.conf")
      and "SPENT" in columnsmod.hidden_columns(PROFILE)["claude"],
      "pinned -> hidden")
check("SPENT" not in columnsmod.pinned_columns(PROFILE)["claude"],
      "...and it left the pinned list in the same breath: never both")
view.build_main()
check("SPENT" not in view.column_plans()["claude"][0],
      "...and the frame behind the menu stopped drawing it")
row(app, "columns", "claude · SPENT")["act"]()
check("SPENT" not in columnsmod.hidden_columns(PROFILE)["claude"]
      and "SPENT" not in columnsmod.pinned_columns(PROFILE)["claude"],
      "hidden -> shown: out of both lists")
check(row(app, "columns", "claude · SPENT").get("stay") is True,
      "the menu stays open")

print("== unpinning the last column STAYS unpinned")
app, view = fresh()
row(app, "columns", "claude · WINDOW")["act"]()    # pinned -> hidden
row(app, "columns", "lanes · LANE")["act"]()       # pinned -> hidden
row(app, "columns", "claude · WINDOW")["act"]()    # hidden -> shown
row(app, "columns", "lanes · LANE")["act"]()       # hidden -> shown
columnsmod.forget()
pinned = columnsmod.pinned_columns(PROFILE)
check(not pinned["lanes"] and not pinned["claude"],
      "nothing is pinned, and the default did not come back: %r" % pinned)
check('DASHBOARD_COLUMNS_PINNED="none"' in conf(),
      "the file says so in a word, because an empty value would delete the line")

print("== the title counts")
app, view = fresh()
row(app, "columns", "claude · RESUMED")["act"]()   # shown -> pinned
row(app, "columns", "claude · WOUND")["act"]()     # shown -> pinned
row(app, "columns", "claude · WOUND")["act"]()     # pinned -> hidden
app.menu = {"kind": "columns", "i": 0}
t = app.menu_title()
check("1 hidden" in t and "3 pinned" in t,
      "columns title counts both: %r (LANE, WINDOW, RESUMED pinned)" % t)

# ================================================================== panels
print("== the panel rows")
app, view = fresh()
items = [it for it in rows(app, "panels") if it.get("on") is not None]
check([it["label"].split()[0] for it in items] == list(columnsmod.PANELS),
      "four rows, deck lanes uncommitted system")
check("the claude/playwright/home/extras line" in
      row(app, "panels", "system")["label"], "each says what it holds")
check(all(it["on"] for it in items), "all shown to begin with")

print("== enter hides one, through the file")
msg = row(app, "panels", "uncommitted")["act"]()
check("uncommitted hidden" in msg, "the notice: %r" % msg)
check('DASHBOARD_PANELS_HIDDEN="uncommitted"' in conf(), "written to dashboard.conf")
columnsmod.forget()
check(columnsmod.hidden_panels(PROFILE) == {"uncommitted"}, "read back from disk")
sections = view.build_main()
check("uncommitted" not in [n for n, _p in sections], "and the frame drops it")
row(app, "panels", "uncommitted")["act"]()
check(not columnsmod.hidden_panels(PROFILE), "and back again")

print("== the extras row is there only while system is hidden")
app, view = fresh()
check(not any("Desktop extras" in it.get("label", "") for it in rows(app, "panels")),
      "with the system line shown there is no extras row")
row(app, "panels", "system")["act"]()
extras = [it for it in rows(app, "panels") if "Desktop extras" in it.get("label", "")]
check(len(extras) == 1, "hiding the system line puts one there")
check("the system line is hidden, so the action is here" in extras[0]["label"],
      "...and the row says why: %r" % extras[0]["label"])
called = []
view.toggle_extras = lambda: called.append(True) or "extras: done"
check(extras[0]["act"]() == "extras: done" and called,
      "enter on it reaches the main view's toggle_extras")
row(app, "panels", "system")["act"]()
check(not any("Desktop extras" in it.get("label", "") for it in rows(app, "panels")),
      "showing the line again takes the row away")

# ============================================================== the values
print("== the values themselves")
check(muxsettings.put(columnsmod.HIDDEN_KEY, "claude", PROFILE) != "",
      "an item with no table is refused")
err = muxsettings.put(columnsmod.HIDDEN_KEY, "sched:TITLE", PROFILE)
check("sched:TITLE" in err, "the refusal carries the item's own text: %r" % err)
check(muxsettings.put(columnsmod.PANELS_KEY, "claude", PROFILE) != "",
      "the claude table cannot be hidden")
check(muxsettings.put(columnsmod.HIDDEN_KEY, "lanes:ACCOUNT", PROFILE) == "",
      "a name for a column absent from this frame is KEPT")
columnsmod.forget()
app, view = fresh()
muxsettings.put(columnsmod.HIDDEN_KEY, "lanes:ACCOUNT,claude:NOSUCH", PROFILE)
columnsmod.forget()
row(app, "columns", "claude · IDLE")["act"]()
check("NOSUCH" in columnsmod.hidden_columns(PROFILE)["claude"],
      "...and kept when another row is toggled, like a tab of a module that did not load")

print("\n%d passed, %d failed" % (PASSES, FAILS))
sys.exit(1 if FAILS else 0)
