"""dashboard.views.main -- the screen the dashboard opens on.

The deck header, the lanes table, the claude sessions with the tree drawn
into them, the uncommitted trees, the system line -- and the session menu
that space opens over a row, with everything it can do to that window.

THE FRAME IS MEASURED IN FORKS PER SECOND: 12.9 ms and 2 forks, against the
216 ms and 248 of the bash version this replaced. Everything here reads /proc
or a file the watchdog published; nothing here runs a command per row. A
badge registered by another module is held to the same rule, and App's
add_badge docstring says so.

WHAT OTHER MODULES MAY ASK THIS VIEW is the five accessors at the foot of
MainView and nothing else; docs/dashboard-views.md carries the same list.
"""
from __future__ import annotations

import os
import subprocess
import time

from rich import box
from rich.console import Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dashboard.app import View
from dashboard.menulayout import (PAGE_KEYS, TABLE_MIN, fit_columns,
                                  make_table, page_jump, rendered_height,
                                  share_rows)
from dashboard.core import (CONTEXT_WINDOW, DIM, EXTRAS_SENTINEL, EXTRA_HINTS,
                            FRAME_INTERVAL, USAGE_MAX_AGE, WATCHDOG_TREE,
                            WD_INTERVAL, knob,
                            FRAME, GREEN, HANDOVERS_DIR, HOME, LANES_EMPTY,
                            LANE_PREFIX, MULTI_ACCOUNT, PROFILE,
                            PROFILE_LABEL, RED, SCRIPTS, SERVER_HINTS,
                            STALE_AFTER, STATES, WATCHDOG_DIR,
                            WATCHDOG_DIRECTIVES, WATCHDOG_ENABLED,
                            WATCHDOG_MON_OPTOUT, WATCHDOG_MSG, WATCHDOG_OPTOUT,
                            YELLOW, gauge, human_age, human_mb, human_tokens,
                            pressure, read, sparkline, when)
from dashboard.data import (Cpu, claude_sessions, dirty_for, dirty_repos,
                            drop_dead, first_glob, heartbeat_age, hooray,
                            hottest_c, lane_account, lane_name, lane_slug_of,
                            listening_inodes, meminfo, monitor_on,
                            monitor_opted_out, opted_out, ports_for,
                            processes, read_tree, session_mode,
                            toggle_watchdog, uptime_seconds, usage_failure,
                            usage_limits)

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


