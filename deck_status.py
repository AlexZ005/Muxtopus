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
WATCHDOG_DIR = STATE_HOME / "claude-watchdog"
WATCHDOG_STATUS = WATCHDOG_DIR / "status.tsv"
WATCHDOG_ENABLED = WATCHDOG_DIR / "enabled"
WATCHDOG_OPTOUT = WATCHDOG_DIR / "optout"
WATCHDOG_REPOS = WATCHDOG_DIR / "repos.tsv"
WATCHDOG_USAGE = WATCHDOG_DIR / "usage.tsv"
# Both sessions on this machine run a 1M-context model. There is no way to ask
# a running session what its window is, so this is an assumption the bar is
# drawn against, overridable rather than hidden.
CONTEXT_WINDOW = int(os.environ.get("CLAUDE_CONTEXT_WINDOW", "1000000"))
# The watchdog republishes every 30s; past double that it is not running.
STALE_AFTER = 75.0


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
                 "resumed", "spent", "cached", "optout", "model", "idle")

    def __init__(self, sid, window, pane, ver, ctx, state, reset, action,
                 resumed=0, spent=0, cached=0, optout=False, model="-", idle=-1):
        self.sid, self.window, self.pane, self.ver = sid, window, pane, ver
        self.ctx, self.state, self.reset, self.action = ctx, state, reset, action
        self.resumed, self.spent, self.cached = resumed, spent, cached
        self.optout, self.model = optout, model
        self.idle = idle


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
        ))
    return out, age


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


def usage_rows() -> list[Text]:
    """Three lines for the header's right edge, or one saying how to get them."""
    u = usage_limits()
    if not u.get("at"):
        return [Text("usage unknown", style=DIM), Text("press u to read it", style=DIM), Text()]

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
    return [
        row("Session", "session_pct", "session_reset"),
        row("Week", "week_pct", "week_reset"),
        row(model, "model_pct", "", f" · read {seen}"),
    ]


def refresh_usage() -> str:
    """Fire the scrape and return immediately -- it spawns a Claude session and
    takes a few seconds, and blocking the frame for that would freeze the whole
    dashboard. The panel picks the result up on a later frame."""
    script = SCRIPTS / "claude-usage.sh"
    if not script.exists():
        return "claude-usage.sh not found"
    try:
        subprocess.Popen([str(script), "--refresh"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "reading usage limits…"
    except OSError as exc:
        return f"usage refresh failed: {exc}"


def dirty_repos() -> list[tuple[str, int]]:
    """(name, changed files) for every repo the watchdog found dirty."""
    out = []
    try:
        for line in WATCHDOG_REPOS.read_text().splitlines():
            f = line.split("\t")
            if len(f) >= 3:
                try:
                    out.append((f[1], int(f[2])))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


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
        self.cursor = ""            # session id under the row cursor
        self.sids: list[str] = []   # last rendered order, for the arrow keys
        self.panes: dict[str, str] = {}   # session id -> tmux pane, for Enter
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
        pane = self.panes.get(self.cursor, "")
        if not pane:
            return f"{self.cursor[:8]} is a background session — no window to open"
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

        lanes = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                      header_style=DIM, border_style=FRAME)
        lanes.add_column("PORT", width=6)
        lanes.add_column("RAM", justify="right", width=10)
        lanes.add_column("AGE", justify="right", width=6)
        lanes.add_column("LANE", overflow="ellipsis", ratio=1)
        lanes.add_column("DIRTY", justify="right", width=6)
        lanes.add_column("STATE", width=16)

        # A session's cwd is /home/deck here, which is not a repo, so "has this
        # work been committed" cannot be answered per SESSION. It can be
        # answered per lane, because a lane row IS a working tree.
        dirty = dict(dirty_repos())

        total_mb = sum(g["rss"] for g in groups.values())
        for pgid in sorted(groups, key=lambda k: pgid_port.get(k, 99999)):
            g = groups[pgid]
            age = g["age"]
            if age >= 86400:
                state, style = "stale, restart", RED
            elif age >= 21600:
                state, style = "ageing", YELLOW
            else:
                state, style = "fresh", GREEN
            lname = lane_name(g["pid"])
            n = dirty.get(lname.rsplit("/", 1)[-1], 0)
            lanes.add_row(
                Text(str(pgid_port.get(pgid, "—")), style="#8fb8de"),
                human_mb(g["rss"]),
                Text(human_age(age), style=style),
                lname,
                Text(str(n) if n else "—", style=YELLOW if n else FRAME),
                Text(state, style=style),
            )
        if not groups:
            lanes.add_row(Text("—", style=DIM), "", "",
                          Text("no dev servers running", style=DIM), "", "")

        # ---- claude sessions ----------------------------------------------
        sessions, sess_age = claude_sessions()
        wd_on = WATCHDOG_ENABLED.exists()
        wd_stale = sess_age < 0 or sess_age > STALE_AFTER

        ordered = sorted(sessions, key=lambda x: -x.ctx)
        # The cursor is tracked by session id, not by row index: the table is
        # sorted by context and that order changes under you as sessions work.
        self.sids = [s.sid for s in ordered]
        self.panes = {s.sid: s.pane for s in ordered}
        if self.cursor not in self.sids:
            self.cursor = self.sids[0] if self.sids else ""

        ct = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                   header_style=DIM, border_style=FRAME)
        ct.add_column("", width=3)
        ct.add_column("WINDOW", overflow="ellipsis", ratio=1)
        ct.add_column("MODEL", width=11, overflow="ellipsis")
        ct.add_column("CONTEXT", width=29)
        ct.add_column("SPENT", justify="right", width=8)
        ct.add_column("IDLE", justify="right", width=6)
        ct.add_column("STATE", width=15)
        ct.add_column("RESUMED", width=11)

        skipped = opted_out()
        for s in ordered:
            s.optout = s.sid in skipped
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
            ct.add_row(mark, Text(s.window), Text(s.model, style=DIM), bar,
                       Text(human_tokens(s.spent), style=DIM), idle_txt, st_txt,
                       Text(when(s.resumed), style=DIM if s.resumed else FRAME))

        if not sessions:
            ct.add_row("", Text("—", style=DIM), "",
                       Text("no claude sessions" if not wd_stale else "watchdog not running",
                            style=DIM), "", "", "", "")

        wd_label = ("watchdog on", GREEN) if wd_on else ("watchdog off", DIM)
        if wd_stale:
            wd_label = ("watchdog not running", RED)
        spent_all = sum(s.spent for s in sessions)
        ctitle = Text.assemble(("claude", "bold"),
                               (f" · {len(sessions)} session(s) · ", DIM),
                               (human_tokens(spent_all), "bold"), (" spent · ", DIM),
                               wd_label)

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
        lane_names = {lane_name(g["pid"]).rsplit("/", 1)[-1] for g in groups.values()}
        elsewhere = [(n, c) for n, c in dirty.items() if n not in lane_names]
        uncommitted = Text()
        if elsewhere:
            uncommitted.append("uncommitted ", style="bold")
            uncommitted.append(", ".join(f"{n} ({c})" for n, c in sorted(elsewhere)),
                               style=YELLOW)
            uncommitted.append("     ")

        sysrow = Text.assemble(
            uncommitted,
            ("claude ", "bold"), f"{len(claude)} · {human_mb(sum(p.rss_mb for p in claude))}",
            "     ", ("playwright ", "bold"), (human_mb(pw) if pw else "—"),
            "     ", ("/home ", "bold"), f"{free} free",
            "     ", ("desktop extras ", "bold"), human_mb(extras),
            ("  (s reclaims)", DIM),
        )

        keys = Text.assemble(
            (" q", DIM), " quit  ", ("r", DIM), " refresh  ", ("R", DIM), " reload  ",
            ("s", DIM), " stop extras  ", ("S", DIM), " start  ",
            ("w", DIM), " watchdog  ", ("u", DIM), " usage  ", ("↑↓", DIM), " pick  ", ("enter", DIM), " open  ", ("space", DIM), " skip  ",
            ("p", DIM), " btop  ", ("?", DIM), " help",
        )
        if self.notice and time.time() - self.notice_at < 8:
            keys = Text.assemble((" " + self.notice, "#c9a0dc"), "\n", keys)

        return Group(
            Panel(head, title="[bold]deck", subtitle=f"[{DIM}]{subtitle}",
                  subtitle_align="right", border_style=FRAME, box=box.ROUNDED),
            Panel(lanes,
                  title=f"[bold]lanes[/] [{DIM}]· {len(groups)} server(s) · {human_mb(total_mb)}",
                  title_align="left", border_style=FRAME, box=box.ROUNDED),
            Panel(ct, title=ctitle, title_align="left",
                  border_style=FRAME, box=box.ROUNDED),
            Panel(sysrow, title="[bold]system", title_align="left",
                  border_style=FRAME, box=box.ROUNDED),
            keys,
        )


