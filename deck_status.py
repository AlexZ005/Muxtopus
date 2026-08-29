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
        self.version = (SCRIPTS / "VERSION").read_text().strip() if (SCRIPTS / "VERSION").exists() else "?"

    def say(self, msg: str) -> None:
        self.notice, self.notice_at = msg, time.time()

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
        head = Table.grid(padding=(0, 1))
        head.add_column(width=5)
        head.add_column()
        head.add_row(Text("MEM", style="bold"),
                     Text.assemble(gauge(used_pct), "  ",
                                   (f"{avail:.1f}", "bold"), f" of {total:.1f} GiB free   ",
                                   (f"{used_pct:.0f}% used", DIM)))
        head.add_row(Text("SWP", style="bold"),
                     Text(f"{sw_used:.1f} of {sw_total:.1f} GiB zram", style=DIM))
        head.add_row(Text("CPU", style="bold"),
                     Text.assemble(sparkline(self.cpu.sample()), "  ",
                                   ("load ", DIM), load, "   ",
                                   (f"{hottest_c()}C", DIM), "   ",
                                   (power + " ", DIM), f"{bat}%"))

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
        lanes.add_column("STATE", width=16)

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
            lanes.add_row(
                Text(str(pgid_port.get(pgid, "—")), style="#8fb8de"),
                human_mb(g["rss"]),
                Text(human_age(age), style=style),
                lane_name(g["pid"]),
                Text(state, style=style),
            )
        if not groups:
            lanes.add_row(Text("—", style=DIM), "", "", Text("no dev servers running", style=DIM), "")

        # ---- system -------------------------------------------------------
        claude = [p for p in procs if p.comm == "claude"]
        pw = sum(p.rss_mb for p in procs if "ms-playwright" in p.cmdline)
        extras = sum(p.rss_mb for p in procs if any(h in p.cmdline for h in EXTRA_HINTS))
        try:
            st = os.statvfs(str(HOME))
            free = f"{st.f_bavail * st.f_frsize / 1073741824:.0f} GiB"   # GiB, matching df -h
        except OSError:
            free = "?"

        sysrow = Text.assemble(
            ("claude ", "bold"), f"{len(claude)} · {human_mb(sum(p.rss_mb for p in claude))}",
            "     ", ("playwright ", "bold"), (human_mb(pw) if pw else "—"),
            "     ", ("/home ", "bold"), f"{free} free",
            "     ", ("desktop extras ", "bold"), human_mb(extras),
            ("  (s reclaims)", DIM),
        )

        keys = Text.assemble(
            (" q", DIM), " quit  ", ("r", DIM), " refresh  ", ("R", DIM), " reload  ",
            ("s", DIM), " stop extras  ", ("S", DIM), " start  ",
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
            Panel(sysrow, title="[bold]system", title_align="left",
                  border_style=FRAME, box=box.ROUNDED),
            keys,
        )


HELP = f"""
  [bold]deck-status[/] -- lane dashboard

  [bold]q[/] quit        [bold]r[/] redraw now      [bold]R[/] reload this script
  [bold]s[/] stop extras [bold]S[/] start extras    (deck-ram.sh, desktop mode only)
  [bold]p[/] btop        [bold]?[/] this screen

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
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.read(1) if r else None


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