class MainView(View):
    """The main screen, and the only view with no key: it is what `s` and
    everything after it come back to."""

    name, key, order = "main", None, 10

    def __init__(self, app) -> None:
        self.app = app
        self.cpu = Cpu()
        self.cursor = ""            # session id under the row cursor
        self.sids: list[str] = []   # last rendered order, for the arrow keys
        self.panes: dict[str, str] = {}   # session id -> tmux pane, for Enter
        self.jobs: dict[str, str] = {}    # session id -> bg job id, for attach
        self.windows: dict[str, str] = {}  # session id -> tmux window name
        self.cwds: dict[str, str] = {}     # session id -> working directory
        # THE LANES TABLE IS THIS ACCOUNT'S BY DEFAULT. Two dashboards side by
        # side listing the same servers is the same confusion the session
        # suffix exists to prevent; f (or enter on a lane row) shows them all.
        self.lanes_all = False
        self.lane_keys: list[str] = []     # lane rows in rendered order
        # THE TREE VIEW. tmux has no window hierarchy, so this is a rendering
        # of tree.tsv, not of tmux. On by default and IDENTICAL to the old
        # ordering until something actually has a parent: roots keep the
        # sort-by-context order, children hang under their root.
        self.tree_mode = True
        self.collapsed: set[str] = set()   # session ids whose subtree is hidden
        self.tree_kids: dict[str, list[str]] = {}
        self.tree_parent: dict[str, str] = {}
        self.lane_acct: dict[int, str | None] = {}   # pid -> account, cached
        # What build worked out and the footer and the menu anchor then need.
        # Stashed rather than recomputed: they are decided halfway down a
        # frame that costs 12.9 ms, and App asks for them in that order.
        self._foot = None
        self._anchor = 2
        # THE SESSIONS TABLE'S PAGE, for PageUp/PageDown: the row lines
        # fit_height actually gave it this frame. The cursor walks one list
        # (lanes, then sessions, then the extras row) but it lives in the
        # sessions table, so that table's viewport is what a page means here.
        self._page = TABLE_MIN

    # -------------------------------------------------------- the protocol
    def build(self, app) -> list:
        return self.build_main()

    def menu_anchor(self, app) -> int:
        return self._anchor

    def footer(self, app):
        return self._foot

    def on_key(self, app, key) -> bool:
        return self.main_key(key)

    def move(self, delta: int) -> None:
        if not self.sids:
            return
        self.cursor = self.sids[max(0, min(len(self.sids) - 1,
                                           self.cursor_row() + delta))]

    def cursor_row(self) -> int:
        """Where the cursor is in the ONE list the arrows walk."""
        try:
            return self.sids.index(self.cursor)
        except ValueError:
            return 0

    def page(self, key: str) -> None:
        """PageUp/PageDown/Home/End down the same list, clamped at both ends.

        Home and End are the FIRST AND LAST ROW OF THE SCREEN -- the topmost
        lane and the extras row -- and not the first and last session: the
        cursor is one cursor top to bottom, and an End that stopped short of
        the row it can see at the bottom would be the surprising one."""
        if not self.sids:
            return
        j = page_jump(key, self.cursor_row(), len(self.sids), self._page)
        if j is not None:
            self.cursor = self.sids[j]

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

    # ----------------------------------------------- the menus' own titles
    # Names are escaped: a window called [x] would otherwise be read as a
    # style by Rich's markup.
    def _session_menu_title(self) -> str:
        win = self.windows.get(self.cursor, "")
        if win:
            return "menu[/] [%s]· %s" % (DIM, escape(win))
        return "menu"

    def session_menu_entries(self) -> list[dict]:
        """The per-window menu (space in the main view)."""
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
                # "Schedule ➥resume of ..." used to sit here. It writes a
                # schedule entry, so it belongs to the schedule view, and it
                # arrives back in this list through app.add_rows("session",
                # ..., order=85) -- the registry doing the one job the old
                # code really did reach across a view boundary to do.
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

    def act_rename(self) -> str:
        win = self.windows.get(self.cursor, "")
        self.app.prompt = {"title": "Rename %s to" % (win or "window"), "buf": "",
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
        self.app.confirm = {"label": "Close %s? The claude session in it is killed." % win,
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
               % (HANDOVERS_DIR, lane_slug_of(win), reset))
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

    # ---------------------------------------------------------- the tree
    def tree_layout(self, ordered: list) -> list[tuple]:
        """Sessions as (session, depth, hidden_count), parents before children.

        tmux CANNOT do this: its windows are a flat indexed list with no
        parent/child relation to read. The relation lives in the scheduler's
        tree.tsv, matched back to live sessions by pane id (exact) and then by
        window name with the ➥ markers stripped (for a pane that was recreated).
        """
        self.tree_kids = {}
        self.tree_parent = {}
        if not self.tree_mode:
            return [(s, 0, 0) for s in ordered]

        tree = read_tree()
        by_pane = {n["pane"]: n for n in tree.values() if n["pane"]}
        slug_of: dict[str, str] = {}
        for s in ordered:
            n = by_pane.get(s.pane) or tree.get((s.window or "").lstrip("➥"))
            if n:
                slug_of[s.sid] = n["slug"]
        sid_of = {slug: sid for sid, slug in slug_of.items()}

        kids: dict[str, list] = {}
        roots: list = []
        for s in ordered:
            slug = slug_of.get(s.sid)
            parent = tree[slug]["parent"] if slug else ""
            psid = sid_of.get(parent) if parent else None
            if psid and psid != s.sid:
                kids.setdefault(psid, []).append(s)
                self.tree_parent[s.sid] = psid
            else:
                roots.append(s)
        self.tree_kids = {k: [c.sid for c in v] for k, v in kids.items()}

        # A row that names an ancestor of itself as its parent would recurse
        # forever; seen[] is cheaper than validating the file.
        rows: list[tuple] = []
        seen: set[str] = set()

        def count(s) -> int:
            n = 0
            for k in kids.get(s.sid, []):
                n += 1 + count(k)
            return n

        def swallow(s) -> None:
            """Mark a hidden subtree as placed. Without this the orphan sweep
            below would helpfully put every collapsed child back at the bottom
            of the table, which is the opposite of collapsing it."""
            for k in kids.get(s.sid, []):
                seen.add(k.sid)
                swallow(k)

        def walk(s, depth: int) -> None:
            if s.sid in seen:
                return
            seen.add(s.sid)
            children = kids.get(s.sid, [])
            hidden = count(s) if (children and s.sid in self.collapsed) else 0
            rows.append((s, depth, hidden))
            if hidden:
                swallow(s)
                return
            for k in children:
                walk(k, depth + 1)

        for r in roots:
            walk(r, 0)
        # Anything left out by a broken parent chain is still shown: a session
        # missing from the table is worse than one drawn at the wrong depth.
        for s in ordered:
            if s.sid not in seen:
                rows.append((s, 0, 0))
        return rows

    def tree_collapse(self) -> str:
        """LEFT: fold the subtree under the cursor, or step out to the parent."""
        sid = self.cursor
        if self.tree_kids.get(sid) and sid not in self.collapsed:
            self.collapsed.add(sid)
            return "collapsed %s" % (self.windows.get(sid, sid[:8]))
        parent = self.tree_parent.get(sid)
        if parent:
            self.cursor = parent
            return ""
        return ""

    def tree_expand(self) -> str:
        """RIGHT: unfold the subtree, or step into the first child."""
        sid = self.cursor
        if sid in self.collapsed:
            self.collapsed.discard(sid)
            return "expanded %s" % (self.windows.get(sid, sid[:8]))
        kids = self.tree_kids.get(sid)
        if kids:
            self.cursor = kids[0]
        return ""

    def toggle_tree(self) -> str:
        self.tree_mode = not self.tree_mode
        if not self.tree_mode:
            self.collapsed.clear()
        return ("tree: children under their parent (←/→ fold)"
                if self.tree_mode else "tree off: sessions by context")

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

    def build_main(self) -> list:
        """The main view's SECTIONS, top to bottom, with its footer and its
        menu anchor put where MainView can find them. What used to end in a
        Group ends in a list: App places an open menu among the sections, so
        every view gets the placer the schedule view once needed its own
        copy of."""
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

        subtitle = f"{os.uname().nodename} · {len(os.sched_getaffinity(0))} threads · {mode} mode · v{self.app.version}"

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

        # COLUMNS AS DATA, then the table is made at the end, once the frame
        # knows how wide and how tall it may be (fit_columns, make_table).
        # The number is the order a narrow terminal gives a column up in,
        # lowest first; None never goes. LANE is where "▼ N more" is drawn.
        lane_cols = [
            ("", {"width": 2}, None),
            ("PORT", {"width": 6}, None),
            ("RAM", {"justify": "right", "width": 10}, 3),
            ("AGE", {"justify": "right", "width": 6}, 2),
            ("LANE", {"ratio": 1, "min_width": 12}, None),
        ]
        # Only the unfiltered view needs to say whose a row is; in the
        # filtered one the answer is the panel title.
        if self.lanes_all:
            lane_cols.append(("ACCOUNT", {"width": 10}, 4))
        lane_cols += [
            ("DIRTY", {"justify": "right", "width": 6}, 1),
            ("STATE", {"width": 16}, 5),
        ]
        lane_rows: list[list] = []

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
            lane_rows.append(cells)
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
            lane_rows.append(cells)
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
        # THE HEARTBEAT IS THE DIRECT ANSWER; the status file's mtime is the
        # inference that used to stand in for it, and it stays as the fallback
        # for a daemon too old to write one.
        hb = heartbeat_age()
        scanned = hb if hb >= 0 else sess_age
        wd_stale = scanned < 0 or scanned > STALE_AFTER

        ordered = sorted(sessions, key=lambda x: -x.ctx)
        # ...then hung into a tree, parents before children. With nothing
        # parented -- every session today -- this is the same list in the same
        # order, so the tree costs nothing until there is one.
        layout = self.tree_layout(ordered)
        visible = [s for s, _, _ in layout]
        # The cursor is tracked by session id, not by row index: the table is
        # sorted by context and that order changes under you as sessions work.
        self.sids = [s.sid for s in visible]
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
        # EVERY COLUMN IS no_wrap (make_table adds it): a row that wraps is
        # a row two lines tall, and a table whose row height depends on the
        # terminal's width cannot be given a row budget. That was the 80x24
        # client: CONTEXT wrapped its token count onto a second line and the
        # footer went off the bottom.
        # Under 100 columns the context gauge is 6 cells, not 14: the figure
        # beside it is what is read, and the 8 cells go to STATE.
        wide = self.app.console.size.width >= 100
        ct_cols = [
            ("", {"width": 3}, None),
            ("MON", {"width": 4}, 3),
            ("WINDOW", {"ratio": 1, "min_width": 12}, None),
            ("MODEL", {"width": 11}, 7),
            # Last to go, and only on a phone-width terminal: the window's
            # name and its state are what the row is for.
            ("CONTEXT", {"width": 29 if wide else 21}, 8),
            ("SPENT", {"justify": "right", "width": 8}, 4),
            ("IDLE", {"justify": "right", "width": 6}, 5),
            ("STATE", {"width": 15}, None),
            ("DIRTY", {"justify": "right", "width": 6}, 6),
        # 12, NOT 11, AND no_wrap. when() renders a stamp older than today as
        # "%b %-d %H:%M" -- "Sep 5 21:13" is 11 and fitted, "Sep 12 12:21" is 12
        # and did not, so every row wound or resumed on a two-digit day wrapped
        # onto a second line and tore the table in half. A width that depends on
        # the day of the month is a width that is wrong two thirds of the time;
        # no_wrap is the belt to that braces, because a cell that cannot wrap
        # can never take a row with it.
            ("WOUND", {"width": 12}, 2),
            ("RESUMED", {"width": 12}, 1),
        ]
        ct_rows: list[list] = []
        ct_cur = -1

        skipped = opted_out()
        mskipped = monitor_opted_out()
        for s, depth, hidden in layout:
            s.optout = s.sid in skipped
            s.moptout = s.sid in mskipped
            pct = min(100.0, s.ctx * 100.0 / CONTEXT_WINDOW) if CONTEXT_WINDOW else 0.0
            bar = Text.assemble(gauge(pct, 14 if wide else 6), " ",
                                (f"{pct:3.0f}%", pressure(pct)), " ",
                                (human_tokens(s.ctx), DIM))
            mark = Text()
            mark.append("▸" if s.sid == self.cursor else " ",
                        style="bold #c9a0dc")
            mark.append("✔" if not s.optout else "·",
                        style=DIM if s.optout else GREEN)
            # HOW A STATE IS DRAWN is dashboard.core.STATES, so a module
            # that teaches the watchdog a new state teaches this column in
            # one line (app.add_state) instead of editing the chain this used
            # to be. An UNREGISTERED state keeps the fallback it has always
            # had -- dim, under its own name -- which is what an unknown
            # state from a newer watchdog has to do. The reset time rides on
            # the two states that have one, which is why the table carries a
            # third field and not just a style.
            label, style, with_reset = STATES.get(s.state, (s.state, DIM, False))
            st_txt = Text(label + (" " + s.reset if with_reset else ""),
                          style=style)
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
            # DEPTH IS DRAWN, not stored in tmux: the window name carries its
            # own ➥ markers, and this adds the indent the flat list cannot.
            if depth:
                wtx = Text.assemble(("  " * depth + "└ ", FRAME), s.window)
            else:
                wtx = Text(s.window)
            if hidden:
                wtx.append("  +%d" % hidden, style="bold #c9a0dc")
            # WHAT OTHER MODULES HAVE TO SAY ABOUT THIS SESSION -- the yellow
            # `?` of an unanswered fork, and whatever comes after it. One
            # short Text each, no forks (App.add_badge's docstring is the
            # rule), and none registered means nothing appended.
            for badge in self.app.badges(s):
                wtx.append(" ")
                wtx.append_text(badge)
            if s.sid == self.cursor:
                ct_cur = len(ct_rows)
            ct_rows.append([mark, mon_txt, wtx, Text(s.model, style=DIM), bar,
                       Text(human_tokens(s.spent), style=DIM), idle_txt, st_txt,
                       dirty_txt,
                       Text(when(s.wound), style=DIM if s.wound else FRAME),
                       Text(when(s.resumed), style=DIM if s.resumed else FRAME)])

        if not sessions:
            ct_rows.append(["", "", Text("—", style=DIM), "",
                            Text("no claude sessions" if not wd_stale else "watchdog not running",
                                 style=DIM), "", "", "", "", "", ""])

        wd_label = ("watchdog on", GREEN) if wd_on else ("watchdog off", DIM)
        if wd_stale:
            wd_label = ("watchdog not running", RED)
        mon = mon_all
        spent_all = sum(s.spent for s in sessions)
        mon_label = ("monitor on", GREEN) if mon else ("monitor off", DIM)
        acct = f" [{PROFILE_LABEL}]" if MULTI_ACCOUNT else ""
        scan_txt = ("scan %s ago" % human_age(scanned)) if scanned >= 0 \
            else "never scanned"
        ctitle = Text.assemble(("claude", "bold"),
                               (acct, YELLOW if PROFILE else DIM),
                               (f" · {len(sessions)} session(s) · ", DIM),
                               (human_tokens(spent_all), "bold"), (" spent · ", DIM),
                               wd_label, (" · ", DIM),
                               (scan_txt, RED if wd_stale else DIM), (" · ", DIM),
                               mon_label)

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
            ("w", DIM), " watchdog  ", ("m", DIM), " monitor  ", ("u", DIM), "/", ("U", DIM), " usage  ", ("↑↓", DIM), " pick  ", ("pgup/dn home/end", DIM), " jump  ", ("enter", DIM), " open  ", ("space", DIM), " menu  ",
            ("esc", DIM), " muxtopus  ", ("c", DIM), " new session  ",
            ("←→", DIM), " fold  ", ("t", DIM), " tree  ",
            ("f", DIM), " all lanes  ", ("p", DIM), " btop  ", ("?", DIM), " help",
        )
        # ...and what other modules want on the key line: `· 3 ?`, and its
        # like. Appended before the notice and the flourish wrap it, so a
        # hint sits on the keys rather than above them.
        for hint in self.app.hints():
            keys.append_text(hint)
        # The one piece of good news this dashboard can deliver, so it gets to
        # be loud. Latched on first sight rather than read per frame: hooray()
        # consumes the flag, and the flag is written by a background process
        # that has no idea whether anyone is looking.
        if hooray():
            self.app.party_at = time.time()
        if time.time() - self.app.party_at < 120:
            keys = Text.assemble(
                ("  🎉  A LIMIT RESET EARLY — the clock lied, go again  🎉", "bold #7ec699"),
                "\n", keys)
        elif self.app.notice and time.time() - self.app.notice_at < 8:
            keys = Text.assemble((" " + self.app.notice, "#c9a0dc"), "\n", keys)

        self._foot = keys

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

        deck_panel = Panel(head, title="[bold]deck", subtitle=f"[{DIM}]{subtitle}",
                           subtitle_align="right", border_style=FRAME, box=box.ROUNDED)
        system_panel = Panel(sysrow, title="[bold]system", title_align="left",
                             border_style=FRAME, box=box.ROUNDED)
        lane_title = f"[bold]lanes[/] [{DIM}]· {len(shown)} server(s) · {human_mb(total_mb)}{lane_scope}"
        lane_cur = self.lane_keys.index(self.cursor) if self.cursor in self.lane_keys else -1
        sections = self.fit_height(
            deck_panel, panels, system_panel,
            (lane_cols, lane_rows, lane_cur, 4, lane_title),
            (ct_cols, ct_rows, ct_cur, 2, ctitle))
        # WHICH PANEL THE CURSOR IS IN, for an open menu to hang under: a
        # lane row, the extras row on the system line, or a session. The
        # muxtopus and settings menus follow the cursor too -- there is no
        # better anchor. Worked out here, where the sections exist, and read
        # back by MainView.menu_anchor.
        names = [n for n, _p in sections]
        if self.cursor.startswith(LANE_PREFIX):
            self._anchor = names.index("lanes")
        elif self.cursor == EXTRAS_SENTINEL:
            self._anchor = len(sections) - 1
        else:
            self._anchor = names.index("claude")
        return sections

    # ================================================= a short terminal
    def fit_height(self, deck_panel, dirty_panels, system_panel, lanes, claude) -> list:
        """The sections, with the lanes and claude tables given the rows the
        terminal HAS -- measured, the way App.place_menu measures a menu.

        What is left for the two tables is the height less what Rich will
        really draw for everything else (the footer included) and less each
        table's own chrome, which is measured by drawing it empty. The rows
        are split by menulayout.share_rows -- the sessions first -- and each
        table scrolls inside its share with the menus' rule and markers.

        THE DEGRADE RULE IS place_menu's: with less than TABLE_MIN row lines
        for a table (a row and both markers) the frame gives something up
        rather than cut a table -- the uncommitted panel first, then the
        deck header, then the system line (not while the cursor is on it)
        -- and the claude title says what went. Below even
        that the tables get their minimum and Live crops what is left,
        which is a terminal this screen does not claim to fit."""
        console = self.app.console
        height = console.size.height
        width = console.size.width
        specs = []
        for cols, rows, cur, marker, title in (lanes, claude):
            keep = fit_columns(cols, width)
            specs.append((cols, keep, rows, cur, marker, title))

        def tables(lines, note=""):
            out = []
            for k, (cols, keep, rows, cur, marker, title) in enumerate(specs):
                if note and k == 1:
                    title = title.copy() if isinstance(title, Text) else Text.from_markup(title)
                    title.append(note, style=DIM)
                # lines == "chrome": the table drawn EMPTY, which is what
                # its borders, header and rule cost with no rows at all.
                empty = lines == "chrome"
                out.append(Panel(make_table(cols, keep, [] if empty else rows, cur, marker,
                                            None if lines in (None, "chrome") else lines[k]),
                                 title=title, title_align="left",
                                 border_style=FRAME, box=box.ROUNDED))
            return out

        def assemble(lines, drop, note=""):
            lane_p, ct_p = tables(lines, note)
            return ([] if "deck" in drop else [("deck", deck_panel)]) + [
                ("lanes", lane_p), ("claude", ct_p),
                *([] if "uncommitted" in drop else [("uncommitted", p) for p in dirty_panels]),
                *([] if "system" in drop else [("system", system_panel)])]

        foot = self.app._submode_foot() or self._foot
        full = assemble(None, ())
        if rendered_height(console, Group(*[p for _n, p in full], foot)) <= height:
            # Every row drawn: the page is the sessions table's whole length,
            # so PageDown from the top lands where End does. That is what a
            # screenful means when the screen holds the lot.
            self._page = max(1, len(specs[1][2]))
            return full
        chrome = sum(rendered_height(console, p) for p in tables("chrome"))
        drop: list[str] = []
        steps = [[], ["uncommitted"], ["uncommitted", "deck"]]
        if self.cursor != EXTRAS_SENTINEL:
            steps.append(["uncommitted", "deck", "system"])
        for step in steps:
            drop = step
            if step == ["uncommitted"] and not dirty_panels:
                continue
            others = [p for n, p in assemble("chrome", drop) if n not in ("lanes", "claude")]
            room = height - chrome - rendered_height(console, Group(*others, foot))
            lines = share_rows(room, [len(sp[2]) for sp in specs])
            if lines is not None:
                break
        else:
            lines = [TABLE_MIN, TABLE_MIN]
        self._page = max(1, lines[1])
        note = (" · %s hidden: short terminal" % ", ".join(reversed(drop))) \
            if drop else ""
        return assemble(lines, drop, note)

    # ====================================================== the views' keys
    # Lifted out of main()'s one long chain, each branch under the view it
    # was always about. The ORDER inside each is the order it had; what is
    # NOT here is the shell's own (q R ? p u U w m f) and the keys that open
    # a view, both of which are checked after these, exactly as before.
    def main_key(self, key: str) -> bool:
        if key == "UP":
            self.move(-1)
        elif key == "DOWN":
            self.move(1)
        elif key in PAGE_KEYS:
            self.page(key)
        elif key in ("\r", "\n"):
            self.app.say(self.open_selected())
        elif key == " ":
            self.app.open_menu("session")
        elif key == "\x1b":
            # The dashboard's own menu: settings, the global switches,
            # disconnect, reload, quit.
            self.app.open_menu("mux")
        elif key == "c":
            # The c flow is its own module. If it failed to import, `c`
            # says so; it does not take the dashboard with it.
            flow = getattr(self.app, "newsession", None)
            if flow is None:
                self.app.say("the new-session flow failed to load")
            else:
                self.app.say(flow.start_new_session())
        elif key == "LEFT":
            self.app.say(self.tree_collapse())
        elif key == "RIGHT":
            self.app.say(self.tree_expand())
        elif key == "t":
            self.app.say(self.toggle_tree())
        else:
            return False
        return True


    # ------------------------------ WHAT OTHER MODULES MAY ASK THIS VIEW
    # The complete list, and it is short on purpose. docs/dashboard-views.md
    # carries the same five, so the coupling is a named call anybody can grep
    # for rather than `self.cursor` reached from the far side of the
    # dashboard. Nothing else in this file is anyone else's business.
    def cursor_sid(self) -> str:
        """The session id under the row cursor. "" on a lane row and on the
        extras row, which is what makes "is there a window to act on" one
        question rather than three."""
        sid = self.cursor
        if not sid or sid.startswith(LANE_PREFIX) or sid == EXTRAS_SENTINEL:
            return ""
        return sid

    def cursor_window(self) -> str:
        """Its tmux window NAME, ➥ markers and all."""
        return self.windows.get(self.cursor_sid(), "")

    def cursor_cwd(self) -> str:
        """Its working folder, or "" when it has none to speak of."""
        return self.cwds.get(self.cursor_sid(), "")

    def listed_sessions(self) -> list[tuple[str, str, str, str]]:
        """(sid, window, pane, cwd) for every session ROW this view drew, in
        the order it drew them -- what the cursor walks. A collapsed subtree
        is not in it, and neither are the lane rows or the extras row."""
        return [(sid, self.windows.get(sid, ""), self.panes.get(sid, ""),
                 self.cwds.get(sid, ""))
                for sid in self.sids
                if sid and not sid.startswith(LANE_PREFIX)
                and sid != EXTRAS_SENTINEL]

    def known_windows(self) -> list[str]:
        """Every live session's window name, collapsed subtrees INCLUDED --
        "is this slug taken" is a question about all of them, not about the
        ones that happen to be on screen."""
        return [w for w in self.windows.values() if w]



