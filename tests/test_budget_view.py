#!/usr/bin/env python3
"""The budget guard's dashboard half: `b` and Settings ▸ Budget ▸.

    .venv/bin/python tests/test_budget_view.py

WHAT IS HELD. dashboard/views/budget.py draws ONLY what the daemon wrote --
the `budget` verdict, status.tsv, sched-why.tsv, tree.tsv and the wound
ledger -- so every case here writes those files into a scratch HOME and
reads back the sentences and the rows. Pure: no terminal, no daemon.

  * the summary says blind when blind, the estimate and HOW it was made when
    not, the projected exhaustion, the manual resets as weeks spent, and an
    old verdict as old (a stale "held" drawn as current is the failure the
    repo's CLAUDE.md names as its worst);
  * the windows table classes each window by its entry's `priority:` and
    sorts release first, and lists an entry only when the BUDGET held it --
    a memory hold is the memory guard's to draw;
  * every knob refuses what the daemon could not use, and a blank one shows
    the number in force from the verdict, not a copy of the presets;
  * the main footer's note is there only while something is held or queued.
"""
import atexit
import os
import pathlib
import shutil
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOME = tempfile.mkdtemp(prefix="mux-budget-view-")
atexit.register(shutil.rmtree, HOME, ignore_errors=True)
os.environ.update(HOME=HOME, XDG_CONFIG_HOME=HOME + "/.config",
                  XDG_STATE_HOME=HOME + "/.local/state", XDG_DATA_HOME=HOME + "/.local/share")
for _k in ("MUXTOPUS_CONFIG", "MUXTOPUS_HOME", "MUXTOPUS_DIR", "CLAUDE_CONFIG_DIR", "TMUX"):
    os.environ.pop(_k, None)
for _k in [k for k in os.environ if k.startswith(("WATCHDOG_", "DASHBOARD_", "MUXTOPUS_"))]:
    os.environ.pop(_k, None)
sys.path.insert(0, str(ROOT))

import muxsettings  # noqa: E402
from dashboard.core import SCHEDULES_DIR, WATCHDOG_DIR  # noqa: E402
from dashboard.views import budget as bv  # noqa: E402
from dashboard.menus import budget as bm  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    if cond:
        print("ok   " + what)
    else:
        fails += 1
        print("FAIL " + what)


def text(lines) -> str:
    return "\n".join(t.plain for t in lines)


WATCHDOG_DIR.mkdir(parents=True, exist_ok=True)
SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
NOW = time.time()


def verdict(**kv):
    base = {"at": str(int(NOW)), "on": "on", "plan": "max5x",
            "plan_src": "detected (default_claude_max_5x)", "lanes": "4", "hold_pct": "70",
            "wind_pct": "85", "lane_pct": "8", "start_pct": "4", "checkpoint_min": "30",
            "day_pct": "14", "wave": "2", "wave_min": "10", "fresh_ctx": "250000",
            "session_est": "42", "session_est_src": "read 41% 3m ago, + 24%/h since", "blind": "",
            "session_reset_at": str(int(NOW + 3 * 3600)), "rate_pct_h": "24",
            "rate_src": "3 working x 8%/h", "exhaust_at": str(int(NOW + 2 * 3600)),
            "week_pct": "35", "week_reset_at": str(int(NOW + 4 * 86400)), "manual_resets": "1",
            "week_eff": "135", "week_allowed": "56", "running": "3", "limited": "1",
            "queued": "0", "paused": "0", "held": "2",
            "held_why": "held: budget -- the week is at 135% effective", "queued_why": ""}
    base.update(kv)
    (WATCHDOG_DIR / "budget").write_text("".join("%s\t%s\n" % kv for kv in base.items()))
    return base


print("== the summary")
ok("no budget verdict yet" in text(bv.summary({})), "no file: says there is no verdict, and why")
b = verdict()
s = text(bv.summary(bv.read_budget(), NOW))
ok("plan max5x (detected (default_claude_max_5x))" in s, "the plan and where it came from")
ok("~42% (read 41% 3m ago, + 24%/h since)" in s, "the estimate, and how it was made")
ok("runs out ~" + time.strftime("%H:%M", time.localtime(NOW + 2 * 3600)) in s,
   "the projected exhaustion, as a clock")
ok("135% effective (35% read + 1 manual reset, each a week spent)" in s,
   "the week: the reading plus the manual reset counted as a week")
ok("the pace allows 56% now (14%/day)" in s, "..against the pace")
ok("3 running  1 limited  0 queued  0 paused  2 held" in s, "the window counts")
ok("held   the week is at 135% effective" in s, "the first hold reason, without its prefix")
ok("judged" not in s, "a fresh verdict is not called old")
verdict(exhaust_at="")
ok("lasts to the reset" in text(bv.summary(bv.read_budget(), NOW)), "no exhaustion: lasts to the reset")
verdict(session_est="", blind="the 95% reading is 300m old, past WATCHDOG_USAGE_STALE=180m")
s = text(bv.summary(bv.read_budget(), NOW))
ok("blind -- the 95% reading is 300m old" in s and "only the cap and the waves hold" in s,
   "blind: says so, and what still holds")
verdict(at=str(int(NOW - 600)))
ok("judged 10m ago -- the watchdog is not judging" in text(bv.summary(bv.read_budget(), NOW)),
   "an old verdict is said to be old")

