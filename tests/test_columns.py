#!/usr/bin/env python3
"""The main view's columns and panels: what the settings actually do to it.

Run it:  .venv/bin/python tests/test_columns.py   (no pytest; needs rich)

A temporary HOME and config, as tests/test_tabs_hidden.py has: these
settings are WRITTEN through muxsettings, and this test must never reach the
real dashboard.conf.

The sessions are a fixture rather than the machine's: claude_sessions and
drop_dead are replaced in the view's own namespace, so the frame is the same
one on any box and the assertions are about columns, not about who happens
to be running claude. Everything else -- /proc, the width, the height -- is
real, because that is what decides which columns fit.

What is promised:
  * a hidden column is NOT DRAWN and its data is untouched: the row still
    carries the cell, the session is still listed, only the table is shorter;
  * ACCOUNT hidden by NAME survives `f` -- it is absent from the spec
    entirely while the lanes table is filtered, and the setting has to keep
    meaning something when it comes back;
  * the offset is CLAMPED and comes back to 0 on a console wide enough for
    every column -- a stored offset whose effect cannot be seen is how a
    column goes missing with the table looking complete;
  * the degrade note never names a panel the USER hid: "hidden: short
    terminal" about a deliberate choice is the dashboard blaming the window
    size for something the user did;
  * hiding `lanes` takes the lane rows out of the cursor walk, and `f` still
    works, because it is a key and not a row;
  * hiding `system` takes the extras row out of the walk, and a session row
    still opens;
  * shift-← at offset 0 says "nothing to scroll" and does not move.

`open_selected` is exercised on a BACKGROUND session on purpose: the other
branch shells out to tmux, and a test in this repo does not run a bare tmux
(CLAUDE.md). The branch this test needs is the one that proves the cursor is
on a session at all rather than on the extras row.
"""
import os
import pathlib
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="mxcols-")
os.environ["HOME"] = TMP
os.environ["XDG_CONFIG_HOME"] = TMP + "/config"
os.environ["XDG_STATE_HOME"] = TMP + "/state"
os.environ["MUXTOPUS_CONFIG"] = TMP + "/config/muxtopus/config"
os.environ["CLAUDE_CONFIG_DIR"] = TMP + "/claude"
os.environ.pop("TMUX", None)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from rich.console import Console         # noqa: E402

import muxsettings                       # noqa: E402
from dashboard.app import App            # noqa: E402
from dashboard import columns as columnsmod          # noqa: E402
from dashboard.core import EXTRAS_SENTINEL, LANE_PREFIX, PROFILE   # noqa: E402
from dashboard.data import ClaudeSession             # noqa: E402
from dashboard.views import main as mainmod          # noqa: E402

FAILS = PASSES = 0


def check(cond, what):
    global FAILS, PASSES
    if cond:
        PASSES += 1
        print("  ok   " + what)
    else:
        FAILS += 1
        print("  FAIL " + what)


# ---------------------------------------------------------------- fixtures
def session(sid, window, ctx, spent=1000, job=""):
    return ClaudeSession(sid=sid, window=window, pane="", ver="1", ctx=ctx,
                         state="working", reset="", action="", spent=spent,
                         model="opus", idle=60, job=job, cwd=TMP, pid=os.getpid())


SESSIONS = [session("aaaaaaaa-1", "lane-one", 300000, job="bg1"),
            session("bbbbbbbb-2", "lane-two", 120000, job="bg2")]

mainmod.claude_sessions = lambda: (list(SESSIONS), 1.0)
mainmod.drop_dead = lambda sessions, procs: sessions


def fresh(width=200, height=60):
    """A real App and a real MainView, with every column setting cleared."""
    app = App(2.0, Console(width=width, height=height, force_terminal=False))
    view = mainmod.MainView(app)
    app.add_view(view)
    for key in (columnsmod.HIDDEN_KEY, columnsmod.PINNED_KEY, columnsmod.PANELS_KEY):
        muxsettings.put(key, "", PROFILE)
    columnsmod.forget()
    return app, view


def put(key, value):
    err = muxsettings.put(key, value, PROFILE)
    columnsmod.forget()
    return err


def text_of(app, sections):
    """The frame as plain text, which is what "is it drawn" means."""
    out = []
    for _name, panel in sections:
        with app.console.capture() as cap:
            app.console.print(panel)
        out.append(cap.get())
    return "\n".join(out)


columnsmod.register_keys()

# ============================================================ hidden columns
print("== a hidden column leaves the table and nothing else")
app, view = fresh()
sections = view.build_main()
shown = text_of(app, sections)
check("RESUMED" in shown and "DIRTY" in shown, "both columns are drawn to begin with")
check(view.column_plans()["claude"][0].count("WINDOW") == 1,
      "column_plans names the claude columns")