# The two bands the wind-downs use, quoted by the help section below. Named
# rather than inlined because the sentence explains why they are what they
# are, and a number in prose that nothing reads is a number that goes stale.
SOFT = knob("WATCHDOG_SOFT_PCT", PROFILE)
HARD = knob("WATCHDOG_HARD_PCT", PROFILE)


# ------------------------------------------------------------------ help
# This module's slice of `?`. Registered with the ORDER it has always had,
# so the help screen reads exactly as it did when it was one string in
# deck_status.py -- the split moved who owns the words, not the words.
HELP_TREE = f"""
  [{DIM}]THE WINDOW TREE[/]
    tmux has NO window hierarchy: its windows are a flat, indexed list per
    session, with no parent to set and nothing to collapse. So the tree is DATA
    the scheduler keeps ({WATCHDOG_TREE}) and this table is the VIEW of it.
    A window the scheduler opened from another one is drawn under it and
    indented; ← folds that subtree (the parent then shows +N), → unfolds it, and
    ← on a leaf steps out to the parent. With nothing parented the order is
    exactly what it always was -- sessions by context -- so the tree costs
    nothing until there is one. [bold]t[/] turns the ordering off entirely.

    What tmux CAN be made to honour is done in the flat list too: the depth is
    carried by the window name (➥lane, ➥➥child) and a child is inserted after
    the last window of its parent subtree, so a family stays contiguous.
"""

