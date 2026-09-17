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

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# THE SETTINGS THE DASHBOARD OWNS AND WRITES (dashboard.conf), and the one
# settings.json edit it is allowed to make. muxconfig reads; this writes.
import muxsettings
# THE APP: what every screen shares -- the notice, the console, the submodes,
# the menu engine -- and the six registries a module puts itself into. The
# menu DRAWING it uses lives one further down, in dashboard.menulayout, which
# is pure and proven on its own (tests/test_menulayout.py).
from dashboard.app import App, View

# THE DASHBOARD PROPER now lives in a package beside this file; what is left
# here is the shell. The six names this file does not use itself are
# RE-EXPORTS and must not be pruned: tests/test_entry_options.py does
# `import deck_status as d` and calls d.read_options, d.options_line,
# d.options_section, d.options_fields, d.parse_options_line and
# d.rewrite_options, and that test passing UNCHANGED is one of the proofs
# that the split changed no behaviour.
from dashboard.core import (CONFIG_DIR, CONTEXT_WINDOW, DIM, EXTRAS_SENTINEL,
    EXTRA_HINTS, FRAME, FRAME_INTERVAL, GREEN, HANDOVERS_DIR, HOME,
    LANES_EMPTY, LANE_PREFIX, MULTI_ACCOUNT, PROFILE, PROFILE_LABEL, RED,
    SCHEDULES_DIR, SCRIPTS, SERVER_HINTS, STALE_AFTER, USAGE_MAX_AGE,
    WATCHDOG_DIR, WATCHDOG_DIRECTIVES, WATCHDOG_ENABLED, WATCHDOG_MONITOR,
    WATCHDOG_MON_OPTOUT, WATCHDOG_MSG, WATCHDOG_OPTOUT, WATCHDOG_TREE,
    WD_INTERVAL, YELLOW, gauge, human_age, human_mb, human_tokens, knob,
    mux_home, options_paths, pressure, read, read_options, sparkline, when)
from dashboard.schedules import (options_fields, options_line, options_section,
    parse_options_line, read_schedules, rewrite_options, sanitise_slug)
from dashboard.data import (Cpu, claude_sessions, dirty_for, dirty_repos,
    drop_dead, first_glob, heartbeat_age, hooray, hottest_c, lane_account,
    lane_name, lane_slug_of, listening_inodes, meminfo, monitor_on,
    monitor_opted_out, opted_out, ports_for, processes, read_tree,
    refresh_usage, session_mode, uptime_seconds, usage_failure, usage_limits)


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