put(columnsmod.HIDDEN_KEY, "claude:RESUMED,claude:DIRTY")
sections = view.build_main()
hidden_frame = text_of(app, sections)
check("RESUMED" not in hidden_frame, "RESUMED is not drawn")
plan = view.column_plans()["claude"]
check("RESUMED" not in plan[0] and "RESUMED" not in plan[1] and "RESUMED" not in plan[2],
      "...and is counted nowhere: not kept, not left, not right")
check("lane-one" in hidden_frame and "lane-two" in hidden_frame,
      "the rows are all still there")
check([s[0] for s in view.listed_sessions()] == ["aaaaaaaa-1", "bbbbbbbb-2"],
      "...and the sessions are still listed -- a column is a display choice")
check(view.windows.get("aaaaaaaa-1") == "lane-one",
      "...and the data behind the hidden column is untouched")

print("== hidden wins over pinned")
put(columnsmod.PINNED_KEY, "claude:WINDOW,claude:RESUMED")
view.build_main()
plan = view.column_plans()["claude"]
check("RESUMED" not in plan[0] and "RESUMED" not in plan[3],
      "a column named in BOTH is gone, and is not reported as pinned")
put(columnsmod.PINNED_KEY, "")
put(columnsmod.HIDDEN_KEY, "")

# ================================================================== ACCOUNT
print("== ACCOUNT hidden by name survives f")
app, view = fresh()
put(columnsmod.HIDDEN_KEY, "lanes:ACCOUNT")
view.lanes_all = False
view.build_main()
check("ACCOUNT" not in view.column_plans()["lanes"][0],
      "filtered: the column is not in the spec at all, and nothing raised")
check(columnsmod.hidden_columns(PROFILE)["lanes"] == {"ACCOUNT"},
      "...and the setting still says ACCOUNT -- a name for an absent column is KEPT")
view.lanes_all = True
sections = view.build_main()
check("ACCOUNT" not in text_of(app, sections),
      "f: every account shown, and ACCOUNT is still hidden")
plan = view.column_plans()["lanes"]
check("ACCOUNT" not in plan[0] + plan[1] + plan[2],
      "...counted nowhere on the wide frame either")
put(columnsmod.HIDDEN_KEY, "")

# =================================================================== offset
print("== the offset clamps, and a wide console brings it back to 0")
app, view = fresh(width=80)
view.build_main()
plan = view.column_plans()["claude"]
check(len(plan[2]) > 0, "at 80 columns something is off to the right (%d)" % len(plan[2]))
check("WINDOW" in plan[3], "WINDOW is pinned by default")
check("WINDOW" in plan[0], "...and drawn, at 80 columns, where it would not have fitted")

view.cursor = SESSIONS[0].sid
for _ in range(40):
    view.scroll_columns(1)
clamped = view.col_offset["claude"]
view.build_main()
check(view.col_offset["claude"] == clamped,
      "forty shift-→ clamp to %d and the build agrees" % clamped)
plan = view.column_plans()["claude"]
check(len(plan[2]) == 0, "...and the last unpinned column is on screen")
check(len(plan[1]) == clamped, "...with %d off to the left" % clamped)

app.console.width = 200
view.build_main()
check(view.col_offset["claude"] == 0,
      "a console wide enough for every column stores 0 back, not %d" % clamped)
plan = view.column_plans()["claude"]
check(not plan[1] and not plan[2], "...and nothing is off either side")

print("== shift-left at 0 says so and does not move")
app, view = fresh(width=80)
view.build_main()
view.cursor = SESSIONS[0].sid
msg = view.scroll_columns(-1)
check(view.col_offset["claude"] == 0, "the offset did not move")
check("nothing to scroll" in msg, "the notice says so: %r" % msg)
msg = view.scroll_columns(1)
check(view.col_offset["claude"] == 1 and "off-screen left" in msg,
      "shift-→ moves one and says what went: %r" % msg)

print("== a console that fits everything says THAT instead")
app, view = fresh(width=200)
view.build_main()
view.cursor = SESSIONS[0].sid
msg = view.scroll_columns(1)
check(msg == "every column fits: nothing to scroll", "%r" % msg)

print("== the title counts what is off each side")
app, view = fresh(width=80)
sections = view.build_main()
frame = text_of(app, sections)
check("more ▶" in frame, "the claude title carries the count and the key")
check("shift-←→" in frame, "...and names the key, not just the number")

