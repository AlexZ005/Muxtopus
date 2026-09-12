#!/usr/bin/env python3
"""deck_status.py -- live dashboard for parallel dev lanes.

Measured against the bash implementation this replaces:
    bash : 216 ms and 248 forks per frame
    this :  12.9 ms and   2 forks per frame

(An earlier synthetic benchmark suggested 1.5 ms; that one did not walk /proc.
The honest figure for this implementation is 12.9 ms -- still ~17x cheaper and
124x fewer forks, with the remaining cost dominated by reading stat/statm/
cmdline for every process on the system.)

The difference is not Python being fast; it is that the bash version forked
ps twice, ss once, ps -o pgid per listening socket and sed PER LINE for width
measurement, every two seconds, forever, on a battery-powered handheld. Every
collector below reads /proc directly instead.

Rich also measures text correctly -- grapheme clusters and East-Asian wide
characters -- which the hand-rolled version could not. That version counted
codepoints, so one CJK character or emoji in a lane path skewed the frame.

Entry point is deck-status.sh, which falls back to its own bash renderer if
this interpreter or rich is unavailable. The dashboard must never be the
broken thing.
"""
from __future__ import annotations

import os
import select
import string
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

HOME = Path.home()
SCRIPTS = Path(__file__).resolve().parent
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
from muxconfig import mux_dir, knob, profile_of

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
# collectors -- all of these read /proc; none of them fork
# --------------------------------------------------------------------------
def read(path: str, default: str = "") -> str:
    try:
        with open(path, "r", errors="replace") as fh:
            return fh.read()
    except OSError:
        return default


def meminfo() -> dict[str, float]:
    out = {}
    for line in read("/proc/meminfo").splitlines():
        k, _, rest = line.partition(":")
        try:
            out[k] = float(rest.split()[0]) / 1048576.0   # kB -> GiB
        except (IndexError, ValueError):
            pass
    return out


