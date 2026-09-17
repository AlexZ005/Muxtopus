"""dashboard.core -- the constants every other module measures against.

The palette, the account profile, every PATH the dashboard reads or writes,
the knobs, and the pure formatters. Nothing here knows about a frame, a menu
or a key; everything here is imported by something that does.

It is the only module allowed to import muxconfig, so there is ONE place the
shell half and the python half are read from the same file -- the rule the
account-profile block below was written to state, now enforced by being true
in one module instead of hoped for in several.

Rich IS allowed here (gauge and sparkline return Text), but it is not
REQUIRED here. dashboard.data and dashboard.schedules import this module for
its paths, and they are read by things that have no terminal -- the watchdog,
a test, a bot -- so a missing rich must cost them nothing. Hence the guarded
import below: without rich the constants still load and only the two
formatters that draw are unusable, and they say so when called.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

try:
    from rich.text import Text
except ImportError:                 # see the docstring: the headless callers
    class Text:                     # get the constants; only drawing is gone
        def __init__(self, *_a, **_k):
            raise ImportError(
                "dashboard.core's formatters need rich, and this interpreter "
                "has none. dashboard.data and dashboard.schedules do not need "
                "it, which is why importing them got this far.")


HOME = Path.home()
# THE CHECKOUT, which is one directory ABOVE this file: dashboard/core.py
# is in the package, and SCRIPTS is what claude-usage.sh, claude-watchdog.sh,
# deck-ram.sh and VERSION are found beside. `.parent` here would be the
# package directory, and every one of those lookups would miss in silence.
SCRIPTS = Path(__file__).resolve().parent.parent
PAGE = os.sysconf("SC_PAGE_SIZE")
TICKS = os.sysconf("SC_CLK_TCK")
SPARK = "▁▂▃▄▅▆▇█"

SERVER_HINTS = ("node_modules/.bin/vite", "vite dev", "npm run dev", "npm exec vite")
EXTRA_HINTS = ("plasmashell", "plasma-discover", "steamwebhelper", "Steam/ubuntu12_32")

GREEN, YELLOW, RED = "#7ec699", "#d6b26b", "#d47f7f"
DIM, FRAME = "grey42", "grey30"

STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", str(HOME / ".local" / "state")))

# ------------------------------------------------------------- account profile
# One dashboard per Claude account. The profile is the suffix on the config
# dir -- ~/.claude is the default account and takes NO suffix, so every path
# below is byte-identical to what it was before a second account existed.
# muxtopus puts CLAUDE_CONFIG_DIR into the tmux session, so window 0 picks its own
# account up from the environment rather than being passed a flag. The DEFAULT
# account is the variable being absent, which is why the fallback below is a
# path and not an error: no variable means ~/.claude, means profile "".
# WHERE THE DATA LIVES comes from muxconfig, which reads the SAME file
# profile.sh reads -- the shell half and the python half must never disagree
# about it, and one reader is how that is guaranteed rather than hoped for.
# mux_home, read_options and options_paths are not used HERE. They are
# re-exported: this module is the single door to muxconfig, so a view that
# wants the options list asks core for it rather than opening a second one.
from muxconfig import (mux_dir, mux_home, knob, profile_of,
                       options as read_options, options_paths)

CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(HOME / ".claude")))
PROFILE = CONFIG_DIR.name
for _p in (".claude",):
    if PROFILE.startswith(_p):
        PROFILE = PROFILE[len(_p):]
PROFILE = PROFILE.lstrip("-_")
SUFFIX = ("-" + PROFILE) if PROFILE else ""
# What a column or a header says when it has to name the account: an empty
# string would read as missing data rather than as "the default one".
PROFILE_LABEL = PROFILE or "personal"
TMUX_SESSION = "claude" + SUFFIX
# Is there more than one account on this machine? Only then is it worth naming
# the account on screen -- two dashboards side by side otherwise look identical
# while reporting different budgets, different sessions and different
# schedules, and reading the work account's reset time off the personal
# dashboard is the one mistake that costs a whole limit window.
try:
    _extra = [d for d in os.listdir(HOME)
              if d.startswith(".claude-") and not d.endswith((".bak", ".old", "~"))
              and (HOME / d).is_dir()]
except OSError:
    _extra = []
MULTI_ACCOUNT = bool(_extra)

WATCHDOG_DIR = STATE_HOME / ("claude-watchdog" + SUFFIX)
WATCHDOG_STATUS = WATCHDOG_DIR / "status.tsv"
WATCHDOG_ENABLED = WATCHDOG_DIR / "enabled"
WATCHDOG_OPTOUT = WATCHDOG_DIR / "optout"
WATCHDOG_REPOS = WATCHDOG_DIR / "repos.tsv"
WATCHDOG_USAGE = WATCHDOG_DIR / "usage.tsv"
WATCHDOG_HOORAY = WATCHDOG_DIR / "usage.hooray"
# Written by claude-usage.sh when a read FAILS. A failed read no longer
# overwrites the cache, so without this the panel would go on showing the last
# good figures with nothing to say they are all there is.
WATCHDOG_USAGE_FAIL = WATCHDOG_DIR / "usage.fail"
WATCHDOG_MONITOR = WATCHDOG_DIR / "monitor"
WATCHDOG_MON_OPTOUT = WATCHDOG_DIR / "monitor-optout"
WATCHDOG_DIRECTIVES = WATCHDOG_DIR / "directives"
WATCHDOG_MSG = WATCHDOG_DIR / "message"
# THE KNOBS come from the config layers via muxconfig -- the same files, the
# same key list and the same precedence as the shell half -- so a value set
# for this account in ~/.config/muxtopus/profiles/<name>.conf reaches the
# dashboard without anyone exporting anything. R re-execs, which re-reads.
# u refreshes only past this age; U ignores it. The watchdog keeps its own
# hourly clock, so this is about not starting a probe per keypress.
USAGE_MAX_AGE = int(knob("CLAUDE_USAGE_MAX_AGE", PROFILE))
# Both sessions on this machine run a 1M-context model. There is no way to ask
# a running session what its window is, so this is an assumption the bar is
# drawn against, overridable rather than hidden.
CONTEXT_WINDOW = int(knob("CLAUDE_CONTEXT_WINDOW", PROFILE))
# The watchdog republishes every 30s; past double that it is not running.
# Both are named rather than inlined because the help screen quotes them to
# explain why a closed window is dropped here instead of waited for.
STALE_AFTER = 75.0
WD_INTERVAL = int(knob("WATCHDOG_INTERVAL", PROFILE))
FRAME_INTERVAL = 2.0


# --------------------------------------------------------------------------
# the one file reader
# --------------------------------------------------------------------------
def read(path: str, default: str = "") -> str:
    try:
        with open(path, "r", errors="replace") as fh:
            return fh.read()
    except OSError:
        return default



# ------------------------------------------------------------- schedules
# An account may keep its folders in a home of its own (MUXTOPUS_HOME_work),
# where they are unsuffixed; muxconfig applies the same rule profile.sh does.
SCHEDULES_DIR = mux_dir("schedules", PROFILE)
SCHED_TEMPLATES = SCHEDULES_DIR / "templates"
# Handoffs live here rather than in the working tree: scratch state does not
# belong under version control, and two accounts working one repo would
# otherwise overwrite each other's STATUS file without a word. handover.sh
# moves a finished one into done/.
HANDOVERS_DIR = mux_dir("handovers", PROFILE)
# Where autonomous plan sessions park the forks they could not ask about.
QUESTIONS_DIR = Path(knob("MUXTOPUS_QUESTIONS_DIR", PROFILE,
                          str(HOME / ".code" / "theprototype-app" / "core" / "plans")))
# The desktop-extras entry rides the same cursor as the sessions, and so do
# the lane rows: a cursor key of "::lane:<pgid>" is a dev server.
EXTRAS_SENTINEL = "::extras"
LANE_PREFIX = "::lane:"
# The placeholder row of an EMPTY lanes table is a cursor target too, or a
# filtered-away table could never be switched to "all" from the arrows.
LANES_EMPTY = LANE_PREFIX + "none"


# The executor's verdict on each pending entry: file -> (verdict, reason, when).
# Written every pass by check_schedules, because the one question this
# scheduler could not answer was "why has that not fired yet".
WATCHDOG_SCHED_WHY = WATCHDOG_DIR / "sched-why.tsv"
# Proof of life: epoch, sessions, pending schedules, interval. The log records
# only changes -- measured, its last line was four days old while the daemon was
# polling every 30s -- so liveness had to be inferred from the mtimes of files
# it happens to rewrite. This says it outright.
WATCHDOG_HEARTBEAT = WATCHDOG_DIR / "heartbeat"


# ------------------------------------------------------------------ the tree
# tmux has NO window hierarchy -- windows are a flat indexed list -- so the
# scheduler keeps the tree as data and this is the view of it.
#   slug  parent  window-id  pane-id  launched-at  file
WATCHDOG_TREE = WATCHDOG_DIR / "tree.tsv"


# HOW A SESSION STATE IS DRAWN: name -> (label, style, show the reset time).
# Data rather than a chain of elifs in the frame, so a module that teaches the
# watchdog a new state can teach the table to draw it in one line
# (App.add_state) instead of editing the main view. A state that is NOT here
# keeps the fallback it has always had: dim, under its own name -- which is
# what an unknown state from a newer watchdog has to do.
STATES: dict[str, tuple[str, str, bool]] = {
    "due": ("due", RED, True),
    "limited": ("limited", YELLOW, True),
    "working": ("working", GREEN, False),
    # THE "nothing is ever going to touch this" state. idle stays dim because
    # it is a fact about the last turn and usually means finished; stranded is
    # a fact about the FUTURE, so it is the one idle state worth a colour.
    "stranded": ("stranded", RED, False),
}


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------
def human_tokens(n: int) -> str:
    return f"{n / 1_000_000:.2f}M" if n >= 1_000_000 else f"{n // 1000}k" if n >= 1000 else str(n)


def when(epoch: int) -> str:
    """A resume stamp, shown as a time today and a date before that."""
    if not epoch:
        return "—"
    now = time.time()
    return time.strftime("%H:%M" if now - epoch < 57600 else "%b %-d %H:%M",
                         time.localtime(epoch))


def human_mb(mb: int) -> str:
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb} MB"


def human_age(sec: float) -> str:
    s = int(sec)
    if s >= 86400:
        return f"{s // 86400}d"
    if s >= 3600:
        return f"{s // 3600}h"
    if s >= 60:
        return f"{s // 60}m"
    return f"{s}s"


def pressure(pct: float) -> str:
    return RED if pct >= 90 else YELLOW if pct >= 70 else GREEN


def gauge(pct: float, width: int = 24) -> Text:
    filled = max(0, min(width, int(pct * width / 100)))
    t = Text()
    t.append("█" * filled, style=pressure(pct))
    t.append("·" * (width - filled), style=DIM)
    return t


def sparkline(pcts: list[int]) -> Text:
    t = Text()
    for p in pcts:
        style = RED if p >= 80 else YELLOW if p >= 45 else GREEN
        t.append(SPARK[min(7, p * 7 // 100)], style=style)
    return t