HELP_LANES = f"""
  [{DIM}]LANES AND ACCOUNTS[/]
    A dev server belongs to the account whose session started it -- read off
    CLAUDE_CONFIG_DIR in its environment, which it keeps even after the window
    that started it is gone. The table shows this account's by default; f, or
    enter on a lane row, shows every account's with each one labelled. Arrow
    up from the first session to reach the lane rows.
"""

HELP_MENU = f"""
  [{DIM}]THE MENU (space)[/]
    Two switches at the top, then everything you can do to the window under
    the cursor: open, rename, skip it, wind it down, resume it, continue it at
    low priority, or close it. Arrows pick, enter chooses, esc closes.
"""

HELP_SMALL = f"""
  [{DIM}]A SMALL TERMINAL[/]
    Nothing is cut off the bottom: the footer always stays on screen. When the
    rows run out, the lanes and claude tables give some up and scroll, showing
    "▲ N more" / "▼ N more" the way a long menu does, with the sessions served
    first. If that is still not enough, the uncommitted panel and then the deck
    header go, and the claude title says which. On a narrow terminal the
    less important columns go first (RESUMED, WOUND, DIRTY...) and the window
    names stay. The tab strip shortens its labels before it scrolls tabs.
"""

HELP_MONITORING = f"""
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
"""

