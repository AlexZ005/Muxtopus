"""dashboard.menus.mux -- the dashboard's OWN menu, and its Settings submenu.

esc opens what is not about one row: Settings, the watchdog and monitor
switches by their full names (w and m stay the fast path), Disconnect, Reload
and Quit. Settings is a submenu registered with `esc_to="mux"`, which is how
esc knows to go back rather than close -- a property of the menu now, and not
a name the main loop knows.

A module that wants a row in either of these -- `ESC ▸ Insights`,
`Settings ▸ Notifications ▸` -- registers it with app.add_rows and never
opens this file. That is the whole reason this file is short.
"""
from __future__ import annotations

import os
import subprocess
import time

from rich.markup import escape

import muxsettings
from dashboard.core import (DIM, HOME, PROFILE, SCRIPTS, WATCHDOG_DIR,
                            WATCHDOG_ENABLED, model_choices)
from dashboard.data import (frozen_snapshot, monitor_on, toggle_monitor,
                            toggle_watchdog)


class MuxMenu:
    """The esc menu and Settings. Not a View: it draws no screen of its own,
    it fills two menu kinds."""

    def __init__(self, app) -> None:
        self.app = app

    def mux_menu_entries(self) -> list[dict]:
        """The dashboard's own menu (esc): what is not about one row. The two
        global switches are here by their full names because a menu is where
        a hand looks for them; w and m stay as the fast path."""
        wd = WATCHDOG_ENABLED.exists()
        mon = monitor_on()
        # THE EXPLANATIONS ARE `desc`, not glued to the label. A row says what
        # it is; the sentence under the cursor says what it does. The one the
        # `Settings ▸` row used to carry is now the settings menu's own
        # header, where it is read when it is about to be true.
        items: list[dict] = [
            {"label": "Settings ▸", "sub": "settings"},
            {"sep": True},
            {"label": "Watchdog: %s" % ("ON" if wd else "off"),
             "desc": "restart a limited window once its limit resets",
             "on": wd, "act": toggle_watchdog, "stay": True},
            {"label": "Monitor: %s" % ("ON" if mon else "off"),
             "desc": "ask a working window to wind down near the limit",
             "on": mon, "act": toggle_monitor, "stay": True},
        ]
        # THE WINDOWS A LOST SERVER TOOK (docs/restore.md): a row only while
        # the watchdog holds a frozen snapshot, so the menu is what it always
        # was on a machine where nothing was lost.
        snap = frozen_snapshot()
        if snap is not None:
            _, k, seen = snap
            when = time.strftime("%m-%d %H:%M", time.localtime(seen)) if seen else "?"
            items.append({"label": "Restore %d windows from %s" % (k, when),
                          "desc": "rebuild what the lost tmux server took, "
                                  "each resuming its session",
                          "act": lambda k=k, when=when: self.act_restore(k, when)})
        items += [
            {"sep": True},
            {"label": "Disconnect",
             "desc": "detach this tmux client; the dashboard and every window "
                     "keep running",
             "act": self.act_disconnect},
            {"label": "Reload the dashboard", "desc": "re-exec this script, as R does",
             "act": self.act_reload},
            {"label": "Quit the dashboard", "act": self.act_quit, "danger": True},
        ]
        if not os.environ.get("TMUX"):
            for it in items:
                if it.get("act") is self.act_disconnect:
                    it["disabled"] = "not inside tmux"
        return items

    def act_restore(self, k: int, when: str) -> str:
        """A confirm, then the watchdog's own restore, detached: it opens K
        windows and waits on each claude for up to thirty seconds, which is
        not something to do inside a frame."""
        self.app.confirm = {"label": "Restore %d windows from %s into this session?" % (k, when),
                            "fn": self._do_restore}
        return ""

    def _do_restore(self) -> str:
        cmd = [str(SCRIPTS / "claude-watchdog.sh")]
        if PROFILE:
            cmd += ["--profile", PROFILE]
        cmd += ["--restore"]
        try:
            log = open(WATCHDOG_DIR / "restore.out", "ab")
            subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            return "restore failed to start: %s" % exc
        return "restoring in the background -- the windows appear as each claude comes up; the log says which resumed"

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
        self.app.pending_reload = True
        return ""

    def act_quit(self) -> str:
        self.app.pending_quit = True
        return ""

    def settings_menu_entries(self) -> list[dict]:
        """One row per setting, label and current value. Every row stays open
        after a change so several can be set in one visit; the notice says
        what was written and to which file."""
        items: list[dict] = []
        for key, meta in muxsettings.DASHBOARD_KEYS.items():
            val = muxsettings.get(key, PROFILE)
            if meta["kind"] == "onoff":
                items.append({"label": "%s: %s" % (meta["label"], "ON" if val == "on" else "off"),
                              "desc": meta["hint"],
                              "on": val == "on", "act": lambda k=key: self._setting_edit(k),
                              "stay": True})
                continue
            if key == "DASHBOARD_NEW_CWD":
                shown = val or "(the selected session's cwd)"
            else:
                shown = val or "(account default)"
            items.append({"label": "%s: %s" % (meta["label"], shown),
                          "desc": meta["hint"],
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
                else [""] + model_choices()
            shown = [c or "(account default)" for c in choices]
            i = choices.index(cur) if cur in choices else 0
            self.app.picker = {"title": meta["label"], "i": i, "options": shown,
                           "fn": lambda c, k=key: self._setting_put(
                               k, "" if c == "(account default)" else c)}
            return ""
        self.app.prompt = {"title": meta["label"], "buf": cur, "keep_menu": True,
                       "fn": lambda s, k=key: self._setting_put(k, s.strip())}
        return ""

    def _setting_put(self, key: str, value: str) -> str:
        label = muxsettings.DASHBOARD_KEYS[key]["label"]
        err = muxsettings.put(key, value, PROFILE)
        if err:
            return "%s: %s" % (label, err)
        return "%s = %s  · %s" % (label, value or "(account default)",
                                  muxsettings.dashboard_conf_path(PROFILE).name)

    def _settings_menu_desc(self) -> str:
        """What the `Settings ▸` row used to carry glued onto its label. Here
        it is read once the menu it describes is open, and the row above is
        short enough for the panel to be worth capping."""
        return "menu layout, defaults for a new window, where a mode is made permanent"

    def _settings_menu_title(self) -> str:
        return "settings[/] [%s]· %s" % (
            DIM, escape(str(muxsettings.dashboard_conf_path(PROFILE)).replace(str(HOME), "~")))



# ------------------------------------------------------------------ help
# This module's slice of `?`. Registered with the ORDER it has always had,
# so the help screen reads exactly as it did when it was one string in
# deck_status.py -- the split moved who owns the words, not the words.
HELP_MUX = f"""
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

    RESTORE appears in the menu only while the watchdog holds a frozen window
    snapshot -- the windows a dead tmux server took, saved every pass and kept
    when the session vanished. It rebuilds them into this session in their
    order, names and folders, each running `claude --resume` on the session it
    had, and puts every lane back in the tree. `muxtopus` offers the same at
    start; docs/restore.md has the rest.
"""

def register(app) -> None:
    menu = MuxMenu(app)
    app.add_menu("mux", menu.mux_menu_entries, title_fn=lambda: "muxtopus")
    app.add_menu("settings", menu.settings_menu_entries,
                 title_fn=menu._settings_menu_title,
                 desc_fn=menu._settings_menu_desc,
                 hint_fn=lambda: "↑↓ pick · enter change · esc back",
                 esc_to="mux")
    app.add_help("THE MUXTOPUS MENU (esc) AND SETTINGS", HELP_MUX, order=30)