HELP = f"""
  [bold]deck-status[/] -- lane dashboard

  [bold]q[/] quit        [bold]r[/] redraw now      [bold]R[/] reload this script
  [bold]s[/] stop extras [bold]S[/] start extras    (deck-ram.sh, desktop mode only)
  [bold]w[/] watchdog    [bold]p[/] btop            [bold]?[/] this screen
  [bold]u[/] read usage limits      [bold]up/down[/] pick   [bold]space[/] include or skip
  [bold]enter[/] open the selected session's window (Ctrl-b 0 comes back here)

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

    The same values are available to scripts and to prompts:
      claude-usage.sh --brief | --json | --session-pct | --week-pct
      claude-usage.sh --ensure 15     refresh only if older than 15 minutes
    Every reading is appended to usage.log with a timestamp.

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
    if data == b"\x1b" and select.select([fd], [], [], 0.05)[0]:
        data += os.read(fd, 16)
    if data.startswith(b"\x1b[") and len(data) >= 3:
        return {b"A": "UP", b"B": "DOWN"}.get(data[2:3], "\x1b")
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
    interval = 2.0
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
                key = read_key(interval)
                if key in ("q", "Q"):
                    break
                if key == "R":
                    # A running process holds the copy it started with; re-exec
                    # so an edited script takes effect without respawning tmux.
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
                elif key in ("u", "U"):
                    dash.say(refresh_usage())
                elif key == "UP":
                    dash.move(-1)
                elif key == "DOWN":
                    dash.move(1)
                elif key in ("\r", "\n"):
                    dash.say(dash.open_selected())
                elif key == " ":
                    dash.say(dash.toggle_selected())
                elif key in ("w", "W"):
                    dash.say(toggle_watchdog())
                elif key == "s":
                    dash.say("stopping desktop extras…")
                    live.update(dash.build(), refresh=True)
                    dash.say(run_deck_ram("stop"))
                elif key == "S":
                    dash.say("starting desktop extras…")
                    live.update(dash.build(), refresh=True)
                    dash.say(run_deck_ram("start"))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