HELP_UNCOMMITTED = f"""
  [{DIM}]UNCOMMITTED[/]
    Its own table rather than a column, because dirty trees and sessions do not
    line up: a repo can be dirty with no session and no dev server anywhere
    near it, and that is the copy most likely to be lost. The DIRTY column on a
    session row is a hint for the tree that window is sitting in.
"""

HELP_BACKGROUND = f"""
  [{DIM}]A session shown as (background) was started with `claude --bg`. It has no
  terminal, so there is no window for enter to open and no pane for the
  watchdog to type into -- it can be watched but never restarted from here.[/]
"""

HELP_USAGE = f"""
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
"""

HELP_CLAUDE = f"""
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
"""

HELP_DIRTY = f"""
  [{DIM}]UNCOMMITTED WORK[/]
    [bold]DIRTY[/] on the lanes table is tracked files changed in that working tree.
    It is not on the claude table because a session's cwd here is /home/deck,
    which is not a repo -- the question is only answerable per TREE. A dirty
    repo with no dev server would then be invisible, so the system line names
    those separately. Untracked files are ignored: a scratch file is noise, a
    modified tracked file is work you could lose.

    [{YELLOW}]limited[/]  stopped at a usage limit, waiting for the reset
    [{RED}]due[/]      the reset has passed and it is still sitting there
    [{RED}]stranded[/] NOTHING IS EVER GOING TO TOUCH THIS. A ➥ lane, idle past
             WATCHDOG_STRANDED (120m), with an OPEN handover, and no pending
             schedule entry naming it -- not by slug, not by after:, not a
             resume- entry. idle stays dim because it is a fact about the last
             turn and usually means finished; this is a fact about the future.
             It is a label, never a trigger: the watchdog only ever prompts a
             [{RED}]due[/] window. Schedule a ➥resume from the menu, or answer its
             handover.

    [bold]w[/] arms the watchdog: an IDLE window that hit a limit is prompted to
    continue once its reset time passes, once per limit. It never types into a
    window that is working. Disarmed, the panel still reports; nothing is sent.
    Measured twice here: autoContinueAtUsageLimit does NOT resume after the
    5-hour session limit, and /loop dies on its first refused wakeup.

    [bold]space[/] excludes ONE session (the [{GREEN}]checkmark[/] becomes a dot). The choice
    lives in the watchdog's own file, so it holds whether or not this dashboard
    is open, and survives a restart. Everything is included by default, so a
    session started tomorrow is covered without being opted in.
"""