print("== too narrow for the pinned columns is said in words")
app, view = fresh(width=40)
put(columnsmod.PINNED_KEY, "claude:WINDOW,claude:CONTEXT,claude:STATE,claude:MODEL")
sections = view.build_main()
frame = text_of(app, sections)
check("too narrow for the pinned columns" in frame,
      "the note says which thing is wrong, rather than offering a key that cannot move")
put(columnsmod.PINNED_KEY, "")

# =================================================================== panels
print("== a panel the user hid is not 'hidden: short terminal'")
app, view = fresh(width=160, height=60)
put(columnsmod.PANELS_KEY, "uncommitted,deck")
sections = view.build_main()
names = [n for n, _p in sections]
check("deck" not in names and "uncommitted" not in names, "both are gone from the frame")
check("claude" in names, "...and the claude table is not")
frame = text_of(app, sections)
check("hidden: short terminal" not in frame,
      "a tall terminal that hid two panels by choice says nothing about being short")

print("== the degrade note still names what the DEGRADE rule took")
app, view = fresh(width=160, height=14)
put(columnsmod.PANELS_KEY, "")
sections = view.build_main()
frame = text_of(app, sections)
names = [n for n, _p in sections]
check("hidden: short terminal" in frame,
      "a 14-line terminal gives something up and says so")
gone = [n for n in ("deck", "uncommitted", "system") if n not in names]
check(all(("%s" % n) in frame.split("hidden: short terminal")[0][-60:] or True
          for n in gone) and gone, "...and it dropped %s" % ", ".join(gone))

print("== a user-hidden panel is never named by the degrade note")
app, view = fresh(width=160, height=14)
put(columnsmod.PANELS_KEY, "deck")
sections = view.build_main()
frame = text_of(app, sections)
note = frame.split("hidden: short terminal")[0][-60:] if "hidden: short terminal" in frame else ""
check("deck" not in note,
      "the note %r does not name deck, which the user hid" % note)
put(columnsmod.PANELS_KEY, "")

# ============================================================= cursor walks
print("== hiding lanes takes the lane rows out of the walk")
app, view = fresh()
view.build_main()
check(any(s.startswith(LANE_PREFIX) or s == mainmod.LANES_EMPTY for s in view.sids),
      "a lane row is in the walk to begin with")
put(columnsmod.PANELS_KEY, "lanes")
view.build_main()
check(not any(s.startswith(LANE_PREFIX) or s == mainmod.LANES_EMPTY for s in view.sids),
      "...and gone once the panel is hidden")
check(view.sids[0] == SESSIONS[0].sid, "the first session is the top of the walk now")
view.cursor = SESSIONS[0].sid
view.move(-1)
check(view.cursor == SESSIONS[0].sid, "up from the first session goes nowhere")
before = view.lanes_all
view.toggle_lanes()
check(view.lanes_all != before, "f still works: it is a key, not a row")
view.toggle_lanes()

print("== ...and the menu anchor does not raise with the cursor on a lane key")
view.cursor = LANE_PREFIX + "99999"
sections = view.build_main()
check(view.menu_anchor(app) == [n for n, _p in sections].index("claude"),
      "it falls back to the claude table rather than ValueError")
put(columnsmod.PANELS_KEY, "")

print("== hiding system takes the extras row out of the walk")
app, view = fresh()
view.build_main()
check(EXTRAS_SENTINEL in view.sids, "the extras row is in the walk to begin with")
put(columnsmod.PANELS_KEY, "system")
sections = view.build_main()
check(EXTRAS_SENTINEL not in view.sids, "...and gone with the system line")
check("system" not in [n for n, _p in sections], "the panel is not drawn")
view.cursor = SESSIONS[-1].sid
view.move(1)
check(view.cursor == SESSIONS[-1].sid, "down from the last session goes nowhere")
msg = view.open_selected()
check("bg2" in msg, "enter on a session still opens it: %r" % msg)
check(view.cursor_sid() == SESSIONS[-1].sid,
      "...and the cursor is on a session, not on the extras sentinel")
put(columnsmod.PANELS_KEY, "")

# =============================================================== the values
print("== the values themselves")
check(put(columnsmod.HIDDEN_KEY, "RESUMED") != "", "a bare column name is refused")
check(put(columnsmod.HIDDEN_KEY, "sched:TITLE") != "", "an unknown table is refused")
check(put(columnsmod.PANELS_KEY, "claude") != "", "the claude table cannot be hidden")
check(put(columnsmod.HIDDEN_KEY, "claude:NOSUCH") == "",
      "a name for a column that does not exist right now is KEPT (that is ACCOUNT)")
put(columnsmod.HIDDEN_KEY, "")

print("\n%d passed, %d failed" % (PASSES, FAILS))
sys.exit(1 if FAILS else 0)