# --------------------------------------------------------------------------
# frame
# --------------------------------------------------------------------------
class Dashboard(App):
    """Every view, still as methods on one object -- reached through the
    adapters at the foot of this file.

    Phase 2 of the split lifted what the views SHARE into App: the notice,
    the console, the submodes, the menu engine and the six registries. What
    is left here is the views themselves, and phases 3 and 4 carry them out
    a screen at a time. Each of them then keeps its own state, and this class
    stops existing.
    """

    def __init__(self, interval: float, console: Console | None = None) -> None:
        super().__init__(interval, console)
        self.cpu = Cpu()
        # ------------------------------------------- the main view's state
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
        # What the view's build() worked out and its footer and menu anchor
        # then need. Stashed rather than recomputed: they are decided halfway
        # down a frame that costs 12.9 ms, and App asks for them in the order
        # build() produces them.
        self._main_foot = None
        self._main_anchor = 2


        # ------------------------------------------------ THE REGISTRATIONS
        # Space opens a menu rather than toggling one setting, because the
        # useful actions outgrew the keyboard. Four kinds today, each one a
        # function that rebuilds its rows every frame; nothing dispatches on
        # the kind any more.
        self.add_menu("session", self.session_menu_entries,
                      title_fn=self._session_menu_title)
        self.add_menu("mux", self.mux_menu_entries,
                      title_fn=lambda: "muxtopus")
        # The one menu that goes BACK rather than closing, and now it says so
        # in its registration instead of in the main loop's key chain.
        self.add_menu("settings", self.settings_menu_entries,
                      title_fn=self._settings_menu_title,
                      hint_fn=lambda: "↑↓ pick · enter change · esc back",
                      esc_to="mux")
        self.add_view(MainView(self))
        # THE FIRST MODULE THAT IS ONE. Phase 5 finds it with pkgutil instead
        # of naming it here; until then the import is the only line in this
        # file that knows the schedule view exists at all.
        from dashboard.views import schedules as _schedules
        _schedules.register(self)

    # ----------------------------------------------- the menus' own titles
    # Names are escaped: a window called [x] would otherwise be read as a
    # style by Rich's markup.
    def _session_menu_title(self) -> str:
        win = self.windows.get(self.cursor, "")
        if win:
            return "menu[/] [%s]· %s" % (DIM, escape(win))
        return "menu"
    def _settings_menu_title(self) -> str:
        return "settings[/] [%s]· %s" % (
            DIM, escape(str(muxsettings.dashboard_conf_path(PROFILE)).replace(str(HOME), "~")))

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

    def mux_menu_entries(self) -> list[dict]:
        """The dashboard's own menu (esc): what is not about one row. The two
        global switches are here by their full names because a menu is where
        a hand looks for them; w and m stay as the fast path."""
        wd = WATCHDOG_ENABLED.exists()
        mon = monitor_on()
        items: list[dict] = [
            {"label": "Settings ▸  menu layout, defaults for a new window, where a mode is made permanent",
             "sub": "settings"},
            {"sep": True},
            {"label": "Watchdog: %s  restart a limited window once its limit resets"
                      % ("ON" if wd else "off"),
             "on": wd, "act": toggle_watchdog, "stay": True},
            {"label": "Monitor: %s  ask a working window to wind down near the limit"
                      % ("ON" if mon else "off"),
             "on": mon, "act": self.act_monitor, "stay": True},
            {"sep": True},
            {"label": "Disconnect  detach this tmux client; the dashboard and every window keep running",
             "act": self.act_disconnect},
            {"label": "Reload the dashboard  re-exec this script, as R does",
             "act": self.act_reload},
            {"label": "Quit the dashboard", "act": self.act_quit, "danger": True},
        ]
        if not os.environ.get("TMUX"):
            items[5]["disabled"] = "not inside tmux"
        return items

    def act_disconnect(self) -> str:
        """`tmux detach-client` with no target: inside a pane TMUX names the
        server and tmux resolves the current client from it. Every window,
        this one included, keeps running; `muxtopus` attaches again."""
        try:
            r = subprocess.run(["tmux", "detach-client"], capture_output=True,
                               text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "detach failed: %s" % exc
        return "" if r.returncode == 0 else "detach failed: %s" % r.stderr.strip()

    def act_reload(self) -> str:
        self.pending_reload = True
        return ""

    def act_quit(self) -> str:
        self.pending_quit = True
        return ""

    # ------------------------------------------------------------ settings
    def model_choices(self) -> list[str]:
        """The CLI aliases options.md's `model` block offers -- the same list
        the options table uses, because `--model opus-5` (the MODEL column's
        spelling) is refused by the CLI and kills the window after it has
        eaten the paste. The literal list is the fallback for a missing or
        broken block."""
        for o in read_options(PROFILE):
            if o["key"] == "model" and not o["bad"] and o["choices"]:
                return list(o["choices"])
        return ["opus", "opus[1m]", "fable", "sonnet", "haiku"]

    def settings_menu_entries(self) -> list[dict]:
        """One row per setting, label and current value. Every row stays open
        after a change so several can be set in one visit; the notice says
        what was written and to which file."""
        items: list[dict] = []
        for key, meta in muxsettings.DASHBOARD_KEYS.items():
            val = muxsettings.get(key, PROFILE)
            if meta["kind"] == "onoff":
                items.append({"label": "%s: %s  %s" % (meta["label"], "ON" if val == "on" else "off",
                                                        meta["hint"]),
                              "on": val == "on", "act": lambda k=key: self._setting_edit(k),
                              "stay": True})
                continue
            if key == "DASHBOARD_NEW_CWD":
                shown = val or "(the selected session's cwd)"
            else:
                shown = val or "(account default)"
            items.append({"label": "%s: %s  %s" % (meta["label"], shown, meta["hint"]),
                          "act": lambda k=key: self._setting_edit(k), "stay": True})
        items.append({"sep": True})
        items.append({"label": "Back", "sub": "mux"})
        return items

    def _setting_edit(self, key: str) -> str:
        meta = muxsettings.DASHBOARD_KEYS[key]
        cur = muxsettings.get(key, PROFILE)
        if meta["kind"] == "onoff":
            return self._setting_put(key, "off" if cur == "on" else "on")
        if meta["kind"] == "choice":
            choices = list(meta["choices"]) if meta["choices"] is not None \
                else [""] + self.model_choices()
            shown = [c or "(account default)" for c in choices]
            i = choices.index(cur) if cur in choices else 0
            self.picker = {"title": meta["label"], "i": i, "options": shown,
                           "fn": lambda c, k=key: self._setting_put(
                               k, "" if c == "(account default)" else c)}
            return ""
        self.prompt = {"title": meta["label"], "buf": cur, "keep_menu": True,
                       "fn": lambda s, k=key: self._setting_put(k, s.strip())}
        return ""

    def _setting_put(self, key: str, value: str) -> str:
        label = muxsettings.DASHBOARD_KEYS[key]["label"]
        err = muxsettings.put(key, value, PROFILE)
        if err:
            return "%s: %s" % (label, err)
        return "%s = %s  · %s" % (label, value or "(account default)",
                                  muxsettings.dashboard_conf_path(PROFILE).name)

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

    # ------------------------------------------- c: a new claude session
    # Seven screens through the existing picker and prompt, then ONE file: a
    # schedule entry with at: already past. The dashboard opens no window
    # itself. The watchdog's next pass does the trust dialog, the readiness
    # wait, the bracketed paste, the tree row, the footer and the log line --
    # one launcher, whoever asked, and none of it reimplemented here.
    def start_new_session(self) -> str:
        self.ns = {}
        cands = self._ns_folder_candidates()
        self.picker = {"title": "new session · working folder", "i": 0,
                       "options": cands + ["other…  type a path"], "fn": self._ns_folder}
        return ""

    def _ns_folder_candidates(self) -> list[str]:
        """Where a session might sensibly start, most likely first: the cursor
        session's folder, the setting, every live session's folder, the dirty
        trees the watchdog publishes, and the git checkouts one and two levels
        under MUXTOPUS_HOME -- the same two levels sweep_repos walks."""
        out: list[str] = []

        def add(p: str) -> None:
            if p and p != "-" and p not in out and os.path.isdir(p):
                out.append(p)

        add(self.cwds.get(self.cursor, ""))
        add(muxsettings.get("DASHBOARD_NEW_CWD", PROFILE))
        for sid in self.sids:
            add(self.cwds.get(sid, ""))
        for path, _name, _n in dirty_repos():
            add(path)
        home = mux_home(PROFILE)
        try:
            for d in sorted(os.scandir(home), key=lambda e: e.name):
                if not d.is_dir(follow_symlinks=False) or d.name.startswith("."):
                    continue
                if os.path.exists(os.path.join(d.path, ".git")):
                    add(d.path)
                    continue
                try:
                    for dd in sorted(os.scandir(d.path), key=lambda e: e.name):
                        if dd.is_dir(follow_symlinks=False) and \
                                os.path.exists(os.path.join(dd.path, ".git")):
                            add(dd.path)
                except OSError:
                    pass
        except OSError:
            pass
        return out

    def _ns_folder(self, choice: str) -> str:
        if choice.startswith("other…"):
            self.prompt = {"title": "new session · working folder", "buf": "",
                           "fn": self._ns_folder_typed}
            return ""
        return self._ns_folder_typed(choice)

    def _ns_folder_typed(self, text: str) -> str:
        p = os.path.expanduser(text.strip())
        if not p or not os.path.isdir(p):
            # Said in the prompt's own title: the notice is not drawn while a
            # prompt owns the footer.
            self.prompt = {"title": "not a directory: %s — working folder" % (text.strip() or "(empty)"),
                           "buf": text.strip(), "fn": self._ns_folder_typed}
            return ""
        self.ns["cwd"] = os.path.abspath(p)
        return self._ns_ask_model()

    def _ns_ask_model(self) -> str:
        choices = [""] + self.model_choices()
        cur = muxsettings.get("DASHBOARD_NEW_MODEL", PROFILE)
        self.picker = {"title": "new session · model  (CLI aliases — the MODEL column's names are refused)",
                       "i": choices.index(cur) if cur in choices else 0,
                       "options": [c or "(account default)" for c in choices],
                       "fn": self._ns_model}
        return ""

    def _ns_model(self, c: str) -> str:
        self.ns["model"] = "" if c == "(account default)" else c
        choices = [""] + list(muxsettings.EFFORTS)
        cur = muxsettings.get("DASHBOARD_NEW_EFFORT", PROFILE)
        self.picker = {"title": "new session · effort",
                       "i": choices.index(cur) if cur in choices else 0,
                       "options": [c or "(account default)" for c in choices],
                       "fn": self._ns_effort}
        return ""

    def _ns_effort(self, c: str) -> str:
        self.ns["effort"] = "" if c == "(account default)" else c
        modes = list(muxsettings.PERM_MODES)
        cur = muxsettings.get("DASHBOARD_NEW_PERMISSION_MODE", PROFILE)
        pk = {"title": "new session · permission mode", "options": modes, "fn": self._ns_mode,
              "i": modes.index(cur) if cur in modes else -1}
        if pk["i"] < 0:
            # "always ask": nothing preselected. A DEFAULT is set in Settings;
            # it is never a lock, this screen is always shown.
            pk["title"] += "  (no default set — esc → Settings sets one)"
        self.picker = pk
        return ""

    def _ns_mode(self, c: str) -> str:
        self.ns["mode"] = c
        if c == "bypassPermissions":
            self.picker = {"title": "bypassPermissions", "i": 0,
                           "options": ["this window only",
                                       "…and make it the default  (writes settings.json)"],
                           "fn": self._ns_bypass}
            return ""
        return self._ns_ask_where()

    def _ns_bypass(self, c: str) -> str:
        if c.startswith("this window"):
            return self._ns_ask_where()
        scope = muxsettings.get("DASHBOARD_PERMANENT_MODE_SCOPE", PROFILE) or "project"
        path = muxsettings.settings_json_path(scope, self.ns["cwd"], CONFIG_DIR)
        self.confirm = {
            "label": ('⚠ writes  "permissions": {"defaultMode": "bypassPermissions"}  to %s\n'
                      '  EVERY future Claude session there skips permission prompts,\n'
                      '  including ones nothing is watching.  (%s — Settings changes where)'
                      % (path, scope)),
            "fn": lambda p=path: self._ns_bypass_write(p),
            "no_fn": self._ns_ask_where}
        return ""

    def _ns_bypass_write(self, path) -> str:
        # THE ONE WRITE lives in muxsettings; this is an entrance to it.
        msg, err = muxsettings.set_default_mode(path, "bypassPermissions")
        self.ns["default_msg"] = err or msg
        self.ns["default_err"] = bool(err)
        return self._ns_ask_where()

    def _ns_ask_where(self) -> str:
        opts = ["a top-level window"]
        for sid in self.sids:
            win = self.windows.get(sid, "")
            if win and self.panes.get(sid):
                opts.append("under %s" % win)
        title = "new session · where"
        if self.ns.get("default_msg"):
            # The outcome of the settings.json write, where it can be seen:
            # no notice is drawn while a picker owns the footer.
            title += "  · settings.json %s: %s" % (
                "NOT written" if self.ns.get("default_err") else "written",
                self.ns["default_msg"])
        self.picker = {"title": title, "i": 0, "options": opts, "fn": self._ns_where}
        return ""

    def _ns_where(self, c: str) -> str:
        if c.startswith("under "):
            win = c[len("under "):]
            # window: is the tmux name (the launcher strips ➥ to find it);
            # parent: is the slug, which is what the tree is keyed on.
            self.ns["window"] = win
            self.ns["parent"] = lane_slug_of(win)
        base = sanitise_slug(os.path.basename(self.ns["cwd"].rstrip("/")))
        self.prompt = {"title": "new session · name  (the slug: window ➥name, STATUS-name.md, handover.sh done name)",
                       "buf": base, "fn": self._ns_name}
        return ""

    def _ns_name(self, text: str) -> str:
        slug = sanitise_slug(text.strip())
        why = ""
        if not slug:
            why = "empty"
        else:
            taken = {r["resolved"] for r in read_schedules()
                     if r["status"] in ("pending", "launched")}
            live = {lane_slug_of(w) for w in self.windows.values() if w}
            if slug in taken or slug in live:
                why = "%s is taken (a window or an entry has it)" % slug
        if why:
            self.prompt = {"title": "%s — new session · name" % why, "buf": text.strip(),
                           "fn": self._ns_name}
            return ""
        self.ns["title"] = text.strip()
        self.ns["slug"] = slug
        self.prompt = {"title": "new session · first prompt  (may be empty)", "buf": "",
                       "fn": self._ns_prompt}
        return ""

    def _ns_prompt(self, text: str) -> str:
        self.ns["prompt"] = text.strip()
        return self._ns_write()

    def _ns_write(self) -> str:
        """The one file. `at:` is now to the minute, so it is already past
        and the watchdog's next pass launches it; `slug:` is pinned so the
        window is named what was typed. An empty prompt makes it a `plan`
        entry with no template -- the executor refuses an empty work body,
        and a plan may be empty: the session receives its identity line and
        nothing invented (QUESTIONS 2a)."""
        ns, self.ns = self.ns, None
        slug = ns["slug"]
        now = time.strftime("%Y-%m-%d %H:%M")
        head = ["type: " + ("work" if ns["prompt"] else "plan"),
                "at: " + now, "title: " + ns["title"], "slug: " + slug]
        if ns.get("window"):
            head += ["window: " + ns["window"], "parent: " + ns["parent"]]
        head.append("cwd: " + ns["cwd"])
        for k in ("model", "effort"):
            if ns.get(k):
                head.append("%s: %s" % (k, ns[k]))
        head.append("permission-mode: " + ns["mode"])
        # The two headers the LAUNCHER applies after readiness, because a
        # session id does not exist before launch (it maps its pane to
        # sessions/<pid>.json). Absent means covered, today's default.
        if muxsettings.get("DASHBOARD_NEW_WATCHDOG", PROFILE) == "off":
            head.append("watchdog: off")
        if muxsettings.get("DASHBOARD_NEW_MONITOR", PROFILE) == "off":
            head.append("monitor: off")
        head += ["status: pending", "created: " + now, "launched:"]
        try:
            SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
            f = SCHEDULES_DIR / ("new-%s.md" % slug)
            if f.exists():
                f = SCHEDULES_DIR / ("new-%s-%s.md" % (slug, time.strftime("%H%M%S")))
            f.write_text("\n".join(head) + "\n---\n"
                         + (ns["prompt"] + "\n" if ns["prompt"] else ""))
        except OSError as exc:
            return "could not write the entry: %s" % exc
        msg = "scheduled ➥%s — the watchdog opens it within ~30s (%s)" % (slug, f.name)
        if ns.get("default_msg"):
            msg += " · settings.json %s" % ns["default_msg"]
        return msg

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
        ct = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                   header_style=DIM, border_style=FRAME)
        ct.add_column("", width=3)
        ct.add_column("MON", width=4)
        # no_wrap or a long background-job name wraps and breaks the row;
        # ellipsis only applies to text that is not allowed to wrap.
        ct.add_column("WINDOW", overflow="ellipsis", no_wrap=True, ratio=1)
        ct.add_column("MODEL", width=11, overflow="ellipsis", no_wrap=True)
        ct.add_column("CONTEXT", width=29)
        ct.add_column("SPENT", justify="right", width=8)
        ct.add_column("IDLE", justify="right", width=6)
        ct.add_column("STATE", width=15, overflow="ellipsis", no_wrap=True)
        ct.add_column("DIRTY", justify="right", width=6)
        # 12, NOT 11, AND no_wrap. when() renders a stamp older than today as
        # "%b %-d %H:%M" -- "Sep 5 21:13" is 11 and fitted, "Sep 12 12:21" is 12
        # and did not, so every row wound or resumed on a two-digit day wrapped
        # onto a second line and tore the table in half. A width that depends on
        # the day of the month is a width that is wrong two thirds of the time;
        # no_wrap is the belt to that braces, because a cell that cannot wrap
        # can never take a row with it.
        ct.add_column("WOUND", width=12, overflow="ellipsis", no_wrap=True)
        ct.add_column("RESUMED", width=12, overflow="ellipsis", no_wrap=True)

        skipped = opted_out()
        mskipped = monitor_opted_out()
        for s, depth, hidden in layout:
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
            elif s.state == "stranded":
                # THE NEW "nothing is ever going to touch this". idle stays
                # dim because it is a fact about the last turn and usually
                # means finished; stranded is a fact about the FUTURE -- an
                # open handover, past the threshold, and no pending entry
                # naming the lane -- so it is the one idle state worth a
                # colour. Eight characters against a 15-wide column: it
                # cannot wrap the row.
                st_txt = Text("stranded", style=RED)
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
            # DEPTH IS DRAWN, not stored in tmux: the window name carries its
            # own ➥ markers, and this adds the indent the flat list cannot.
            if depth:
                wtx = Text.assemble(("  " * depth + "└ ", FRAME), s.window)
            else:
                wtx = Text(s.window)
            if hidden:
                wtx.append("  +%d" % hidden, style="bold #c9a0dc")
            ct.add_row(mark, mon_txt, wtx, Text(s.model, style=DIM), bar,
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
            ("w", DIM), " watchdog  ", ("m", DIM), " monitor  ", ("u", DIM), "/", ("U", DIM), " usage  ", ("↑↓", DIM), " pick  ", ("enter", DIM), " open  ", ("space", DIM), " menu  ",
            ("esc", DIM), " muxtopus  ", ("c", DIM), " new session  ",
            ("←→", DIM), " fold  ", ("t", DIM), " tree  ",
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

        self._main_foot = keys

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

        sections = [
            ("deck", Panel(head, title="[bold]deck", subtitle=f"[{DIM}]{subtitle}",
                           subtitle_align="right", border_style=FRAME, box=box.ROUNDED)),
            ("lanes", Panel(lanes,
                            title=f"[bold]lanes[/] [{DIM}]· {len(shown)} server(s) · {human_mb(total_mb)}{lane_scope}",
                            title_align="left", border_style=FRAME, box=box.ROUNDED)),
            ("claude", Panel(ct, title=ctitle, title_align="left",
                             border_style=FRAME, box=box.ROUNDED)),
            *[("uncommitted", p) for p in panels],
            ("system", Panel(sysrow, title="[bold]system", title_align="left",
                             border_style=FRAME, box=box.ROUNDED)),
        ]
        # WHICH PANEL THE CURSOR IS IN, for an open menu to hang under: a
        # lane row, the extras row on the system line, or a session. The
        # muxtopus and settings menus follow the cursor too -- there is no
        # better anchor. Worked out here, where the sections exist, and read
        # back by MainView.menu_anchor.
        if self.cursor.startswith(LANE_PREFIX):
            self._main_anchor = 1
        elif self.cursor == EXTRAS_SENTINEL:
            self._main_anchor = len(sections) - 1
        else:
            self._main_anchor = 2
        return sections

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
        elif key in ("\r", "\n"):
            self.say(self.open_selected())
        elif key == " ":
            self.open_menu("session")
        elif key == "\x1b":
            # The dashboard's own menu: settings, the global switches,
            # disconnect, reload, quit.
            self.open_menu("mux")
        elif key == "c":
            self.say(self.start_new_session())
        elif key == "LEFT":
            self.say(self.tree_collapse())
        elif key == "RIGHT":
            self.say(self.tree_expand())
        elif key == "t":
            self.say(self.toggle_tree())
        else:
            return False
        return True
# ======================================================== the two adapters
# Phase 2 gives the App its views without moving a line of them: each of
# these is a handful of forwards to the methods above. Phases 3 and 4 turn
# them into modules that hold their own state, and this file keeps only the
# shell. Reading them is how a new view learns the shape it has to have.
class MainView(View):
    name, key, order = "main", None, 10

    def __init__(self, app) -> None:
        self.app = app

    def build(self, app):
        return app.build_main()

    def menu_anchor(self, app):
        return app._main_anchor

    def footer(self, app):
        return app._main_foot

    def on_key(self, app, key):
        return app.main_key(key)

    # ------------------------------ WHAT OTHER VIEWS MAY ASK THE MAIN VIEW
    # The complete list, and it is short on purpose: these three, and nothing
    # else, cross the line. docs/dashboard-views.md carries the same list,
    # so the coupling is a named call anybody can grep for rather than
    # `self.cursor` reached from the far side of the dashboard.
    def cursor_sid(self):
        """The session id under the row cursor. "" on a lane or extras row."""
        sid = self.app.cursor
        if not sid or sid.startswith(LANE_PREFIX) or sid == EXTRAS_SENTINEL:
            return ""
        return sid

    def cursor_window(self):
        """Its tmux window NAME, ➥ markers and all."""
        return self.app.windows.get(self.cursor_sid(), "")

    def cursor_cwd(self):
        """Its working folder, or "" when it has none to speak of."""
        return self.app.cwds.get(self.cursor_sid(), "")



SOFT = knob("WATCHDOG_SOFT_PCT", PROFILE)
HARD = knob("WATCHDOG_HARD_PCT", PROFILE)

HELP = f"""
  [bold]deck-status[/] -- lane dashboard

  [bold]q[/] quit        [bold]r[/] redraw now      [bold]R[/] reload this script
  [bold]s[/] scheduled windows      [bold]enter[/] on the extras row stops/starts them
  [bold]w[/] watchdog    [bold]m[/] monitoring      [bold]p[/] btop   [bold]?[/] this screen
  [bold]u[/] read usage limits      [bold]up/down[/] pick   [bold]space[/] menu   [bold]esc[/] muxtopus menu
  [bold]c[/] a new claude session (folder, model, effort, mode, where, name, first prompt)
  [bold]enter[/] open the selected session's window (Ctrl-b 0 comes back here)
  [bold]f[/] lanes: this account only / every account
  [bold]←/→[/] fold / unfold a subtree      [bold]t[/] tree ordering on / off

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

  [{DIM}]A NEW CLAUDE SESSION (c)[/]
    Seven screens through the picker and the prompt: the working folder (the
    cursor's, the setting, every session's, the dirty trees, the checkouts
    under MUXTOPUS_HOME, or a typed path -- it must exist); the model, as a CLI
    ALIAS (opus, fable, sonnet…; `--model opus-5` is refused by the CLI and
    kills the window after it has eaten the paste); the effort; the permission
    mode (preselected from Settings, or nothing preselected when that says
    ask -- a default, never a lock); where it goes (a top-level window, or
    under a live one: ➥➥name, inserted after that parent's subtree, drawn
    indented); the name, which is the slug (window, handover, handover.sh
    done); and an optional first prompt.
    THEN IT WRITES A SCHEDULE ENTRY with at: already past, and nothing else:
    the watchdog opens the window within one pass and does the trust dialog,
    the readiness wait, the paste and the tree row -- one launcher, whoever
    asked. The entry carries model:, effort:, permission-mode:, cwd:,
    parent:/window:, and watchdog: off / monitor: off when Settings says a
    new window is not watched or monitored (the launcher opts the session out
    once it has an id). An empty prompt writes a plan entry: the session gets
    its identity line and nothing invented.
    Choosing bypassPermissions also offers "…and make it the default": a
    confirm names the exact settings.json (project or account, per Settings)
    and what changes -- EVERY future session there skips permission prompts,
    including ones nothing is watching. The write merges permissions.defaultMode
    into the existing JSON (nested, where Claude Code reads it), backs the
    old file up beside itself, and refuses a file that is not valid JSON.

  [{DIM}]THE MUXTOPUS MENU (esc) AND SETTINGS[/]
    esc opens the dashboard's own menu -- what is not about one row: Settings,
    the watchdog and monitor switches by their full names (w and m stay the
    fast path), Disconnect (detaches this tmux client; every window keeps
    running, `muxtopus` attaches again), Reload (R) and Quit.

    Settings are written to

        {muxsettings.dashboard_conf_path(PROFILE)}

    a file the DASHBOARD owns, in the same KEY="value" shell as config -- kept
    apart from config because that one is yours and full of your comments, and
    a program that rewrites it would eventually eat them. It is read as a
    layer ABOVE config (and profiles/<name>.dashboard.conf above
    profiles/<name>.conf), so what the menu writes is what the next frame
    reads; a value is only reported as saved once it has been read back from
    disk. `muxtopus -c` shows every setting with the layer it came from.
    The settings: the menu layout (table, modal, bottom), the permission mode,
    model and effort preselected when c creates a window, whether such a window
    is watched and monitored, the working folder offered first, and which
    settings.json "make it the default" writes to.

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
    In the view: enter/e edit · c create (type, template, THE OPTIONS TABLE,
    then the editor to paste the prompt) · o reopen the options table on a
    pending entry · l launch now · d delete · r reload · s/esc back.
    space opens the ENTRY'S menu: the why sentence when it is blocked, waiting
    or stalled, then edit, options, launch now, duplicate (a pending copy
    with a different slug, opened in the editor), check (the executor's
    --check --body report, full screen), open its window when it has one,
    and delete. A corrupted entry gets its reason and only delete.

  [{DIM}]THE OPTIONS TABLE (c, and o on a pending entry)[/]
    The checkboxes between the template and the editor: the contract sentences
    you would otherwise retype into every brief, ticked once. They come from

        {options_paths(PROFILE)[0]}

    which is YOURS -- one block per option, blank-line separated, `key: value`
    like a schedule header, its own comment block at the top being the format
    spec. Edit it and the table changes; a second account overrides or adds to
    it in profiles/<name>.options.md. A block the reader cannot make sense of
    is shown greyed with the reason rather than dropped, exactly as a
    corrupted schedule entry is.

    ↑↓ picks, space or enter ticks. An option that needs a number or a time
    opens the text prompt; one with a list of choices opens the picker (that
    is how model: and effort: are set). THE ACTIONS ARE ROWS at the bottom:
    check all, uncheck all, continue (save what is ticked, then the editor;
    "save" on a reopen) and, on create only, skip (continue with nothing
    ticked). esc CANCELS, on create and on reopen alike: on create no entry
    file is written at all, on reopen the file is untouched.

    A TICK WRITES ONE OF TWO THINGS: a sentence, appended to the body under a
    `## Options` heading at the END of it, or a header field (model:, effort:)
    the launcher passes as a flag. The header also records `options:
    questions, phases, lanes=3`, and THAT is the source of truth: o reopens
    the table from it and regenerates the section, so a sentence edited by
    hand in that section is overwritten on the next save. To keep one, move it
    ABOVE the heading -- everything above it is preserved byte for byte -- or
    edit it in options.md where it came from.

    Placeholders in a sentence ({{{{SLUG}}}}, {{{{WINDOW}}}}, {{{{HANDOVER}}}},
    {{{{QUESTIONS}}}}, {{{{SCHEDULES}}}}, {{{{CWD}}}}, {{{{PARENT}}}}) are written out
    LITERALLY and resolved by the executor when the prompt is pasted, because
    the slug does not exist yet while the table is open. {{{{VALUE}}}} is the
    exception -- it is what the prompt collected, and it is resolved here.

    WHY AN ENTRY HAS NOT FIRED is printed under the table for the row under the
    cursor, in the executor's own words -- `at: reset` is two gates (the budget
    reading fresh, or the five-hour window rolling over) and the line says which
    one it is waiting on. A row marked [{RED}]stalled[/] cannot be judged at all and
    will not resolve on its own. To resolve an entry in full without launching
    anything -- slug, window name, handover path, insert target, the exact
    paste, and the due verdict with its reason:

        claude-watchdog.sh --check <name> [--body] Plan sessions write their forks into core/plans/QUESTIONS-*.md
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
                return {0x41: "UP", 0x42: "DOWN",
                        0x43: "RIGHT", 0x44: "LEFT"}.get(b, "\x1b")
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
    dash = Dashboard(interval, console)

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

                if dash.pending_quit:
                    break
                if dash.pending_reload:
                    # A running process holds the copy it started with; re-exec
                    # so an edited script takes effect without respawning tmux.
                    # Also nudge the limits, but through --ensure: a reload is
                    # not a reason to start a probe if the figures are minutes
                    # old, and R gets pressed a lot while editing.
                    refresh_usage()
                    live.stop()
                    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                    os.execv(sys.executable, [sys.executable, __file__] + args)

                # A --check report takes the terminal over the way the
                # editor does: through less when there is one (the report is
                # longer than a screen, and the top is the useful half),
                # printed plainly otherwise.
                if dash.pending_report is not None:
                    text, dash.pending_report = dash.pending_report, None
                    live.stop()
                    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                    if os.path.exists("/usr/bin/less"):
                        subprocess.run(["/usr/bin/less", "-R"], input=text, text=True)
                    else:
                        console.clear()
                        console.print(Text(text))
                        console.print(Text("press any key", style=DIM))
                        tty.setcbreak(fd)
                        read_key(120)
                    tty.setcbreak(fd)
                    live.start()
                    continue

                key = read_key(interval)

                # THE ONE ROUTING RULE, and its first three steps are the
                # App's: a submode (prompt, confirm, picker, a view's own
                # modal) owns the keyboard while it is open -- q included,
                # because typing a window name with a "q" in it must not quit
                # the dashboard -- then an open menu, then the ACTIVE VIEW.
                if dash.route_key(key):
                    continue

                # THE SHELL'S OWN, reachable from every view. q, R, ? and p
                # need this function's Live and its saved terminal state, and
                # u, U, w and m are about the account and the fleet rather
                # than about one screen. f is here because it was reachable
                # from the schedule view before the split and the split is
                # not the place to decide it should not be -- whose key it
                # really is, is a question for the next view.
                if key in ("q", "Q"):
                    break
                if key == "R":
                    dash.pending_reload = True
                    continue
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
                elif key in ("w", "W"):
                    dash.say(toggle_watchdog())
                elif key in ("m", "M"):
                    dash.say(dash.act_monitor())
                elif key == "f":
                    dash.say(dash.toggle_lanes())
                else:
                    # LAST: a key that opens a view. The schedule view's own
                    # s and esc took it back to main above, so this only ever
                    # opens one. Stopping/starting desktop extras moved onto
                    # the cursor: arrow past the sessions, enter.
                    dash.open_view_key(key)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
