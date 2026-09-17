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

from rich.markup import escape

import muxsettings
from dashboard.core import (DIM, HOME, PROFILE, WATCHDOG_ENABLED,
                            model_choices)
from dashboard.data import monitor_on, toggle_monitor, toggle_watchdog


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
        items: list[dict] = [
            {"label": "Settings ▸  menu layout, defaults for a new window, where a mode is made permanent",
             "sub": "settings"},
            {"sep": True},
            {"label": "Watchdog: %s  restart a limited window once its limit resets"
                      % ("ON" if wd else "off"),
             "on": wd, "act": toggle_watchdog, "stay": True},
            {"label": "Monitor: %s  ask a working window to wind down near the limit"
                      % ("ON" if mon else "off"),
             "on": mon, "act": toggle_monitor, "stay": True},
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

    def _settings_menu_title(self) -> str:
        return "settings[/] [%s]· %s" % (
            DIM, escape(str(muxsettings.dashboard_conf_path(PROFILE)).replace(str(HOME), "~")))


def register(app) -> None:
    menu = MuxMenu(app)
    app.add_menu("mux", menu.mux_menu_entries, title_fn=lambda: "muxtopus")
    app.add_menu("settings", menu.settings_menu_entries,
                 title_fn=menu._settings_menu_title,
                 hint_fn=lambda: "↑↓ pick · enter change · esc back",
                 esc_to="mux")