HELP_FILES = f"""
  [{DIM}]All of it is read from files claude-watchdog.sh publishes: no API calls,
  no tokens, and no tmux captures from this process.[/]
"""

HELP_CLOSED = f"""
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
"""

HELP_LANESTATE = f"""
  [{DIM}]LANE STATE[/]
    [{GREEN}]fresh[/]    under 6h
    [{YELLOW}]ageing[/]   6-24h
    [{RED}]stale[/]    over 24h. A vite server was measured at 2487 MB after three
             days against 1142 MB fresh, and a long-lived server is also what
             serves dual module instances.
"""

HELP_RAM = f"""
  [{DIM}]RAM is summed per PROCESS GROUP: `npm run dev` and the vite it spawns are
  separate processes, the port belongs to vite, and npm holds ~70 MB of its own.[/]
"""

def register(app) -> None:
    view = MainView(app)
    app.add_view(view)
    app.add_menu("session", view.session_menu_entries,
                 title_fn=view._session_menu_title)
    app.add_help("THE WINDOW TREE", HELP_TREE, order=10)
    app.add_help("LANES AND ACCOUNTS", HELP_LANES, order=11)
    app.add_help("THE MENU (space)", HELP_MENU, order=12)
    app.add_help("A SMALL TERMINAL", HELP_SMALL, order=13)
    app.add_help("SESSION MONITORING", HELP_MONITORING, order=40)
    app.add_help("UNCOMMITTED", HELP_UNCOMMITTED, order=41)
    app.add_help("", HELP_BACKGROUND, order=60)
    app.add_help("USAGE LIMITS (top right)", HELP_USAGE, order=61)
    app.add_help("CLAUDE", HELP_CLAUDE, order=62)
    app.add_help("UNCOMMITTED WORK", HELP_DIRTY, order=63)
    app.add_help("", HELP_FILES, order=64)
    app.add_help("CLOSED WINDOWS LEAVE ON THE NEXT REDRAW", HELP_CLOSED, order=65)
    app.add_help("LANE STATE", HELP_LANESTATE, order=66)
    app.add_help("", HELP_RAM, order=67)