class Cpu:
    """Per-core busy percentage from /proc/stat deltas between frames."""

    def __init__(self) -> None:
        self.prev: dict[str, tuple[int, int]] = {}

    def sample(self) -> list[int]:
        pcts = []
        for line in read("/proc/stat").splitlines():
            if not line.startswith("cpu") or line.startswith("cpu "):
                continue
            parts = line.split()
            name, vals = parts[0], [int(v) for v in parts[1:]]
            total, idle = sum(vals), vals[3]
            p_total, p_idle = self.prev.get(name, (0, 0))
            if p_total and total > p_total:
                busy = (total - p_total) - (idle - p_idle)
                pct = max(0, min(100, busy * 100 // (total - p_total)))
            else:
                pct = 0
            self.prev[name] = (total, idle)
            pcts.append(pct)
        return pcts


def uptime_seconds() -> float:
    try:
        return float(read("/proc/uptime").split()[0])
    except (IndexError, ValueError):
        return 0.0


def first_glob(pattern: str) -> str:
    for p in sorted(Path("/sys/class").glob(pattern)):
        v = read(str(p)).strip()
        if v:
            return v
    return ""


def hottest_c() -> str:
    temps = []
    for p in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        v = read(str(p)).strip()
        if v.lstrip("-").isdigit():
            temps.append(int(v) / 1000.0)
    return f"{max(temps):.0f}" if temps else "?"


class Proc:
    __slots__ = ("pid", "pgid", "comm", "cmdline", "rss_mb", "age")

    def __init__(self, pid, pgid, comm, cmdline, rss_mb, age):
        self.pid, self.pgid, self.comm = pid, pgid, comm
        self.cmdline, self.rss_mb, self.age = cmdline, rss_mb, age


def processes(boot_uptime: float) -> list[Proc]:
    out = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        stat = read(f"/proc/{pid}/stat")
        if not stat:
            continue
        # comm can contain spaces and parens, so split on the LAST ')'
        close = stat.rfind(")")
        if close < 0:
            continue
        comm = stat[stat.find("(") + 1: close]
        fields = stat[close + 2:].split()
        try:
            pgid = int(fields[2])                 # pgrp
            starttime = int(fields[19]) / TICKS   # since boot
        except (IndexError, ValueError):
            continue
        statm = read(f"/proc/{pid}/statm").split()
        rss_mb = (int(statm[1]) * PAGE // 1048576) if len(statm) > 1 else 0
        cmdline = read(f"/proc/{pid}/cmdline").replace("\0", " ").strip()
        out.append(Proc(pid, pgid, comm, cmdline, rss_mb, max(0.0, boot_uptime - starttime)))
    return out


def listening_inodes() -> dict[int, int]:
    """socket inode -> local port, for sockets in LISTEN state."""
    found = {}
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in read(path).splitlines()[1:]:
            f = line.split()
            if len(f) < 10 or f[3] != "0A":       # 0A == TCP_LISTEN
                continue
            try:
                found[int(f[9])] = int(f[1].rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                pass
    return found


def ports_for(pids: list[int], inodes: dict[int, int]) -> dict[int, int]:
    """pid -> listening port. Only the candidate pids are scanned, so this
    stays cheap: a full /proc/*/fd walk would be far more syscalls."""
    out = {}
    for pid in pids:
        try:
            for fd in os.scandir(f"/proc/{pid}/fd"):
                try:
                    target = os.readlink(fd.path)
                except OSError:
                    continue
                if target.startswith("socket:["):
                    ino = int(target[8:-1])
                    if ino in inodes:
                        out[pid] = inodes[ino]
                        break
        except OSError:
            continue
    return out


class ClaudeSession:
    __slots__ = ("sid", "window", "pane", "ver", "ctx", "state", "reset", "action",
                 "resumed", "spent", "cached", "optout", "model", "idle", "job",
                 "cwd", "wound", "dirty", "moptout", "pid")

    def __init__(self, sid, window, pane, ver, ctx, state, reset, action,
                 resumed=0, spent=0, cached=0, optout=False, model="-", idle=-1, job="",
                 cwd="-", wound=0, moptout=False, pid=0):
        self.sid, self.window, self.pane, self.ver = sid, window, pane, ver
        self.ctx, self.state, self.reset, self.action = ctx, state, reset, action
        self.resumed, self.spent, self.cached = resumed, spent, cached
        self.optout, self.model = optout, model
        self.idle, self.job = idle, job
        self.cwd, self.wound, self.moptout = cwd, wound, moptout
        self.pid = pid
        self.dirty = 0          # filled in from the repo sweep at render time


def claude_sessions() -> tuple[list[ClaudeSession], float]:
    """Rows published by claude-watchdog.sh, plus the age of that file.

    Reading a file rather than capturing tmux panes here is the whole reason
    this stays cheap: the dashboard redraws every 2s at 2 forks a frame, and a
    capture-pane per window would multiply that on a battery-powered handheld.
    The watchdog already polls, so it publishes and this only reads.
    """
    try:
        raw = WATCHDOG_STATUS.read_text()
        age = time.time() - WATCHDOG_STATUS.stat().st_mtime
    except OSError:
        return [], -1.0
    def num(fields, i):
        try:
            return int(fields[i])
        except (IndexError, ValueError):
            return 0

    out = []
    for line in raw.splitlines():
        f = line.split("\t")
        if len(f) < 7:
            continue
        out.append(ClaudeSession(
            f[0], f[1], f[2], f[3], num(f, 4), f[5], f[6],
            f[7] if len(f) > 7 else "",
            num(f, 8), num(f, 9), num(f, 10),
            (len(f) > 11 and f[11] == "1"),
            f[12] if len(f) > 12 else "-",
            num(f, 13) if len(f) > 13 else -1,
            f[14] if len(f) > 14 else "",
            f[15] if len(f) > 15 else "-",
            num(f, 16) if len(f) > 16 else 0,
            (len(f) > 17 and f[17] == "1"),
            num(f, 18) if len(f) > 18 else 0,
        ))
    return out, age


def drop_dead(sessions: list[ClaudeSession],
              procs: list[Proc]) -> list[ClaudeSession]:
    """Sessions whose process is still alive.

    THE PUBLISHED FILE IS ALWAYS A LITTLE OLD. The watchdog rebuilds it once
    an interval, so a window closed just after a pass stayed on this table for
    most of the next one -- long enough to reach for a row that is not there
    any more. The row carries its pid, and this frame has already walked
    /proc for the memory figures, so the check is a set lookup: no fork, no
    tmux call, and the row goes the frame after the process does.

    THE TEST IS DELIBERATELY THE WEAKEST ONE THAT WORKS: is the pid in /proc
    at all. Matching the command name as well would also catch a pid that has
    been recycled onto something else, but it would drop a live session the
    day a session runs under a name this file did not predict -- and the two
    mistakes are not equals. A row wrongly dropped hides work that is running;
    a row wrongly kept is the behaviour of every version before this one, and
    the next watchdog pass corrects it.

    A row published by a watchdog too old to send a pid has none, and is kept:
    the fallback is the previous behaviour, never a table that empties itself.
    """
    live = {p.pid for p in procs}
    return [s for s in sessions if not s.pid or s.pid in live]


def opted_out() -> set[str]:
    """Read the opt-out file DIRECTLY rather than the copy in the published
    table. This dashboard writes that file, and the watchdog only republishes
    every 30s -- taking the published value made a press of space appear to do
    nothing for up to half a minute."""
    try:
        return {l.strip() for l in WATCHDOG_OPTOUT.read_text().splitlines() if l.strip()}
    except OSError:
        return set()


def usage_limits() -> dict[str, str]:
    """The last reading claude-usage.sh took. Never scraped from here: that
    costs a throwaway session and ~4s, which has no business on a 2s frame."""
    out: dict[str, str] = {}
    try:
        for line in WATCHDOG_USAGE.read_text().splitlines():
            k, _, v = line.partition("\t")
            out[k] = v
    except OSError:
        pass
    return out


def usage_failure(u: dict[str, str]) -> str:
    """Why the last read failed, if it failed AFTER the cached numbers were
    taken. Empty when the cache is the more recent of the two."""
    try:
        at, _, why = WATCHDOG_USAGE_FAIL.read_text().strip().partition("\t")
        ts = int(at)
    except (OSError, ValueError):
        return ""
    try:
        if ts <= int(u.get("at") or 0):
            return ""
    except ValueError:
        pass
    return why or "read failed"


def usage_rows() -> list[Text]:
    """Three lines for the header's right edge, or one saying how to get them.

    EXACTLY THREE, always: the header grid puts one on each of its rows."""
    u = usage_limits()
    failed = usage_failure(u)
    if not u.get("at"):
        return [Text("usage unknown", style=DIM),
                Text(failed[:34] if failed else "press u to read it",
                     style=YELLOW if failed else DIM),
                Text()]

    def pct(key: str) -> float:
        try:
            return float(u.get(key) or 0)
        except ValueError:
            return 0.0

    def row(label: str, pkey: str, rkey: str, tail: str = "") -> Text:
        v = u.get(pkey) or "?"
        t = Text()
        t.append(f"{label} ", style=DIM)
        t.append(f"{v}%", style=pressure(pct(pkey)))
        if u.get(rkey):
            t.append(f" · resets {u[rkey]}", style=DIM)
        if tail:
            t.append(tail, style=DIM)
        return t

    try:
        seen = time.strftime("%H:%M", time.localtime(int(u["at"])))
    except (ValueError, KeyError):
        seen = "?"
    model = (u.get("model") or "model").capitalize()
    last = row(model, "model_pct", "", f" · read {seen}")
    if failed:
        last.append(" · stale", style=YELLOW)
    return [
        row("Session", "session_pct", "session_reset"),
        row("Week", "week_pct", "week_reset"),
        last,
    ]


def refresh_usage(force: bool = False) -> str:
    """Fire the scrape and return immediately -- it spawns a Claude session and
    takes a few seconds, and blocking the frame for that would freeze the whole
    dashboard. The panel picks the result up on a later frame.

    force=False uses --ensure, so leaning on the key does not start a probe per
    press; force=True is the deliberate 'no, now'."""
    script = SCRIPTS / "claude-usage.sh"
    if not script.exists():
        return "claude-usage.sh not found"
    # NAME THE ACCOUNT, do not leave it to be inherited. claude-usage.sh falls
    # back to CLAUDE_CONFIG_DIR, which is right whenever this dashboard was
    # started by muxtopus -- and silently wrong in a window that was not, where it
    # would refresh the personal account's cache from the work dashboard.
    acct = ["--profile", PROFILE] if PROFILE else []
    args = [str(script), *acct, "--refresh"] if force else \
           [str(script), *acct, "--ensure", str(USAGE_MAX_AGE)]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return f"usage refresh failed: {exc}"
    if force:
        return "reading usage limits now…"
    age = usage_limits().get("at")
    try:
        mins = int((time.time() - int(age)) // 60)
    except (TypeError, ValueError):
        return "reading usage limits…"
    return ("reading usage limits…" if mins >= USAGE_MAX_AGE
            else f"usage is {mins}m old, still fresh — U forces a read")


def hooray() -> bool:
    """A limit reset EARLY since the last frame. Read once and cleared, so the
    flourish shows for one refresh cycle rather than until midnight."""
    try:
        WATCHDOG_HOORAY.unlink()
        return True
    except OSError:
        return False


def dirty_repos() -> list[tuple[str, str, int]]:
    """(path, name, changed files) for every repo the watchdog found dirty."""
    out = []
    try:
        for line in WATCHDOG_REPOS.read_text().splitlines():
            f = line.split("\t")
            if len(f) >= 3:
                try:
                    out.append((f[0], f[1], int(f[2])))
                except ValueError:
                    pass
    except OSError:
        pass
    out.sort(key=lambda r: -r[2])
    return out


def dirty_for(cwd: str, repos: list[tuple[str, str, int]]) -> int:
    """Uncommitted files in the repo the session is sitting in.

    Longest prefix wins, because a worktree lives inside the parent checkout's
    directory and the inner one is the answer. This is a HINT on the row; the
    table below is the truth, and it lists dirty repos with no session at all --
    which are the ones most likely to be forgotten."""
    if not cwd or cwd == "-":
        return 0
    best = 0
    best_len = -1
    for path, _name, n in repos:
        if (cwd == path or cwd.startswith(path.rstrip("/") + "/")) and len(path) > best_len:
            best, best_len = n, len(path)
    return best


def monitor_on() -> bool:
    return WATCHDOG_MONITOR.exists()


def monitor_opted_out() -> set[str]:
    """Sessions exempt from wind-downs -- a SEPARATE list from the restart
    opt-out, because they are different powers: a lane can be safe to restart
    after a limit and still be one you never want interrupted mid-turn. Read
    live for the same reason the other one is: the watchdog republishes only
    every 30s, and a toggle that appears dead for half a minute reads as broken."""
    try:
        return {l.strip() for l in WATCHDOG_MON_OPTOUT.read_text().splitlines() if l.strip()}
    except OSError:
        return set()


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


SLUG_OK = frozenset(string.ascii_letters + string.digits + "._-")


def sanitise_slug(raw: str) -> str:
    """The executor's rule, character for character: tr -c 'A-Za-z0-9._-' '-'
    then cut to 22. Mirrored here rather than shelled out to, for the same
    reason validate_schedule mirrors the executor's other rules -- this side is
    a linter, and a linter that disagrees with the thing it lints is worse than
    none."""
    return "".join(c if c in SLUG_OK else "-" for c in raw)[:22]


def resolve_slug(row: dict) -> str:
    """What the window, the handover file and `handover.sh done` will all be
    called. An explicit slug: wins over the title; the filename is the last
    resort."""
    raw = row.get("slug") or row.get("title") or row["file"].stem
    return sanitise_slug(raw)


def slug_warning(row: dict) -> str:
    """Empty when the slug is exactly what was written down.

    Not corruption -- a title that sanitises still launches -- but the gap
    between "27-storage wave 2" and the slug 27-storage-wave-2 is what put a
    lane's handover in a file nothing was watching, so it is said out loud."""
    raw = row.get("slug") or row.get("title")
    src = "slug" if row.get("slug") else "title"
    if not raw:
        return ""
    slug = sanitise_slug(raw)
    if slug == raw:
        return ""
    if len(raw) > 22 and raw[:22] == slug:
        return "%s truncated to %r — set slug: to pin it" % (src, slug)
    return "%s is not a slug; it becomes %r — set slug: to pin it" % (src, slug)


# The executor's verdict on each pending entry: file -> (verdict, reason, when).
# Written every pass by check_schedules, because the one question this
# scheduler could not answer was "why has that not fired yet".
WATCHDOG_SCHED_WHY = WATCHDOG_DIR / "sched-why.tsv"


def sched_why() -> dict[str, tuple[str, str, int]]:
    out: dict[str, tuple[str, str, int]] = {}
    try:
        for line in WATCHDOG_SCHED_WHY.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    at = int(parts[3])
                except (IndexError, ValueError):
                    at = 0
                out[parts[0]] = (parts[1], parts[2], at)
    except OSError:
        pass
    return out


def read_schedules() -> list[dict]:
    """Parse every schedule file, KEEPING the broken ones.

    The executor (claude-watchdog.sh) silently skips what it cannot parse;
    this side's whole job is the opposite -- show the file with the reason it
    will never launch, because a schedule that quietly does nothing is the
    worst failure a scheduler can have."""
    rows: list[dict] = []
    try:
        files = sorted(SCHEDULES_DIR.glob("*.md"))
    except OSError:
        return rows
    for f in files:
        if f.name == "README.md":
            continue
        row = {"file": f, "type": "", "at": "", "title": "", "slug": "",
               "window": "", "cwd": "", "template": "", "status": "",
               "created": "", "launched": "", "body": "", "bad": "",
               "warn": "", "resolved": ""}
        try:
            text = f.read_text()
        except OSError as exc:
            row["bad"] = "unreadable: %s" % exc
            rows.append(row)
            continue
        head, sep, body = text.partition("\n---\n")
        if not sep:
            row["bad"] = "no --- separator line"
        for line in head.splitlines():
            k, _, v = line.partition(": ")
            k = k.rstrip(":")           # tolerate "launched:" with no value
            if k in row and k not in ("file", "body", "bad"):
                row[k] = v.strip()
        row["body"] = body.strip()
        row["resolved"] = resolve_slug(row)
        row["warn"] = slug_warning(row)
        if not row["bad"]:
            row["bad"] = validate_schedule(row)
        rows.append(row)
    return rows


def validate_schedule(row: dict) -> str:
    """The corrupted-marking rules. Mirrors what the bash executor requires --
    kept deliberately a little STRICTER (exact time format), since this side
    is a linter for hand-edited files and bash date -d will swallow almost
    anything, right or wrong."""
    if row["type"] not in ("plan", "work"):
        return "type must be plan or work (got %r)" % (row["type"] or "")
    if row["at"] != "reset":
        ok = False
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                time.strptime(row["at"], fmt)
                ok = True
                break
            except ValueError:
                pass
        if not ok:
            return "at must be 'reset' or YYYY-MM-DD HH:MM (got %r)" % (row["at"] or "")
    if not row["cwd"] or not Path(row["cwd"]).is_dir():
        return "cwd missing or not a directory"
    if row["type"] == "work" and not row["body"]:
        return "work item has an empty prompt body"
    if row["template"] and not (SCHED_TEMPLATES / (row["template"] + ".md")).exists():
        return "template %r not in templates/" % row["template"]
    if row["status"] not in ("pending", "launched", "error", ""):
        return "unknown status %r" % row["status"]
    return ""


def human_tokens(n: int) -> str:
    return f"{n / 1_000_000:.2f}M" if n >= 1_000_000 else f"{n // 1000}k" if n >= 1000 else str(n)


def when(epoch: int) -> str:
    """A resume stamp, shown as a time today and a date before that."""
    if not epoch:
        return "—"
    now = time.time()
    return time.strftime("%H:%M" if now - epoch < 57600 else "%b %-d %H:%M",
                         time.localtime(epoch))


def session_mode(procs: list[Proc]) -> str:
    comms = {p.comm for p in procs}
    if "kwin_wayland" in comms:
        return "desktop"
    if any("start-gamescope-session" in p.cmdline for p in procs):
        return "game"
    return "?"


def lane_account(pid: int) -> str | None:
    """Which account a dev server belongs to, read off its environment.

    muxtopus puts CLAUDE_CONFIG_DIR into the tmux SESSION, so everything
    started inside one of its windows inherits the variable -- and keeps it
    after the window is gone. That is why this beats walking parent pids: a
    server that was daemonised, or outlived the shell that started it, has
    been reparented to init and has no ancestry left, but its environment is
    still the one it was born with. No variable is the default account,
    exactly as everywhere else in this tool. None means the file could not be
    read (another user's process): unknown, and therefore not ours."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            env = f.read()
    except OSError:
        return None
    for item in env.split(b"\0"):
        if item.startswith(b"CLAUDE_CONFIG_DIR="):
            return profile_of(item[len(b"CLAUDE_CONFIG_DIR="):].decode(errors="replace"))
    return ""


def lane_name(pid: int) -> str:
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return "?"
    code = str(HOME / ".code") + "/"
    if cwd.startswith(code):
        return cwd[len(code):]
    if cwd.startswith(str(HOME) + "/"):
        return "~/" + cwd[len(str(HOME)) + 1:]
    return cwd


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# frame
# --------------------------------------------------------------------------
class Dashboard:
    def __init__(self, interval: float) -> None:
        self.cpu = Cpu()
        self.interval = interval
        self.notice: str | None = None
        self.notice_at = 0.0
        self.party_at = 0.0
        self.cursor = ""            # session id under the row cursor
        self.sids: list[str] = []   # last rendered order, for the arrow keys
        self.panes: dict[str, str] = {}   # session id -> tmux pane, for Enter
        self.jobs: dict[str, str] = {}    # session id -> bg job id, for attach
        self.windows: dict[str, str] = {}  # session id -> tmux window name
        # Space opens a menu rather than toggling one setting, because the
        # useful actions outgrew the keyboard: two global switches plus six
        # things to do to the window under the cursor.
        self.menu_open = False
        self.menu_i = 0
        self.prompt: dict | None = None    # inline text entry (rename)
        self.confirm: dict | None = None   # yes/no gate (close)
        self.picker: dict | None = None    # arrow-driven option list (create flow)
        self.pending_edit: str | None = None   # file the main loop opens in an editor
        self.view = "main"                 # "main" | "sched"
        self.sched_i = 0
        self.sched_rows: list[dict] = []
        self.cwds: dict[str, str] = {}     # session id -> working directory
        # THE LANES TABLE IS THIS ACCOUNT'S BY DEFAULT. Two dashboards side by
        # side listing the same servers is the same confusion the session
        # suffix exists to prevent; f (or enter on a lane row) shows them all.
        self.lanes_all = False
        self.lane_keys: list[str] = []     # lane rows in rendered order
        self.lane_acct: dict[int, str | None] = {}   # pid -> account, cached
        self.version = (SCRIPTS / "VERSION").read_text().strip() if (SCRIPTS / "VERSION").exists() else "?"

    def say(self, msg: str) -> None:
        self.notice, self.notice_at = msg, time.time()

    def move(self, delta: int) -> None:
        if not self.sids:
            return
        try:
            i = self.sids.index(self.cursor)
        except ValueError:
            i = 0
        self.cursor = self.sids[max(0, min(len(self.sids) - 1, i + delta))]

    def open_selected(self) -> str:
        """Jump the tmux client to the selected session's window.

        The dashboard keeps running in window 0; this only moves the client, so
        Ctrl-b 0 comes straight back. A background session (`claude --bg`) has
        no pane to switch to, which is a real case here rather than an edge one,
        so it is named instead of failing silently."""
        if self.cursor == EXTRAS_SENTINEL:
            return self.toggle_extras()
        if self.cursor.startswith(LANE_PREFIX):
            return self.toggle_lanes()
        pane = self.panes.get(self.cursor, "")
        if not pane:
            job = self.jobs.get(self.cursor, "")
            # A background job has no window, but it does have a job id, and
            # that is the whole answer to "how do I see what it is doing".
            return (f"background job — run:  claude attach {job}" if job
                    else f"{self.cursor[:8]} is a background session — no window to open")
        try:
            r = subprocess.run(["tmux", "select-window", "-t", pane],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return ""
            # A different tmux session needs the client moved, not the window.
            r = subprocess.run(["tmux", "switch-client", "-t", pane],
                               capture_output=True, text=True, timeout=5)
            return "" if r.returncode == 0 else f"could not open: {r.stderr.strip()}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"could not open: {exc}"

    # ---------------------------------------------------------------- menu
    def menu_entries(self) -> list[dict]:
        """Rebuilt every frame so the labels state what is true right now."""
        wd_all = WATCHDOG_ENABLED.exists()
        mon_all = monitor_on()
        sid = self.cursor
        if sid == EXTRAS_SENTINEL:
            return [{"label": "Reclaim or start desktop extras",
                     "act": self.toggle_extras}]
        if sid.startswith(LANE_PREFIX):
            return [{"label": ("Show this account's lanes only" if self.lanes_all
                               else "Show every account's lanes"),
                     "act": self.toggle_lanes}]
        win = self.windows.get(sid, "")
        has_pane = bool(self.panes.get(sid))
        skipped = sid in opted_out()
        mskipped = sid in monitor_opted_out()
        label = win or (sid[:8] if sid else "nothing")
        # THE MENU IS PER WINDOW. The two global switches live on w and m and
        # are shown in the panel title, because a menu opened over one row is
        # the wrong place to disarm the whole fleet -- and because the question
        # you actually have in front of a row is about THAT lane.
        items: list[dict] = []
        if sid:
            items += [
                {"key": "wd_win",
                 "label": "Restart %s after a limit: %s" % (
                     label, "YES" if not skipped else "no, left parked"),
                 "on": not skipped, "act": self.toggle_selected},
                {"key": "mon_win",
                 "label": "Wind %s down near the limit: %s" % (
                     label, "YES" if not mskipped else "no, never interrupted"),
                 "on": not mskipped, "act": self.act_mon_window},
                {"sep": True},
                {"label": "Open %s" % label, "act": self.open_selected, "need_pane": True},
                {"label": "Rename %s" % label, "act": self.act_rename, "need_pane": True},
                {"label": "Wind down %s now  ask it to checkpoint and stop" % label,
                 "act": self.act_wind},
                {"label": "Resume %s now  tell it to continue" % label,
                 "act": self.act_resume, "need_pane": True},
                {"label": "Continue %s at low priority  spends the WEEKLY budget" % label,
                 "act": self.act_lowpri, "need_pane": True},
                {"label": "Schedule ➥resume of %s at the next reset  reads its STATUS file" % label,
                 "act": self.act_schedule_resume},
                {"sep": True},
                {"label": "Close %s  kills the claude session in it" % label,
                 "act": self.act_close, "need_pane": True, "danger": True},
            ]
        else:
            items = [{"label": "no session selected", "disabled": "nothing to act on"}]
        # Say so when a global switch makes the rows above moot, rather than
        # letting a row read ON while nothing can happen.
        if not wd_all:
            items.append({"label": "watchdog is off globally  (w turns it on)",
                          "disabled": "global"})
        if not mon_all:
            items.append({"label": "monitoring is off globally  (m turns it on)",
                          "disabled": "global"})
        for it in items:
            if it.get("need_pane") and not has_pane:
                it["disabled"] = "background session, no window"
        return items

    def menu_move(self, delta: int) -> None:
        items = self.menu_entries()
        i = self.menu_i
        for _ in range(len(items)):
            i = (i + delta) % len(items)
            if not items[i].get("sep") and not items[i].get("disabled"):
                self.menu_i = i
                return

    def menu_activate(self) -> None:
        items = self.menu_entries()
        if not (0 <= self.menu_i < len(items)):
            return
        it = items[self.menu_i]
        if it.get("sep") or it.get("disabled"):
            return
        msg = it["act"]()
        # A submode owns the screen until it is answered; a plain action is done.
        if self.prompt is None and self.confirm is None:
            if it.get("key") not in ("watchdog", "monitor"):
                self.menu_open = False
        if msg:
            self.say(msg)

    def act_watchdog(self) -> str:
        return toggle_watchdog()

    def act_mon_window(self) -> str:
        """Exempt THIS session from wind-downs, or put it back in scope."""
        if not self.cursor:
            return "no session selected"
        try:
            WATCHDOG_DIR.mkdir(parents=True, exist_ok=True)
            lines = []
            if WATCHDOG_MON_OPTOUT.exists():
                lines = [l for l in WATCHDOG_MON_OPTOUT.read_text().splitlines() if l.strip()]
            win = self.windows.get(self.cursor, self.cursor[:8])
            if self.cursor in lines:
                lines.remove(self.cursor)
                msg = "%s may be wound down near the limit" % win
            else:
                lines.append(self.cursor)
                msg = "%s will never be interrupted" % win
            WATCHDOG_MON_OPTOUT.write_text("".join(l + "\n" for l in lines))
            return msg
        except OSError as exc:
            return "toggle failed: %s" % exc

    def act_monitor(self) -> str:
        """Arm or disarm the wind-downs. Separate from the watchdog on purpose:
        restarting a window that already stopped cannot lose anything, while
        telling a working window to wrap up changes what it is doing."""
        try:
            WATCHDOG_DIR.mkdir(parents=True, exist_ok=True)
            if WATCHDOG_MONITOR.exists():
                WATCHDOG_MONITOR.unlink()
                return "session monitoring off - no window will be asked to stop"
            WATCHDOG_DIRECTIVES.mkdir(parents=True, exist_ok=True)
            WATCHDOG_MONITOR.touch()
            return "session monitoring on - a window near the limit is asked to checkpoint"
        except OSError as exc:
            return "monitor toggle failed: %s" % exc

    def act_rename(self) -> str:
        win = self.windows.get(self.cursor, "")
        self.prompt = {"title": "Rename %s to" % (win or "window"), "buf": "",
                       "fn": self._do_rename}
        return ""

    def _do_rename(self, text: str) -> str:
        name = text.strip()
        if not name:
            return "rename cancelled"
        pane = self.panes.get(self.cursor, "")
        if not pane:
            return "no window to rename"
        try:
            subprocess.run(["tmux", "rename-window", "-t", pane, name],
                           capture_output=True, timeout=5)
            return "renamed to %s" % name
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "rename failed: %s" % exc

    def act_close(self) -> str:
        win = self.windows.get(self.cursor, "") or self.cursor[:8]
        self.confirm = {"label": "Close %s? The claude session in it is killed." % win,
                        "fn": self._do_close}
        return ""

    def _do_close(self) -> str:
        pane = self.panes.get(self.cursor, "")
        if not pane:
            return "no window to close"
        try:
            subprocess.run(["tmux", "kill-window", "-t", pane],
                           capture_output=True, timeout=5)
            return "closed"
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "close failed: %s" % exc

    def act_wind(self) -> str:
        """Drop a directive the session picks up after its next tool call.

        This is the same channel the watchdog uses, so a hand-driven wind-down
        and an automatic one are indistinguishable to the session -- which is
        the point: it is told what to do, never why."""
        if not self.cursor:
            return "no session selected"
        u = usage_limits()
        reset = u.get("session_reset") or "the top of the hour"
        win = self.windows.get(self.cursor, "this lane")
        msg = ("Budget checkpoint: land the step you are on now and commit it, then "
               "write a handoff to %s/STATUS-%s.md saying what is done, what is next "
               "and anything half-finished. Then stop. The budget resets at %s; do "
               "not start what you cannot finish before then."
               % (HANDOVERS_DIR, win, reset))
        try:
            WATCHDOG_DIRECTIVES.mkdir(parents=True, exist_ok=True)
            (WATCHDOG_DIRECTIVES / self.cursor).write_text(msg + "\n")
            return "%s will be asked to checkpoint after its next tool call" % win
        except OSError as exc:
            return "could not queue: %s" % exc

    def _send(self, text: str) -> str:
        pane = self.panes.get(self.cursor, "")
        if not pane:
            return "no window to type into"
        try:
            subprocess.run(["tmux", "send-keys", "-t", pane, text],
                           capture_output=True, timeout=5)
            time.sleep(0.6)
            subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"],
                           capture_output=True, timeout=5)
            return "sent"
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "send failed: %s" % exc

    def act_resume(self) -> str:
        try:
            msg = WATCHDOG_MSG.read_text().splitlines()[0]
        except (OSError, IndexError):
            msg = "The usage limit has reset. Continue from where you left off."
        return self._send(msg)

    def act_lowpri(self) -> str:
        """Continue NOW against the weekly budget instead of waiting for the
        session window to refill. Offered by the limit banner itself."""
        return self._send("/low-priority")

    def prompt_key(self, key: str) -> None:
        pr = self.prompt
        if pr is None:
            return
        if key in ("\r", "\n"):
            fn = pr["fn"]
            text = pr["buf"]
            self.prompt = None
            self.menu_open = False
            self.say(fn(text))
        elif key == "\x1b":
            self.prompt = None
            self.say("cancelled")
        elif key in ("\x7f", "\b"):
            pr["buf"] = pr["buf"][:-1]
        elif len(key) == 1 and key.isprintable():
            pr["buf"] += key

    def confirm_key(self, key: str) -> None:
        cf = self.confirm
        if cf is None:
            return
        if key in ("y", "Y"):
            fn = cf["fn"]
            self.confirm = None
            self.menu_open = False
            self.say(fn())
        elif key in ("n", "N", "\x1b", "\r", "\n"):
            self.confirm = None
            self.say("cancelled")

    def _submode_foot(self):
        """The footer panel when a text prompt, confirm or picker owns the
        keyboard -- shared by both views so the create flow works from either."""
        if self.prompt is not None:
            return Panel(
                Text.assemble((self.prompt["title"] + ": ", "bold"),
                              (self.prompt["buf"], "#c9a0dc"), ("_", "bold #c9a0dc"),
                              ("      enter save · esc cancel", DIM)),
                border_style="#c9a0dc", box=box.ROUNDED)
        if self.confirm is not None:
            return Panel(
                Text.assemble((self.confirm["label"], "bold"), "    ",
                              ("y", "bold " + RED), (" yes    ", DIM),
                              ("n", "bold"), (" no", DIM)),
                border_style=RED, box=box.ROUNDED)
        if self.picker is not None:
            body = Text()
            for i, opt in enumerate(self.picker["options"]):
                cur = (i == self.picker["i"])
                body.append(" ▸ " if cur else "   ", style="bold #c9a0dc")
                body.append(opt + "\n", style="bold" if cur else "")
            body.append("   ↑↓ pick · enter choose · esc cancel", style=DIM)
            return Panel(body, title="[bold]" + self.picker["title"],
                         title_align="left", border_style="#c9a0dc", box=box.ROUNDED)
        return None

    def picker_key(self, key: str) -> None:
        pk = self.picker
        if pk is None:
            return
        if key == "UP":
            pk["i"] = (pk["i"] - 1) % len(pk["options"])
        elif key == "DOWN":
            pk["i"] = (pk["i"] + 1) % len(pk["options"])
        elif key in ("\r", "\n"):
            fn, choice = pk["fn"], pk["options"][pk["i"]]
            self.picker = None
            msg = fn(choice)
            if msg:
                self.say(msg)
        elif key == "\x1b":
            self.picker = None
            self.say("cancelled")

    # ------------------------------------------------------------ schedules
    def sched_move(self, delta: int) -> None:
        if self.sched_rows:
            self.sched_i = max(0, min(len(self.sched_rows) - 1, self.sched_i + delta))

    def _sched_sel(self):
        if 0 <= self.sched_i < len(self.sched_rows):
            return self.sched_rows[self.sched_i]
        return None

    def request_edit_selected(self) -> str:
        r = self._sched_sel()
        if r is None:
            return "nothing selected — c creates one"
        self.pending_edit = str(r["file"])
        return ""

    def start_create(self) -> None:
        self.picker = {"title": "schedule what?", "i": 0,
                       "options": ["plan", "work"], "fn": self._create_type}

    def _create_type(self, choice: str) -> str:
        if choice == "plan":
            tpls = sorted(t.stem for t in SCHED_TEMPLATES.glob("*.md"))
            if tpls:
                self.picker = {"title": "from which template?", "i": 0,
                               "options": tpls, "fn": self._create_tpl}
                return ""
        return self._create_write(choice, "")

    def _create_tpl(self, choice: str) -> str:
        return self._create_write("plan", choice)

    def _create_write(self, typ: str, tpl: str) -> str:
        """Write a pre-filled item and drop straight into the editor on it.

        The chosen template is COPIED into the body rather than referenced, so
        what you edit is exactly what gets pasted -- a referenced template
        would be prepended again by the executor."""
        try:
            SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
            f = SCHEDULES_DIR / ("%s-%s.md" % (typ, time.strftime("%Y%m%d-%H%M%S")))
            cwd = self.cwds.get(self.cursor, "")
            if not cwd or cwd == "-":
                cwd = str(HOME / ".code" / "theprototype-app" / "core")
            body = ""
            if tpl:
                try:
                    body = (SCHED_TEMPLATES / (tpl + ".md")).read_text()
                except OSError:
                    body = ""
            f.write_text("type: %s\n" % typ
                         + "at: reset\n"
                         + "title: \n"
                         + "window: \n"
                         + "cwd: %s\n" % cwd
                         + "status: pending\n"
                         + "created: %s\n" % time.strftime("%Y-%m-%d %H:%M")
                         + "launched:\n"
                         + "---\n" + body)
            self.pending_edit = str(f)
            return "created %s — set the title and time, paste the prompt" % f.name
        except OSError as exc:
            return "create failed: %s" % exc

    def launch_selected_now(self) -> str:
        """Make the item due immediately; the daemon does the actual launch on
        its next 30s pass -- one launcher, whoever asked."""
        r = self._sched_sel()
        if r is None:
            return "nothing selected"
        if r["bad"]:
            return "cannot launch: %s" % r["bad"]
        if r["status"] != "pending":
            return "only a pending item launches (this one is %s)" % (r["status"] or "?")
        try:
            text = r["file"].read_text()
            lines = text.split("\n")
            for i, l in enumerate(lines):
                if l.startswith("at: "):
                    lines[i] = "at: " + time.strftime("%Y-%m-%d %H:%M")
                    break
            r["file"].write_text("\n".join(lines))
            return "due now — the watchdog launches it within ~30s"
        except OSError as exc:
            return "failed: %s" % exc

    def confirm_delete_selected(self) -> None:
        r = self._sched_sel()
        if r is None:
            self.say("nothing selected")
            return
        f = r["file"]
        self.confirm = {"label": "Delete %s?" % f.name,
                        "fn": lambda: self._do_sched_delete(f)}

    def _do_sched_delete(self, f) -> str:
        try:
            f.unlink()
            return "deleted %s" % f.name
        except OSError as exc:
            return "delete failed: %s" % exc

    def act_schedule_resume(self) -> str:
        """The wound-down flow's other half: a work item, due at the reset,
        that opens a fresh ➥window right after this one and reads the STATUS
        handoff the wind-down asked the session to write."""
        sid = self.cursor
        win = self.windows.get(sid, "")
        cwd = self.cwds.get(sid, "")
        if not win or not cwd or cwd == "-":
            return "no window/cwd to schedule from"
        try:
            SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
            # NOT in cwd. The handoff belongs to the account, not to the
            # working tree: it is scratch state that would otherwise be
            # committed, and two accounts on one repo would collide on the
            # window name.
            status_file = "%s/STATUS-%s.md" % (HANDOVERS_DIR, win)
            try:
                tpl = (SCHED_TEMPLATES / "resume-status.md").read_text()
            except OSError:
                tpl = ('Read {{STATUS_FILE}} and continue from its "How to resume" '
                       "section. One commit per phase; update the STATUS file "
                       "before stopping.")
            f = SCHEDULES_DIR / ("resume-%s.md" % win)
            f.write_text("type: work\n"
                         + "at: reset\n"
                         + "title: resume %s\n" % win
                         + "window: %s\n" % win
                         + "cwd: %s\n" % cwd
                         + "status: pending\n"
                         + "created: %s\n" % time.strftime("%Y-%m-%d %H:%M")
                         + "launched:\n"
                         + "---\n" + tpl.replace("{{STATUS_FILE}}", status_file))
            return "scheduled ➥resume of %s at the next reset (%s)" % (win, f.name)
        except OSError as exc:
            return "schedule failed: %s" % exc

    def toggle_lanes(self) -> str:
        self.lanes_all = not self.lanes_all
        return "lanes: every account" if self.lanes_all else f"lanes: {PROFILE_LABEL} only"

    def toggle_extras(self) -> str:
        """Enter on the extras row: reclaim when running, start when not --
        the old s/S pair folded onto the cursor. Blocks the frame for the
        deck-ram run, exactly as the old keys did."""
        procs = processes(uptime_seconds())
        extras = sum(p.rss_mb for p in procs
                     if any(h in p.cmdline for h in EXTRA_HINTS))
        return run_deck_ram("stop" if extras else "start")

    def build_sched(self) -> Group:
        rows = read_schedules()
        self.sched_rows = rows
        self.sched_i = max(0, min(self.sched_i, len(rows) - 1)) if rows else 0

        u = usage_limits()
        reset_txt = ""
        if u.get("session_reset_at"):
            try:
                reset_txt = time.strftime("%H:%M", time.localtime(int(u["session_reset_at"])))
            except (ValueError, OverflowError):
                pass

        st = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                   header_style=DIM, border_style=FRAME)
        st.add_column("", width=3)
        st.add_column("STATUS", width=10)
        st.add_column("TYPE", width=6)
        st.add_column("FOR", width=18)
        st.add_column("AT", width=17)
        st.add_column("TITLE", ratio=1, overflow="ellipsis", no_wrap=True)
        st.add_column("SLUG", width=24, overflow="ellipsis", no_wrap=True)
        why = sched_why()
        for i, r in enumerate(rows):
            mark = Text("▸" if i == self.sched_i else " ", style="bold #c9a0dc")
            r["why"] = why.get(r["file"].name, ("", "", 0))
            verdict = r["why"][0]
            if r["bad"]:
                stx = Text("corrupted", style=RED)
            elif r["status"] == "launched":
                stx = Text("launched", style=DIM)
            elif r["status"] == "error":
                stx = Text("error", style=RED)
            elif verdict == "stalled":
                # PENDING FOREVER IS NOT PENDING. An entry the executor cannot
                # judge used to be indistinguishable from one that is simply
                # early, and it never resolved on its own.
                stx = Text("stalled", style=RED)
            elif verdict == "blocked":
                stx = Text("blocked", style=YELLOW)
            elif verdict == "due":
                stx = Text("due", style="bold " + GREEN)
            else:
                stx = Text("pending", style=GREEN)
            when_for = r["at"] or "?"
            if r["at"] == "reset" and reset_txt:
                when_for = "reset (%s)" % reset_txt
            title = r["title"] or r["file"].stem
            if r["bad"]:
                ttx = Text("%s — %s" % (title, r["bad"]), style=RED)
            elif r["warn"]:
                # A divergent slug is not corruption -- it launches -- so it is
                # a warning on an otherwise normal row, not a refusal.
                ttx = Text.assemble(title, ("  ⚠ " + r["warn"], YELLOW))
            elif r["status"] == "launched" and r["launched"]:
                ttx = Text("%s — launched %s" % (title, r["launched"]))
            else:
                ttx = Text(title)
            st.add_row(mark, stx, Text(r["type"] or "?", style=DIM),
                       Text(when_for), Text(r["created"] or "—", style=DIM),
                       ttx, Text(r["resolved"] or r["file"].name, style=DIM))
        if not rows:
            st.add_row("", Text("—", style=DIM), "",
                       Text("nothing scheduled — press c", style=DIM), "", "", "")

        parts = [Panel(st, title="[bold]scheduled windows[/] "
                           f"[{DIM}]· {SCHEDULES_DIR} · templates in templates/",
                       title_align="left", border_style=FRAME, box=box.ROUNDED)]

        # WHY THE SELECTED ENTRY IS NOT RUNNING, in the executor's own words.
        # One line under the table rather than a column: the sentence is long
        # on purpose (it names the gate, the figure and the threshold) and it
        # is only ever wanted for the row under the cursor.
        sel = self._sched_sel()
        if sel is not None:
            verdict, reason, at = sel.get("why", ("", "", 0))
            if sel["bad"]:
                line = Text.assemble(("will never launch: ", RED), (sel["bad"], RED))
            elif reason:
                stale = " (%s ago)" % human_age(time.time() - at) if at else ""
                line = Text.assemble((reason, RED if verdict == "stalled" else ""),
                                     (stale, DIM))
            elif sel["status"] == "launched":
                line = Text("launched %s — the watchdog only judges pending entries"
                            % (sel["launched"] or "?"), style=DIM)
            else:
                line = Text("no verdict yet — the watchdog writes one every pass",
                            style=DIM)
            if sel["warn"]:
                line = Text.assemble(line, "\n", ("⚠ " + sel["warn"], YELLOW))
            parts.append(Panel(line, title="[bold]why", title_align="left",
                               border_style=FRAME, box=box.ROUNDED))

        try:
            qfiles = sorted(QUESTIONS_DIR.glob("QUESTIONS-*.md"))
        except OSError:
            qfiles = []
        if qfiles:
            qt = Text()
            qt.append("awaiting your answers   ", style="bold " + YELLOW)
            qt.append("   ".join(q.name for q in qfiles), style=YELLOW)
            qt.append("\n" + str(QUESTIONS_DIR), style=DIM)
            parts.append(Panel(qt, border_style=FRAME, box=box.ROUNDED))

        keys = Text.assemble(
            (" ↑↓", DIM), " pick  ", ("enter", DIM), "/", ("e", DIM), " edit  ",
            ("c", DIM), " create  ", ("l", DIM), " launch now  ",
            ("d", DIM), " delete  ", ("r", DIM), " reload  ",
            ("s", DIM), "/", ("esc", DIM), " back  ", ("q", DIM), " quit",
        )
        if self.notice and time.time() - self.notice_at < 8:
            keys = Text.assemble((" " + self.notice, "#c9a0dc"), "\n", keys)
        foot = self._submode_foot() or keys
        return Group(*parts, foot)

    def toggle_selected(self) -> str:
        """Opt one session out of being restarted, or back in.

        The watchdog reads this file, so the choice survives a dashboard
        restart and applies whether or not this screen is open. Absent from
        the file means enabled, so a brand new session is covered without
        anyone having to opt it in."""
        if not self.cursor:
            return "no session selected"
        try:
            WATCHDOG_DIR.mkdir(parents=True, exist_ok=True)
            lines = []
            if WATCHDOG_OPTOUT.exists():
                lines = [l for l in WATCHDOG_OPTOUT.read_text().splitlines() if l.strip()]
            short = self.cursor[:8]
            if self.cursor in lines:
                lines.remove(self.cursor)
                msg = f"{short} will be restarted after a limit"
            else:
                lines.append(self.cursor)
                msg = f"{short} will be left alone"
            WATCHDOG_OPTOUT.write_text("".join(l + "\n" for l in lines))
            return msg
        except OSError as exc:
            return f"toggle failed: {exc}"

    def build(self) -> Group:
        if self.view == "sched":
            return self.build_sched()
        mem = meminfo()
        total = mem.get("MemTotal", 0.0)
        avail = mem.get("MemAvailable", 0.0)
        used_pct = ((total - avail) / total * 100) if total else 0
        sw_total = mem.get("SwapTotal", 0.0)
        sw_used = sw_total - mem.get("SwapFree", 0.0)

        up = uptime_seconds()
        procs = processes(up)
        mode = session_mode(procs)
        load = read("/proc/loadavg").split()[0] if read("/proc/loadavg") else "?"
        bat = first_glob("power_supply/BAT*/capacity")
        status = first_glob("power_supply/BAT*/status")
        power = {"Charging": "chg", "Discharging": "bat"}.get(status, "ac")

        # ---- header -------------------------------------------------------
        # Machine on the left, account limits on the right: they are the two
        # ceilings a long run can hit, and neither is much use without the other.
        urows = usage_rows()
        head = Table.grid(padding=(0, 1), expand=True)
        head.add_column(width=5)
        head.add_column(ratio=1)
        head.add_column(justify="right", width=34)
        head.add_row(Text("MEM", style="bold"),
                     Text.assemble(gauge(used_pct), "  ",
                                   (f"{avail:.1f}", "bold"), f" of {total:.1f} GiB free   ",
                                   (f"{used_pct:.0f}% used", DIM)),
                     urows[0])
        head.add_row(Text("SWP", style="bold"),
                     Text(f"{sw_used:.1f} of {sw_total:.1f} GiB zram", style=DIM),
                     urows[1])
        head.add_row(Text("CPU", style="bold"),
                     Text.assemble(sparkline(self.cpu.sample()), "  ",
                                   ("load ", DIM), load, "   ",
                                   (f"{hottest_c()}C", DIM), "   ",
                                   (power + " ", DIM), f"{bat}%"),
                     urows[2])

        subtitle = f"{os.uname().nodename} · {len(os.sched_getaffinity(0))} threads · {mode} mode · v{self.version}"

        # ---- lanes --------------------------------------------------------
        groups: dict[int, dict] = {}
        for p in procs:
            if any(h in p.cmdline for h in SERVER_HINTS):
                g = groups.setdefault(p.pgid, {"rss": 0, "age": 0.0, "pid": p.pid})
                g["age"] = max(g["age"], p.age)
                if "vite" in p.cmdline:
                    g["pid"] = p.pid
        # A server is a PROCESS GROUP: npm run dev and the vite it spawns are
        # separate processes, the port belongs to vite, npm holds ~70 MB of its
        # own. Summing the group is the only honest figure.
        for p in procs:
            if p.pgid in groups:
                groups[p.pgid]["rss"] += p.rss_mb

        inodes = listening_inodes()
        member_pids = [p.pid for p in procs if p.pgid in groups]
        pid_port = ports_for(member_pids, inodes)
        pgid_port: dict[int, int] = {}
        for p in procs:
            if p.pgid in groups and p.pid in pid_port:
                pgid_port[p.pgid] = pid_port[p.pid]

        # WHOSE LANE IS IT. Read once per server, not per frame: an environment
        # is fixed at exec, so the answer cannot change while the group lives.
        # The group LEADER is asked first -- the `npm run dev` the rest hang
        # off -- because the member sampled above can be a short-lived worker
        # that is gone by the next frame; any member inherits the same answer.
        for pgid, g in groups.items():
            if pgid not in self.lane_acct:
                acct = lane_account(pgid)
                if acct is None:
                    acct = lane_account(g["pid"])
                self.lane_acct[pgid] = acct
            g["acct"] = self.lane_acct[pgid]
        self.lane_acct = {k: v for k, v in self.lane_acct.items() if k in groups}
        shown = {k: g for k, g in groups.items()
                 if self.lanes_all or g["acct"] == PROFILE}
        hidden = len(groups) - len(shown)

        lanes = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                      header_style=DIM, border_style=FRAME)
        lanes.add_column("", width=2)
        lanes.add_column("PORT", width=6)
        lanes.add_column("RAM", justify="right", width=10)
        lanes.add_column("AGE", justify="right", width=6)
        lanes.add_column("LANE", overflow="ellipsis", no_wrap=True, ratio=1)
        # Only the unfiltered view needs to say whose a row is; in the
        # filtered one the answer is the panel title.
        if self.lanes_all:
            lanes.add_column("ACCOUNT", width=10)
        lanes.add_column("DIRTY", justify="right", width=6)
        lanes.add_column("STATE", width=16)

        # Per LANE this has always worked, because a lane row is a working
        # tree. Per SESSION it used to be unanswerable -- the published table
        # carried no cwd -- but it does now, so a window sitting in a worktree
        # can say how much uncommitted work it is holding before you close it.
        dirty_list = dirty_repos()
        dirty = {name: n for _path, name, n in dirty_list}

        total_mb = sum(g["rss"] for g in shown.values())
        self.lane_keys = []
        for pgid in sorted(shown, key=lambda k: pgid_port.get(k, 99999)):
            g = shown[pgid]
            key = LANE_PREFIX + str(pgid)
            self.lane_keys.append(key)
            age = g["age"]
            if age >= 86400:
                state, style = "stale, restart", RED
            elif age >= 21600:
                state, style = "ageing", YELLOW
            else:
                state, style = "fresh", GREEN
            lname = lane_name(g["pid"])
            n = dirty.get(lname.rsplit("/", 1)[-1], 0)
            cells = [
                Text("▸" if key == self.cursor else " ", style="bold #c9a0dc"),
                Text(str(pgid_port.get(pgid, "—")), style="#8fb8de"),
                human_mb(g["rss"]),
                Text(human_age(age), style=style),
                Text(lname),
                Text(str(n) if n else "—", style=YELLOW if n else FRAME),
                Text(state, style=style),
            ]
            if self.lanes_all:
                acct = g["acct"]
                cells.insert(5, Text("?" if acct is None else (acct or "personal"),
                                     style=DIM if acct == PROFILE else "#c9a0dc"))
            lanes.add_row(*cells)
        if not shown:
            # The count and the key are in the panel title; keep the cell short
            # enough to survive a narrow column. Selected, it says what enter does.
            self.lane_keys = [LANES_EMPTY]
            sel = self.cursor == LANES_EMPTY
            empty = "no dev servers running" if not hidden else f"none for {PROFILE_LABEL}"
            if sel:
                empty += "  (enter: %s)" % ("mine" if self.lanes_all else "all")
            cells = [Text("▸" if sel else " ", style="bold #c9a0dc"), Text("—", style=DIM), "", "",
                     Text(empty, style="#c9a0dc" if sel else DIM), "", ""]
            if self.lanes_all:
                cells.insert(5, "")
            lanes.add_row(*cells)
        if self.lanes_all:
            lane_scope = " · every account  (f: this one)"
        elif hidden or MULTI_ACCOUNT:
            lane_scope = f" · {PROFILE_LABEL}" + (f" · {hidden} hidden  (f: all)" if hidden else "")
        else:
            lane_scope = ""

        # ---- claude sessions ----------------------------------------------
        sessions, sess_age = claude_sessions()
        sessions = drop_dead(sessions, procs)
        wd_on = WATCHDOG_ENABLED.exists()
        wd_stale = sess_age < 0 or sess_age > STALE_AFTER

        ordered = sorted(sessions, key=lambda x: -x.ctx)
        # The cursor is tracked by session id, not by row index: the table is
        # sorted by context and that order changes under you as sessions work.
        self.sids = [s.sid for s in ordered]
        self.panes = {s.sid: s.pane for s in ordered}
        self.jobs = {s.sid: s.job for s in ordered}
        self.windows = {s.sid: s.window for s in ordered}
        self.cwds = {s.sid: s.cwd for s in ordered}
        # ONE CURSOR, TOP TO BOTTOM, in the order the panels are drawn: lane
        # rows above, then the sessions, then the extras entry on the system
        # row. Arrow up from the first session and a lane lights up; enter or
        # space there switches the lanes table between this account and all.
        first_session = self.sids[0] if self.sids else ""
        self.sids = self.lane_keys + self.sids + [EXTRAS_SENTINEL]
        if self.cursor not in self.sids:
            self.cursor = first_session or self.sids[0]

        mon_all = monitor_on()
        ct = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                   header_style=DIM, border_style=FRAME)
        ct.add_column("", width=3)
        ct.add_column("MON", width=4)
        # no_wrap or a long background-job name wraps and breaks the row;
        # ellipsis only applies to text that is not allowed to wrap.
        ct.add_column("WINDOW", overflow="ellipsis", no_wrap=True, ratio=1)
        ct.add_column("MODEL", width=11, overflow="ellipsis")
        ct.add_column("CONTEXT", width=29)
        ct.add_column("SPENT", justify="right", width=8)
        ct.add_column("IDLE", justify="right", width=6)
        ct.add_column("STATE", width=15)
        ct.add_column("DIRTY", justify="right", width=6)
        ct.add_column("WOUND", width=11)
        ct.add_column("RESUMED", width=11)

        skipped = opted_out()
        mskipped = monitor_opted_out()
        for s in ordered:
            s.optout = s.sid in skipped
            s.moptout = s.sid in mskipped
            pct = min(100.0, s.ctx * 100.0 / CONTEXT_WINDOW) if CONTEXT_WINDOW else 0.0
            bar = Text.assemble(gauge(pct, 14), " ",
                                (f"{pct:3.0f}%", pressure(pct)), " ",
                                (human_tokens(s.ctx), DIM))
            mark = Text()
            mark.append("▸" if s.sid == self.cursor else " ",
                        style="bold #c9a0dc")
            mark.append("✔" if not s.optout else "·",
                        style=DIM if s.optout else GREEN)
            if s.state == "due":
                st_txt = Text("due " + s.reset, style=RED)
            elif s.state == "limited":
                st_txt = Text("limited " + s.reset, style=YELLOW)
            elif s.state == "working":
                st_txt = Text("working", style=GREEN)
            else:
                st_txt = Text(s.state, style=DIM)
            # An idle window is only interesting once it has been quiet a
            # while, and only alarming if it is quiet with work in flight.
            if s.idle < 0:
                idle_txt = Text("—", style=FRAME)
            else:
                idle_style = DIM if (s.idle < 900 or s.state == "working") else YELLOW
                idle_txt = Text(human_age(s.idle), style=idle_style)
            s.dirty = dirty_for(s.cwd, dirty_list)
            dirty_txt = (Text(str(s.dirty), style=YELLOW) if s.dirty
                         else Text("—", style=FRAME))
            # Two scopes, and the row shows the ANSWER rather than just its own
            # half: with the global switch off nothing can happen to anybody, so
            # the row reads "--" instead of claiming to be armed. Space toggles
            # the per-window half; m toggles the global one.
            if not mon_all:
                mon_txt = Text("--", style=FRAME)
            elif s.moptout:
                mon_txt = Text("off", style=DIM)
            else:
                mon_txt = Text("on", style=GREEN)
            ct.add_row(mark, mon_txt, Text(s.window), Text(s.model, style=DIM), bar,
                       Text(human_tokens(s.spent), style=DIM), idle_txt, st_txt,
                       dirty_txt,
                       Text(when(s.wound), style=DIM if s.wound else FRAME),
                       Text(when(s.resumed), style=DIM if s.resumed else FRAME))

        if not sessions:
            ct.add_row("", "", Text("—", style=DIM), "",
                       Text("no claude sessions" if not wd_stale else "watchdog not running",
                            style=DIM), "", "", "", "", "", "")

        wd_label = ("watchdog on", GREEN) if wd_on else ("watchdog off", DIM)
        if wd_stale:
            wd_label = ("watchdog not running", RED)
        mon = mon_all
        spent_all = sum(s.spent for s in sessions)
        mon_label = ("monitor on", GREEN) if mon else ("monitor off", DIM)
        acct = f" [{PROFILE_LABEL}]" if MULTI_ACCOUNT else ""
        ctitle = Text.assemble(("claude", "bold"),
                               (acct, YELLOW if PROFILE else DIM),
                               (f" · {len(sessions)} session(s) · ", DIM),
                               (human_tokens(spent_all), "bold"), (" spent · ", DIM),
                               wd_label, (" · ", DIM), mon_label)

        # ---- system -------------------------------------------------------
        claude = [p for p in procs if p.comm == "claude"]
        pw = sum(p.rss_mb for p in procs if "ms-playwright" in p.cmdline)
        extras = sum(p.rss_mb for p in procs if any(h in p.cmdline for h in EXTRA_HINTS))
        try:
            st = os.statvfs(str(HOME))
            free = f"{st.f_bavail * st.f_frsize / 1073741824:.0f} GiB"   # GiB, matching df -h
        except OSError:
            free = "?"

        # The lanes table only lists trees with a dev server, so a repo holding
        # uncommitted work and running nothing would be invisible there -- which
        # is exactly the one you are most likely to lose.
        lane_names = {lane_name(g["pid"]).rsplit("/", 1)[-1] for g in shown.values()}

        ex_sel = (self.cursor == EXTRAS_SENTINEL)
        ex_hint = ("  (enter %s)" % ("reclaims" if extras else "starts")) if ex_sel \
                  else "  (navigate by arrows)"
        sysrow = Text.assemble(
            ("claude ", "bold"), f"{len(claude)} · {human_mb(sum(p.rss_mb for p in claude))}",
            "     ", ("playwright ", "bold"), (human_mb(pw) if pw else "—"),
            "     ", ("/home ", "bold"), f"{free} free",
            "     ", ("▸ " if ex_sel else "", "bold #c9a0dc"),
            ("desktop extras ", "bold"), human_mb(extras),
            (ex_hint, "#c9a0dc" if ex_sel else DIM),
        )

        keys = Text.assemble(
            (" q", DIM), " quit  ", ("r", DIM), " refresh  ", ("R", DIM), " reload  ",
            ("s", DIM), " schedules  ",
            ("w", DIM), " watchdog  ", ("m", DIM), " monitor  ", ("u", DIM), "/", ("U", DIM), " usage  ", ("↑↓", DIM), " pick  ", ("enter", DIM), " open  ", ("space", DIM), " menu  ",
            ("f", DIM), " all lanes  ", ("p", DIM), " btop  ", ("?", DIM), " help",
        )
        # The one piece of good news this dashboard can deliver, so it gets to
        # be loud. Latched on first sight rather than read per frame: hooray()
        # consumes the flag, and the flag is written by a background process
        # that has no idea whether anyone is looking.
        if hooray():
            self.party_at = time.time()
        if time.time() - self.party_at < 120:
            keys = Text.assemble(
                ("  🎉  A LIMIT RESET EARLY — the clock lied, go again  🎉", "bold #7ec699"),
                "\n", keys)
        elif self.notice and time.time() - self.notice_at < 8:
            keys = Text.assemble((" " + self.notice, "#c9a0dc"), "\n", keys)

        foot = keys
        sub = self._submode_foot()
        if sub is not None:
            foot = sub
        elif self.menu_open:
            body = Text()
            for i, it in enumerate(self.menu_entries()):
                if it.get("sep"):
                    body.append("   " + "·" * 52 + "\n", style=FRAME)
                    continue
                cur = (i == self.menu_i)
                if it.get("disabled"):
                    body.append("     " + it["label"], style=FRAME)
                    body.append("  (%s)\n" % it["disabled"], style=FRAME)
                    continue
                body.append(" ▸ " if cur else "   ", style="bold #c9a0dc")
                style = "bold"
                if it.get("danger"):
                    style = "bold " + RED if cur else RED
                elif "on" in it:
                    style = ("bold " + GREEN) if it["on"] else ("bold " if cur else DIM)
                elif not cur:
                    style = ""
                body.append(it["label"] + "\n", style=style)
            body.append("   ↑↓ pick · enter choose · esc close", style=DIM)
            foot = Panel(body, title="[bold]menu", title_align="left",
                         border_style="#c9a0dc", box=box.ROUNDED)

        # UNCOMMITTED WORK GETS ITS OWN TABLE, not a column on the sessions.
        # The two do not line up: a repo can be dirty with no session and no
        # dev server in it, and that is the copy most likely to be lost, while
        # a session's cwd is often a parent directory that is not a repo at
        # all. The per-row DIRTY column above is the hint; this is the truth.
        panels = []
        if dirty_list:
            dt = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                       header_style=DIM, border_style=FRAME)
            dt.add_column("FILES", justify="right", width=6)
            dt.add_column("TREE", width=26, overflow="ellipsis", no_wrap=True)
            dt.add_column("PATH", overflow="ellipsis", no_wrap=True, ratio=1)
            dt.add_column("", width=10)
            for path, name, n in dirty_list:
                here = name in lane_names
                dt.add_row(Text(str(n), style=YELLOW),
                           Text(name),
                           Text(path.replace(str(HOME), "~"), style=DIM),
                           Text("has a lane" if here else "", style=DIM))
            panels.append(Panel(dt, title="[bold]uncommitted[/] "
                                f"[{DIM}]· {len(dirty_list)} tree(s) · "
                                f"{sum(n for _p, _n, n in dirty_list)} file(s)",
                                title_align="left", border_style=FRAME, box=box.ROUNDED))

        return Group(
            Panel(head, title="[bold]deck", subtitle=f"[{DIM}]{subtitle}",
                  subtitle_align="right", border_style=FRAME, box=box.ROUNDED),
            Panel(lanes,
                  title=f"[bold]lanes[/] [{DIM}]· {len(shown)} server(s) · {human_mb(total_mb)}{lane_scope}",
                  title_align="left", border_style=FRAME, box=box.ROUNDED),
            Panel(ct, title=ctitle, title_align="left",
                  border_style=FRAME, box=box.ROUNDED),
            *panels,
            Panel(sysrow, title="[bold]system", title_align="left",
                  border_style=FRAME, box=box.ROUNDED),
            foot,
        )


SOFT = knob("WATCHDOG_SOFT_PCT", PROFILE)
HARD = knob("WATCHDOG_HARD_PCT", PROFILE)

HELP = f"""
  [bold]deck-status[/] -- lane dashboard

  [bold]q[/] quit        [bold]r[/] redraw now      [bold]R[/] reload this script
  [bold]s[/] scheduled windows      [bold]enter[/] on the extras row stops/starts them
  [bold]w[/] watchdog    [bold]m[/] monitoring      [bold]p[/] btop   [bold]?[/] this screen
  [bold]u[/] read usage limits      [bold]up/down[/] pick   [bold]space[/] menu
  [bold]enter[/] open the selected session's window (Ctrl-b 0 comes back here)
  [bold]f[/] lanes: this account only / every account

  [{DIM}]LANES AND ACCOUNTS[/]
    A dev server belongs to the account whose session started it -- read off
    CLAUDE_CONFIG_DIR in its environment, which it keeps even after the window
    that started it is gone. The table shows this account's by default; f, or
    enter on a lane row, shows every account's with each one labelled. Arrow
    up from the first session to reach the lane rows.

  [{DIM}]THE MENU (space)[/]
    Two switches at the top, then everything you can do to the window under
    the cursor: open, rename, skip it, wind it down, resume it, continue it at
    low priority, or close it. Arrows pick, enter chooses, esc closes.

  [{DIM}]SESSION MONITORING[/]
    Off by default, and a separate switch from the watchdog because they are
    different powers. The watchdog RESTARTS a window that already stopped,
    which cannot lose anything. Monitoring speaks to a window that is still
    WORKING, asking it to commit what it has and write a handoff before the
    budget runs out -- so that the next window can start from that handoff
    instead of carrying a quarter-million tokens of context forward.

    It is delivered through a PostToolUse hook, so it reaches a session mid-turn
    without typing into a pane that is busy composing. Two bands: past {SOFT}% of
    the session budget it is asked to stop spawning subagents, past {HARD}% to
    checkpoint and stop. The hard band only fires when it BUYS something -- a
    context big enough to be worth restarting fresh, or a weekly budget too
    spent for /low-priority to carry the session through. Otherwise the window
    is left to run into the limit banner, which costs nothing.

    THE SESSION IS NEVER TOLD WHY. It receives an instruction, not a budget
    negotiation. The reasoning is logged here instead: the WOUND column says
    when a window was last asked to wrap up, and the log carries the reading
    that decided it.

  [{DIM}]UNCOMMITTED[/]
    Its own table rather than a column, because dirty trees and sessions do not
    line up: a repo can be dirty with no session and no dev server anywhere
    near it, and that is the copy most likely to be lost. The DIRTY column on a
    session row is a hint for the tree that window is sitting in.

  [{DIM}]SCHEDULED WINDOWS (s)[/]
    One .md per window to open later, in {SCHEDULES_DIR} (templates in
    templates/; the folder README documents the format). The watchdog daemon
    launches due items: `at: reset` fires when the session limit resets or the
    budget simply reads fresh; an absolute time fires when it passes. The new
    window opens right after its `window:` target, named with a leading ➥,
    and the prompt lands as ONE bracketed paste. A file the view cannot parse
    shows as corrupted with the reason, and never launches.
    In the view: enter/e edit · c create (type, template, then straight into
    the editor to paste the prompt) · l launch now · d delete · r reload ·
    s/esc back. Plan sessions write their forks into core/plans/QUESTIONS-*.md
    instead of asking; those files are listed in the view until answered.

  [{DIM}]A session shown as (background) was started with `claude --bg`. It has no
  terminal, so there is no window for enter to open and no pane for the
  watchdog to type into -- it can be watched but never restarted from here.[/]

  [{DIM}]USAGE LIMITS (top right)[/]
    The only numbers here that cannot be computed locally. Claude Code has no
    usage subcommand and no file holding live limit state, so [bold]u[/] runs
    claude-usage.sh, which starts a throwaway session, sends /usage, reads the
    pane and kills it -- about four seconds, no turn taken. It is ON DEMAND for
    that reason, and the third line carries the time it was read so a stale
    number cannot pass for a current one.

    [bold]u[/] refreshes only if the figures are over {USAGE_MAX_AGE} minutes old, so leaning
    on the key costs nothing; [bold]U[/] forces a read now. [bold]R[/] reloads this script and
    nudges the limits the same way u does. The watchdog also refreshes hourly
    on its own, so the numbers stay warm with nobody watching.

    THE READING BELONGS TO THIS ACCOUNT ([{YELLOW}]{PROFILE_LABEL}[/]) and no other. The probe
    is a tmux session, and a tmux session does NOT inherit the environment of
    whatever created it -- so the account has to be handed in explicitly, and
    for a while it was not: every account's probe read the same budget and
    filed it under its own name. If two dashboards ever show identical figures
    again, that is the shape of the bug.

    A FAILED READ SAYS SO. It leaves the last good numbers alone and marks the
    third line [{YELLOW}]stale[/], rather than writing a row of blanks stamped with the
    current time -- which showed "?%" and then counted as fresh enough not to
    retry. A read that cannot get to a prompt names its reason: the account is
    not logged in, has not trusted the folder, or never finished setup.

    The same values are available to scripts and to prompts:
      claude-usage.sh --brief | --json | --session-pct | --week-pct
      claude-usage.sh --ensure 15     refresh only if older than 15 minutes
    Every reading is appended to usage.log with a timestamp.

    If a limit ever empties BEFORE the time it promised, that is the one good
    surprise here, so it is announced loudly and sent to your phone. Configure
    a backend in ~/.config/claude-notify.conf (ntfy, Pushbullet or Telegram --
    see the header of claude-notify.sh); with none configured it is logged and
    nothing is sent.

  [{DIM}]CLAUDE[/]
    [bold]CONTEXT[/] is the session's live context against {CONTEXT_WINDOW // 1000}k
    (set CLAUDE_CONTEXT_WINDOW if yours differs -- a running session cannot be
    asked what its window is). [bold]SPENT[/] is that session's lifetime input +
    cache writes + output, the parts billed at or above full rate; cache READS
    are excluded because they cost about a tenth and would swamp the number.
    Subagent tokens are NOT included -- they never enter the parent transcript.
    [bold]IDLE[/] is time since that session last wrote a turn; it goes amber past
    15 minutes, so a stalled window reads differently from a finished one.
    [bold]RESUMED[/] is when the watchdog last restarted that session.

  [{DIM}]UNCOMMITTED WORK[/]
    [bold]DIRTY[/] on the lanes table is tracked files changed in that working tree.
    It is not on the claude table because a session's cwd here is /home/deck,
    which is not a repo -- the question is only answerable per TREE. A dirty
    repo with no dev server would then be invisible, so the system line names
    those separately. Untracked files are ignored: a scratch file is noise, a
    modified tracked file is work you could lose.

    [{YELLOW}]limited[/]  stopped at a usage limit, waiting for the reset
    [{RED}]due[/]      the reset has passed and it is still sitting there

    [bold]w[/] arms the watchdog: an IDLE window that hit a limit is prompted to
    continue once its reset time passes, once per limit. It never types into a
    window that is working. Disarmed, the panel still reports; nothing is sent.
    Measured twice here: autoContinueAtUsageLimit does NOT resume after the
    5-hour session limit, and /loop dies on its first refused wakeup.

    [bold]space[/] excludes ONE session (the [{GREEN}]checkmark[/] becomes a dot). The choice
    lives in the watchdog's own file, so it holds whether or not this dashboard
    is open, and survives a restart. Everything is included by default, so a
    session started tomorrow is covered without being opted in.

  [{DIM}]All of it is read from files claude-watchdog.sh publishes: no API calls,
  no tokens, and no tmux captures from this process.[/]

  [{DIM}]CLOSED WINDOWS LEAVE ON THE NEXT REDRAW[/]
    That file is rebuilt once every {WD_INTERVAL}s, so a window closed just after a pass
    used to sit on this table for most of the next one -- measured at 21 and 25
    seconds, long enough to arrow onto a row that is not there any more. Each
    row now carries its process id, and this frame has already walked /proc for
    the memory figures, so a row whose process is gone is dropped here: no
    fork, no tmux call, gone within {FRAME_INTERVAL:g}s.

    Nothing else got faster. Rows still APPEAR at the watchdog's pace, because
    deciding what a session IS costs a transcript read, and a 2s frame will not
    pay for one. The test is only whether the pid is still in /proc -- not
    whether it still looks like claude, because dropping a live session to
    catch a recycled pid trades a harmless wait for a hidden window.

  [{DIM}]LANE STATE[/]
    [{GREEN}]fresh[/]    under 6h
    [{YELLOW}]ageing[/]   6-24h
    [{RED}]stale[/]    over 24h. A vite server was measured at 2487 MB after three
             days against 1142 MB fresh, and a long-lived server is also what
             serves dual module instances.

  [{DIM}]RAM is summed per PROCESS GROUP: `npm run dev` and the vite it spawns are
  separate processes, the port belongs to vite, and npm holds ~70 MB of its own.[/]

  [{DIM}]press any key[/]
"""


def read_key(timeout: float) -> str | None:
    """One keypress, with the arrows decoded.

    READ THE FILE DESCRIPTOR, NOT sys.stdin, and that is the whole point of
    this function. An arrow is the three bytes ESC [ A delivered in a single
    write. sys.stdin is buffered, so the first read(1) pulls all three into
    Python's buffer and hands back one -- after which select() on the fd
    correctly reports NOTHING left to read, because the remaining two are in
    userspace, not the kernel. The previous version then gave up and returned a
    bare Escape, so arrows silently did nothing while every plain key worked.

    os.read has no such buffer: one read takes the whole sequence, and a
    sequence split across writes is picked up by the short second poll.
    """
    fd = sys.stdin.fileno()
    if not select.select([fd], [], [], timeout)[0]:
        return None
    try:
        data = os.read(fd, 16)
    except OSError:
        return None
    if not data:
        return None

    # COMPLETE A SPLIT ESCAPE SEQUENCE. 50ms was the old budget, which is
    # generous on a local tty and tight over ssh: when ESC and "[A" arrive in
    # separate reads the sequence was abandoned as a bare Escape and the "["
    # and "A" were then consumed as two further junk keypresses -- so the arrow
    # did nothing and ate the two presses after it. Keep reading while what we
    # hold is a prefix rather than a whole sequence.
    deadline = time.time() + 0.25
    while data.startswith(b"\x1b") and not _complete_key(data):
        left = deadline - time.time()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            break
        try:
            more = os.read(fd, 16)
        except OSError:
            break
        if not more:
            break
        data += more
    return decode_key(data)


def _complete_key(data: bytes) -> bool:
    """Is this a whole sequence, or still a prefix waiting for its tail?"""
    if not data.startswith(b"\x1b"):
        return True
    if data == b"\x1b" or data == b"\x1b[" or data == b"\x1bO":
        return False
    if data.startswith((b"\x1b[", b"\x1bO")):
        # A CSI/SS3 sequence ends at its first final byte (@ through ~).
        return any(0x40 <= b <= 0x7E for b in data[2:])
    return True


def decode_key(data: bytes) -> str:
    """Bytes to a key name. Pure, so the arrow handling is testable."""
    if data.startswith((b"\x1b[", b"\x1bO")):
        for b in data[2:]:
            if 0x40 <= b <= 0x7E:
                # Final byte identifies the key; anything between is a
                # modifier parameter (ESC [ 1 ; 5 A is ctrl-up), and a
                # modified arrow should still move the cursor.
                return {0x41: "UP", 0x42: "DOWN"}.get(b, "\x1b")
        return "\x1b"
    return data[:1].decode("utf-8", "replace")


def toggle_watchdog() -> str:
    """Arm or disarm the re-prompt. The watchdog keeps polling and publishing
    either way -- the flag only decides whether it is allowed to TYPE into a
    window, which is the part that spends tokens."""
    try:
        WATCHDOG_DIR.mkdir(parents=True, exist_ok=True)
        if WATCHDOG_ENABLED.exists():
            WATCHDOG_ENABLED.unlink()
            return "watchdog off — limited windows will be left alone"
        WATCHDOG_ENABLED.touch()
        return "watchdog on — an idle limited window is prompted once its limit resets"
    except OSError as exc:
        return f"watchdog toggle failed: {exc}"


def run_deck_ram(action: str) -> str:
    script = SCRIPTS / "deck-ram.sh"
    if not script.exists():
        return "deck-ram.sh not found"
    try:
        out = subprocess.run([str(script), action], capture_output=True, text=True, timeout=90).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{action} failed: {exc}"
    lines = [l.strip() for l in out.splitlines() if l.strip().startswith(("+", "!", "."))]
    return lines[-1].lstrip("+!. ") if lines else f"{action} done"


def main() -> int:
    interval = FRAME_INTERVAL
    args = sys.argv[1:]
    if "--int" in args:
        try:
            interval = float(args[args.index("--int") + 1])
        except (IndexError, ValueError):
            pass
    once = "--once" in args

    console = Console()
    dash = Dashboard(interval)

    if once or not sys.stdout.isatty():
        dash.build()          # prime the CPU deltas so the frame is real
        time.sleep(0.12)
        console.print(dash.build())
        return 0

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        dash.build()          # prime
        with Live(dash.build(), console=console, screen=True,
                  auto_refresh=False, transient=False) as live:
            while True:
                live.update(dash.build(), refresh=True)

                # A requested file edit suspends the whole display into a real
                # editor (the btop pattern). Fallback is nano: $EDITOR is
                # empty over ssh on the deck.
                if dash.pending_edit:
                    path, dash.pending_edit = dash.pending_edit, None
                    live.stop()
                    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                    subprocess.run([os.environ.get("EDITOR") or "nano", path])
                    tty.setcbreak(fd)
                    live.start()
                    continue

                key = read_key(interval)

                # A SUBMODE OWNS THE KEYBOARD while it is open, and it is
                # checked before every global key -- including q. Typing a
                # window name that contains a "q" must not quit the dashboard,
                # and neither must answering a confirm.
                if key is not None and (dash.prompt is not None
                                        or dash.confirm is not None
                                        or dash.picker is not None
                                        or dash.menu_open):
                    if dash.prompt is not None:
                        dash.prompt_key(key)
                    elif dash.confirm is not None:
                        dash.confirm_key(key)
                    elif dash.picker is not None:
                        dash.picker_key(key)
                    elif key == "UP":
                        dash.menu_move(-1)
                    elif key == "DOWN":
                        dash.menu_move(1)
                    elif key in ("\r", "\n"):
                        dash.menu_activate()
                    elif key in ("\x1b", " ", "q", "Q"):
                        dash.menu_open = False
                    continue

                # The schedule view owns most keys while open; q, R, ? and p
                # deliberately stay global.
                if dash.view == "sched" and key is not None:
                    if key == "UP":
                        dash.sched_move(-1)
                        continue
                    if key == "DOWN":
                        dash.sched_move(1)
                        continue
                    if key in ("\r", "\n", "e", "E"):
                        m = dash.request_edit_selected()
                        if m:
                            dash.say(m)
                        continue
                    if key == "c":
                        dash.start_create()
                        continue
                    if key == "l":
                        dash.say(dash.launch_selected_now())
                        continue
                    if key == "d":
                        dash.confirm_delete_selected()
                        continue
                    if key == "r":
                        dash.say("schedules re-read")
                        continue
                    if key in ("s", "\x1b"):
                        dash.view = "main"
                        continue

                if key in ("q", "Q"):
                    break
                if key == "R":
                    # A running process holds the copy it started with; re-exec
                    # so an edited script takes effect without respawning tmux.
                    # Also nudge the limits, but through --ensure: a reload is
                    # not a reason to start a probe if the figures are minutes
                    # old, and R gets pressed a lot while editing.
                    refresh_usage()
                    live.stop()
                    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                    os.execv(sys.executable, [sys.executable, __file__] + args)
                if key == "?":
                    live.stop()
                    console.clear()
                    console.print(HELP)
                    read_key(60)
                    live.start()
                elif key in ("p", "P"):
                    live.stop()
                    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                    subprocess.run(["btop"] if os.path.exists("/usr/bin/btop") else ["htop"])
                    tty.setcbreak(fd)
                    live.start()
                elif key == "u":
                    dash.say(refresh_usage())
                elif key == "U":
                    dash.say(refresh_usage(force=True))
                elif key == "UP":
                    dash.move(-1)
                elif key == "DOWN":
                    dash.move(1)
                elif key in ("\r", "\n"):
                    dash.say(dash.open_selected())
                elif key == " ":
                    dash.menu_open = True
                    dash.menu_i = 0
                elif key in ("w", "W"):
                    dash.say(toggle_watchdog())
                elif key in ("m", "M"):
                    dash.say(dash.act_monitor())
                elif key == "f":
                    dash.say(dash.toggle_lanes())
                elif key == "s":
                    # The schedule view. Stopping/starting desktop extras
                    # moved onto the cursor: arrow past the sessions, enter.
                    dash.view = "sched"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