print("== the windows and entries")
(SCHEDULES_DIR / "rel.md").write_text("type: work\npriority: release\nstatus: launched\n---\nx\n")
(SCHEDULES_DIR / "low.md").write_text("type: work\npriority: p2\nstatus: launched\n---\nx\n")
(SCHEDULES_DIR / "heldone.md").write_text("type: work\npriority: ops\nstatus: pending\n---\nx\n")
(SCHEDULES_DIR / "memheld.md").write_text("type: work\nstatus: pending\n---\nx\n")
(WATCHDOG_DIR / "tree.tsv").write_text("rel\t\t@1\t%1\t0\trel.md\nlow\t\t@2\t%2\t0\tlow.md\n")
row = lambda sid, name, ctx, state, reset, acted: "\t".join(
    [sid, name, "%9", "1", str(ctx), state, reset, acted] + ["-"] * 12) + "\n"
(WATCHDOG_DIR / "status.tsv").write_text(
    row("s-low", "low", 300000, "working", "-", "")
    + row("s-rel", "rel", 120000, "due", "4pm", "queued")
    + row("s-hand", "byhand", 5000, "limited", "Oct10,5pm", "")
    + row("s-pause", "paused1", 9000, "idle", "-", "")
    + row("s-idle", "idle1", 9000, "idle", "-", ""))
(WATCHDOG_DIR / "wound").write_text("s-pause\t2\t%d\t%d\ns-idle\t2\t%d\t%d\n"
                                    % (NOW + 3600, NOW - 60, NOW - 3600, NOW - 7200))
(WATCHDOG_DIR / "sched-why.tsv").write_text(
    "heldone.md\theld\theld: budget -- 4 windows working, the cap is 4\t0\n"
    "memheld.md\theld\theld: memory -- 3.1 GB available\t0\n")
rows = bv.budget_lanes(NOW)
got = [(r["name"], r["prio"], r["what"]) for r in rows]
ok(got[0] == ("rel", "release", "queued"), "release first, and a queued resume says queued: %r" % (got[:1],))
ok(("low", "p2", "running") in got, "a running window is classed by its entry (p2)")
ok(("byhand", "p1", "limited") in got, "a window opened by hand is p1")
ok(("paused1", "p1", "paused") in got, "wound down hard for a window not yet reset: paused")
ok(not any(n == "idle1" for n, _, _ in got), "..one whose window has reset is not")
ok(("heldone", "ops", "held") in got, "an entry the budget held, with its class")
ok(not any(n == "memheld" for n, _, _ in got), "an entry the MEMORY guard held is not listed here")
ok([r["prio"] for r in rows] == sorted([r["prio"] for r in rows], key=bv.CLASSES.index),
   "sorted by class: release, p1, ops, p2")
held = [r for r in rows if r["what"] == "held"][0]
ok(held["why"] == "4 windows working, the cap is 4", "the hold's reason, without its prefix")

print("== the footer note")
verdict(held="2", queued="1")
ok(bv.footer_note(None).plain == "  · budget: 2 held, 1 queued (b)", "held and queued: the note")
verdict(held="0", queued="0")
ok(bv.footer_note(None) is None, "nothing held: no note")
verdict(held="3", at=str(int(NOW - 900)))
ok(bv.footer_note(None) is None, "an old verdict: no note (the daemon is not judging)")

print("== Settings ▸ Budget ▸")
muxsettings.register(bm.BUDGET_KEYS, menu="budget")
ok(list(muxsettings.keys_of("budget")) == list(bm.BUDGET_KEYS), "every knob is a budget-menu setting")
ok(muxsettings.put("WATCHDOG_BUDGET_LANES", "many") != "", "a cap that is not a number is refused")
ok(muxsettings.put("WATCHDOG_BUDGET_HOLD_PCT", "140") != "", "a hold line over 100% is refused")
ok(muxsettings.put("WATCHDOG_BUDGET_PLAN", "max40x") != "", "a plan that does not exist is refused")
ok(muxsettings.put("WATCHDOG_BUDGET_LANES", "6") == "", "a cap of 6 is written")
ok(muxsettings.get("WATCHDOG_BUDGET_LANES") == "6", "..and read back")
conf = muxsettings.dashboard_conf_path("").read_text()
ok('WATCHDOG_BUDGET_LANES="6"' in conf, "..into dashboard.conf, where profile.sh reads it")
ok(muxsettings.put("WATCHDOG_BUDGET_LANES", "") == "", "an empty line gives it back to the plan")
ok("WATCHDOG_BUDGET_LANES" not in muxsettings.dashboard_conf_path("").read_text(), "..and the key is gone")
ok(muxsettings.scope_of("MUXTOPUS_E2E_SLOTS", "work") == "", "the e2e slot count is the machine's, not an account's")
menu = bm.BudgetMenu(app=None)
bnow = verdict(lanes="4")
ok(menu.shown("WATCHDOG_BUDGET_LANES", "", bnow) == "(plan: 4)", "a blank knob shows the plan's number in force")
ok(menu.shown("WATCHDOG_BUDGET_LANES", "7", bnow) == "7", "a pinned one shows itself")
ok(menu.shown("WATCHDOG_HARD_PCT", "", bnow) == "(default: 85)", "the wind-down line shows its default")
ok(menu.shown("WATCHDOG_BUDGET", "", bnow) == "ON", "the guard is on by default")

print()
print("%d FAILED" % fails if fails else "all passed")
sys.exit(1 if fails else 0)
