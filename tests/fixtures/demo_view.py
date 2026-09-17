"""A whole dashboard feature in ONE FILE, which is the thing being proved.

Copied into `dashboard/views/` by tests/sandbox/onefile.sh, which then checks
that it appears -- and that `git status` shows no other file modified. Every
registry the seam offers is used exactly once here, so if any of them stops
working this file stops appearing and says which.

It is a fixture, not a feature: it displays nothing you would want. Read it
as the shortest possible answer to "what does a new view have to provide",
and docs/dashboard-views.md as the long one.
"""
from __future__ import annotations

from rich import box
from rich.panel import Panel
from rich.text import Text

import muxsettings
from dashboard.app import View
from dashboard.core import DIM, FRAME, YELLOW

HELP_DEMO = """
  [%s]THE DEMO TAB[/]
    A fixture dropped into dashboard/views/ by tests/sandbox/onefile.sh. If
    you are reading this on a real dashboard, something copied a test file
    into your checkout.
""" % DIM


class DemoView(View):
    # A TAB, not a screen: it shares the schedule view's group, so the shell
    # draws the strip in the panel title and ←→ cycles between them. `key` is
    # None because a tab is reached through its group, not by a key of its own.
    name, key, group, order = "demo", None, "s", 30

    def __init__(self, app) -> None:
        self.app = app
        self.pressed = 0

    def tab_label(self, app) -> str:
        return "demo %d" % self.pressed

    def build(self, app) -> list:
        body = Text.assemble(
            ("the demo view is a tab of s\n", "bold"),
            ("x pressed %d time(s)\n" % self.pressed, YELLOW),
            ("←→ cycles the tabs · esc goes back", DIM))
        return [("demo", Panel(body, title="[bold]demo",
                               title_align="left", border_style=FRAME,
                               box=box.ROUNDED))]

    def footer(self, app):
        return Text(" x count  ←→ tab  esc back  q quit", style=DIM)

    def on_key(self, app, key) -> bool:
        if key == "x":
            self.pressed += 1
            app.say("demo: %d" % self.pressed)
            return True
        if key == "\x1b":
            app.switch_to("main")
            return True
        return False


def register(app) -> None:
    view = DemoView(app)
    app.add_view(view)                                          # 1. a view
    # 2. a menu of its own, reachable from the row it adds to the esc menu
    app.add_menu("demo", lambda: [{"label": "a demo menu row",
                                   "act": lambda: "the demo menu fired"}],
                 title_fn=lambda: "demo menu", esc_to="mux")
    # 3. a row in SOMEBODY ELSE's menu, at an order that puts it under
    #    Settings rather than at the bottom
    app.add_rows("mux", lambda a: [{"label": "Demo ▸  a row this file added",
                                    "sub": "demo"}], order=15)
    # 4. a mark on every session row, and a note in the main footer
    app.add_badge(lambda a, session: Text("◆", style=YELLOW))
    app.add_hint(lambda a: Text(" · demo loaded", style=YELLOW))
    # 5. a section of `?`
    app.add_help("THE DEMO TAB", HELP_DEMO, order=70)
    # 6. how a watchdog state this module knows about is drawn
    app.add_state("demoing", "demoing", YELLOW)
    # ...and a setting of its own. WATCHDOG_STRANDED is borrowed because it is
    # already in muxconfig.KEYS and is not one of the core eight: a REAL new
    # setting is three lines in that list and in profile.sh first, which is
    # what muxsettings.register refuses to let a module skip.
    muxsettings.register({"WATCHDOG_STRANDED": {
        "label": "Demo: stranded after (minutes)", "kind": "text",
        "hint": "registered by tests/fixtures/demo_view.py"}})
