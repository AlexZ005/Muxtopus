"""dashboard.data -- everything the dashboard READS, and nothing it draws.

/proc for the machine, and the files claude-watchdog.sh publishes for the
fleet. Every function here answers a question about the world; not one of
them returns a renderable, and NO RICH IS IMPORTED. That is a deliberate
constraint rather than an accident of what happened to move: it is what lets
the watchdog, a test or a bot ask this module a question without a terminal,
and it is checked by importing it with rich uninstalled.

WHAT THAT BUYS, measured against the bash implementation this replaced:

    bash : 216 ms and 248 forks per frame
    this :  12.9 ms and   2 forks per frame

(An earlier synthetic benchmark suggested 1.5 ms; that one did not walk /proc.
The honest figure is 12.9 ms -- still ~17x cheaper and 124x fewer forks, with
the remaining cost dominated by reading stat/statm/cmdline for every process
on the system.)

The difference is not Python being fast; it is that the bash version forked
ps twice, ss once, ps -o pgid per listening socket and sed PER LINE for width
measurement, every two seconds, forever, on a battery-powered handheld. Every
collector below reads /proc directly instead, and the session table is a file
the watchdog publishes rather than a tmux capture per window.

That figure is the budget everything registered into the frame is held to as
well -- which is why App.add_badge's docstring says a badge must not fork.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from dashboard.core import (
    HANDOVERS_DIR, HOME, PAGE, PROFILE, SCRIPTS, TICKS, USAGE_MAX_AGE,
    WATCHDOG_DIR, WATCHDOG_DIRECTIVES, WATCHDOG_ENABLED,
    WATCHDOG_HEARTBEAT, WATCHDOG_HOORAY, WATCHDOG_MON_OPTOUT, WATCHDOG_MONITOR,
    WATCHDOG_OPTOUT, WATCHDOG_REPOS, WATCHDOG_SCHED_WHY, WATCHDOG_STATUS,
    WATCHDOG_TREE, WATCHDOG_USAGE, WATCHDOG_USAGE_FAIL, profile_of, read)
# THE HANDOVER RULES, which are not this module's: what "open" and "done"
# mean is one definition shared with the watchdog, and handover_state below
# is a call to it rather than a second copy that drifted once already.
import muxhandovers
# THE ONE EDGE TO dashboard.schedules, and it is one function: a live window's
# lane slug is the executor's slug rule applied to a tmux name, and that rule
# has exactly one implementation on this side (sanitise_slug). Importing it is
# cheaper than a second copy that could drift -- which is the bug the rule's
# own docstring is about.
from dashboard.schedules import sanitise_slug


# --------------------------------------------------------------------------
# collectors -- all of these read /proc; none of them fork
# --------------------------------------------------------------------------
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


def lane_slug_of(window: str) -> str:
    """A live window's lane slug: its tmux name with the depth markers off.

    Every handover path is built from the SLUG, never from the display name --
    or a wind-down asks for STATUS-➥27-storage.md while the same window's own
    footer told the worker STATUS-27-storage.md."""
    return sanitise_slug(window.replace("➥", "")) or window



def heartbeat_age() -> float:
    """Seconds since the watchdog last completed a pass; -1 if it never has."""
    try:
        first = WATCHDOG_HEARTBEAT.read_text().split("\t")[0]
        return time.time() - int(first)
    except (OSError, ValueError, IndexError):
        return -1.0


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


def read_tree() -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        for line in WATCHDOG_TREE.read_text().splitlines():
            p = line.split("\t")
            if len(p) < 5 or not p[0]:
                continue
            try:
                at = int(p[4])
            except ValueError:
                at = 0
            out[p[0]] = {"slug": p[0], "parent": p[1], "wid": p[2],
                         "pane": p[3], "at": at,
                         "file": p[5] if len(p) > 5 else ""}
    except OSError:
        pass
    return out


def live_windows() -> set[str]:
    """Which tmux window ids exist right now. One fork, and only in the
    schedules view -- the main frame is measured in forks per second."""
    try:
        out = subprocess.run(["tmux", "list-windows", "-a", "-F", "#{window_id}"],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {l.strip() for l in out.splitlines() if l.strip()}


def handover_state(slug: str) -> tuple[str, float]:
    """What the lane's handover says about it: open, done, or nothing yet.

    ONE DEFINITION, and it is muxhandovers'. This used to test the OPEN file
    first while the watchdog's sched_dep_state tested `done/` first, so a lane
    that ran, was marked done and ran again -- which has both files -- was
    `open` to the WHY line and `done` to every `after: <slug>`. The
    disagreement was invisible and the dashboard was the one that was wrong:
    `after:` is what the executor acts on. muxhandovers.lane_state mirrors
    that order and tests/test_handovers.py greps it out of the shell.
    """
    return muxhandovers.lane_state(HANDOVERS_DIR, slug)


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
# the two global switches -- writers, beside the readers above
#
# THE FLAG ONLY DECIDES WHETHER THE WATCHDOG MAY TYPE into a window, which is
# the part that spends tokens; it keeps polling and publishing either way.
# They live here rather than with the menu rows that flip them because the
# `w` and `m` keys reach them from every view, and a key should not have to
# import a menu.
# --------------------------------------------------------------------------
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


def toggle_monitor() -> str:
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
