"""Seven more tabs for `s`, so the strip has nine and must scroll.

Copied into `dashboard/views/` of a COPY of the checkout by
tests/sandbox/prove.sh -- a fixture, not a feature. Each tab says its own
name in its body ("this is tab <name>") and in its footer, which is how
prove.sh knows which tab ←→ landed on without trusting the strip it is
testing.
"""
from __future__ import annotations

from rich import box
from rich.panel import Panel
from rich.text import Text

from dashboard.app import View
from dashboard.core import DIM, FRAME

NAMES = ["deployments", "alerts", "pages", "backups", "certificates",
         "queues", "workers"]


class ExtraTab(View):
    key = None
    group = "s"

    def __init__(self, name: str, order: int) -> None:
        self.name, self.order = name, order

    def tab_label(self, app) -> str:
        return "%s %d" % (self.name, self.order)

    def tab_short(self, app) -> str:
        return self.name[:4]

    def tab_initial(self, app) -> str:
        return self.name[:1]

    def build(self, app) -> list:
        return [(self.name, Panel(Text("this is tab %s" % self.name, style="bold"),
                                  border_style=FRAME, box=box.ROUNDED))]

    def footer(self, app):
        return Text(" ←→ tab  s/esc back  q quit  · tab %s" % self.name, style=DIM)

    def on_key(self, app, key) -> bool:
        if key in ("\x1b", "s"):
            app.switch_to("main")
            return True
        return False


def register(app) -> None:
    for i, name in enumerate(NAMES):
        app.add_view(ExtraTab(name, 50 + i))
