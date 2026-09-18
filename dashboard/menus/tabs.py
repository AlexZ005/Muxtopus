"""dashboard.menus.tabs -- Settings ▸ Tabs: which tabs the strip shows.

One row per tab -- every view that shares a group -- toggled with enter and
written through muxsettings into dashboard.conf as DASHBOARD_TABS_HIDDEN, a
comma-separated list of view NAMES (names, not labels: a label carries a
count and changes every frame). The App reads it (App.hidden_tabs) and
leaves the hidden ones out of the strip and out of the ←→ cycle.

HIDDEN WINS OVER LOCKED. The strip keeps its first six tabs whatever the
width (dashboard/tabstrip.py) -- the first six SHOWN ones. Hiding one of them
is the user saying they do not want it, which the lock was only ever there
to serve; the next shown tab takes the place. The rows say which six are
locked, the menu's hint says the rule, and so does `?`.

A HIDDEN TAB IS NOT GONE:
  * its data keeps working -- its badges on the session rows, its note in
    the main footer, its count -- because those are registered by its module,
    not drawn by its tab;
  * a view KEY still opens it (s opens the schedules even when that tab is
    hidden, and shows it in the strip for as long as you are on it);
  * every hidden tab gets an "Open ... once" row here, which goes to it
    without unhiding it; ←→ from there walks the shown tabs.
Nothing here can make a tab unreachable, and nothing can break the cycle:
the active tab is always in the strip it is cycled through.

This file registers everything it needs -- the key, the row in Settings,
the menu, the help -- so it is one of the "a feature is one file" kind.
"""
from __future__ import annotations

import re

import muxsettings
from dashboard.app import TABS_KEY
from dashboard.core import DIM, PROFILE
from dashboard.tabstrip import LOCKED

NAME_OK = re.compile(r"^[A-Za-z0-9_.-]+$")


class TabsMenu:
    def __init__(self, app) -> None:
        self.app = app

    def tabs(self) -> list:
        """Every tab of every group, in strip order, hidden or not."""
        return [v for v in self.app.views() if getattr(v, "group", None)]

    def entries(self) -> list[dict]:
        hidden = self.app.hidden_tabs()
        items: list[dict] = []
        shown_at: dict[str, int] = {}
        for v in self.tabs():
            off = v.name in hidden
            if not off:
                shown_at[v.group] = shown_at.get(v.group, 0) + 1
            pos = shown_at.get(v.group, 0)
            if off:
                note = "hidden from the strip and from ←→"
            elif pos <= LOCKED:
                note = "locked: stays on a narrow strip (%d of %d)" % (pos, LOCKED)
            else:
                note = "scrolls on a narrow strip"
            items.append({"label": "%s  (tab of %s): %s  %s"
                                   % (v.name, v.group, "hidden" if off else "SHOWN", note),
                          "on": not off, "stay": True,
                          "act": lambda n=v.name: self.toggle(n)})
        opens = [v for v in self.tabs() if v.name in hidden]
        if opens:
            items.append({"sep": True})
            for v in opens:
                items.append({"label": "Open %s once  it stays hidden; ←→ from there "
                                       "walks the shown tabs" % v.name,
                              "act": lambda n=v.name: self.open_once(n)})
        if not items:
            items.append({"label": "no view has tabs", "disabled": "nothing to hide"})
        items.append({"sep": True})
        items.append({"label": "Back", "sub": "settings"})
        return items

    def toggle(self, name: str) -> str:
        hidden = set(self.app.hidden_tabs())
        hidden ^= {name}
        # Names of tabs whose module did not load are KEPT: a lane's broken
        # commit must not quietly unhide the user's choice for it.
        value = ",".join(sorted(hidden))
        err = muxsettings.put(TABS_KEY, value, PROFILE)
        self.app.forget_hidden()
        if err:
            return "tabs: not saved -- %s" % err
        return "%s %s  · %s" % (name, "hidden" if name in hidden else "shown",
                                 muxsettings.dashboard_conf_path(PROFILE).name)

    def open_once(self, name: str) -> str:
        self.app.menu = None
        self.app.switch_to(name)
        return ""

    def title(self) -> str:
        n = len(self.app.hidden_tabs() & {v.name for v in self.tabs()})
        return "tabs[/] [%s]· %d hidden · %s" % (DIM, n, TABS_KEY)

    def hint(self) -> str:
        return ("enter show/hide · hidden wins: the first %d SHOWN tabs are the "
                "locked ones · esc back" % LOCKED)


HELP_TABS = f"""
  [{DIM}]TABS, AND WHICH ONES ARE SHOWN (esc ▸ Settings ▸ Tabs)[/]
    A screen with tabs (s: schedules │ handovers) draws them as a strip in its
    first panel's title and ←→ walks them. On a narrow terminal the strip
    shortens its labels first -- full, then short, then an initial; the tab
    you are on keeps its name longest -- and only then scrolls: the first
    {LOCKED} tabs stay, the rest slide, "«2" and "3»" count what is off each
    side and the subtitle says "←→ tab 7/9". ←→ reaches every tab, drawn or not.

    Settings ▸ Tabs shows or hides each one (DASHBOARD_TABS_HIDDEN in
    dashboard.conf). A hidden tab leaves the strip and the ←→ cycle, and
    HIDDEN WINS OVER LOCKED: the {LOCKED} that stay on a narrow strip are the
    first {LOCKED} you have not hidden. Hiding a tab hides only the tab -- its
    marks on the session rows and its note in the footer stay, a view key
    still opens it, and the menu has an "Open ... once" row for each one.
"""


def validate_names(value: str) -> str:
    bad = [x for x in value.split(",") if x and not NAME_OK.match(x)]
    return "not a tab name: %s" % ", ".join(bad) if bad else ""


def _register_key() -> None:
    muxsettings.register({
        TABS_KEY: {"label": "Hidden tabs", "kind": "text", "check": validate_names,
                   "hint": "view names, comma-separated (Settings ▸ Tabs)"},
    }, menu="tabs")


def register(app) -> None:
    # Once per process: the settings store is module-level, and a second
    # App in one process (the tests build several) must not trip over it.
    if muxsettings.spec_of(TABS_KEY) is None:
        _register_key()
    menu = TabsMenu(app)
    app.add_menu("tabs", menu.entries, title_fn=menu.title, hint_fn=menu.hint,
                 esc_to="settings")
    app.add_rows("settings", lambda a: [{
        "label": "Tabs ▸  which tabs the strip shows (%d hidden)"
                 % len(a.hidden_tabs() & {v.name for v in menu.tabs()}),
        "sub": "tabs",
        # Under the last setting, beside Notifications ▸ (which takes +5):
        # counted when drawn, as that row's is, and after it on the label.
        "order": len(muxsettings.DASHBOARD_KEYS) * 10 + 5}])
    app.add_help("TABS", HELP_TABS, order=31)
