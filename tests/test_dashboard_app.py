#!/usr/bin/env python3
"""dashboard.app -- the seam itself: routing, registration, ordering, failure.

Run it:  .venv/bin/python tests/test_dashboard_app.py   (no pytest; needs rich)

THE GOLDENS PROVE THE PICTURE; this proves the promises the picture cannot
show. Three lanes are about to register views, menus, rows, badges and states
into this object at the same time, and what they need to be able to rely on
is not "it looked right on my machine" but:

  * a submode owns the keyboard, q included;
  * two views cannot quietly claim one key;
  * two modules adding rows to one menu get the same menu whichever of them
    Python happened to import first;
  * one module's broken badge cannot take the screen down, or spend the
    frame budget telling you so sixty times a minute.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from rich.console import Console          # noqa: E402
from rich.text import Text                # noqa: E402

from dashboard import core                # noqa: E402
from dashboard.app import App, RegistrationError, View   # noqa: E402

FAILS = 0
PASSES = 0


def check(cond, what):
    global FAILS, PASSES
    if cond:
        PASSES += 1
        print("  ok   %s" % what)
    else:
        FAILS += 1
        print("  FAIL %s" % what)


def app():
    """An App with no views and a console of a fixed size, so nothing here
    depends on the terminal it is run in."""
    return App(2.0, Console(width=120, height=40, force_terminal=False))


class Spy(View):
    """A view that records the keys it was offered and claims the ones told."""

    def __init__(self, name, key=None, claims=(), group=None, order=50):
        self.name, self.key, self.group, self.order = name, key, group, order
        self.claims = set(claims)
        self.seen = []
        self.opened = 0
        self.closed = 0

    def on_key(self, app, key):
        self.seen.append(key)
        return key in self.claims

    def build(self, app):
        return [(self.name, Text(self.name))]

    def footer(self, app):
        return Text("footer of " + self.name)

    def on_open(self, app):
        self.opened += 1

    def on_close(self, app):
        self.closed += 1


print("== routing: a submode owns the keyboard, q included")
a = app()
main = Spy("main", claims=("t",))
a.add_view(main)
a.prompt = {"title": "name", "buf": "", "fn": lambda s: ""}
check(a.route_key("q") is True, "q is eaten while a prompt is open")
check(a.prompt["buf"] == "q", "...and typed into it")
check(main.seen == [], "the view was not offered it")
a.route_key("\x1b")
check(a.prompt is None, "esc closes the prompt")

print("== routing: the modal comes after prompt, picker and confirm")
a = app()
a.add_view(Spy("main"))
got = []
a.modal = {"key": got.append, "panel": lambda: None}
a.picker = {"title": "t", "i": 0, "options": ["x"], "fn": lambda c: ""}
a.route_key("DOWN")
check(got == [], "the picker has the keys while it is up")
a.picker = None
a.route_key("DOWN")
check(got == ["DOWN"], "...and the modal gets them back when it is answered")

print("== routing: an open menu beats the active view")
a = app()
v = Spy("main", claims=("t",))
a.add_view(v)
a.add_menu("mux", lambda: [{"label": "one", "act": lambda: ""}])
a.open_menu("mux")
check(a.route_key("t") is True, "a key the view claims is swallowed by the menu")
check(v.seen == [], "the view never saw it")
check(a.route_key("z") is True, "and so is one nobody claims")
a.route_key("\x1b")
check(a.menu is None, "esc at the top closes the menu")

print("== routing: esc_to is the menu's own, not the loop's")
a = app()
a.add_view(Spy("main"))
a.add_menu("mux", lambda: [{"label": "m", "act": lambda: ""}])
a.add_menu("settings", lambda: [{"label": "s", "act": lambda: ""}], esc_to="mux")
a.open_menu("settings")
a.route_key("\x1b")
check(a.menu and a.menu["kind"] == "mux", "esc in a submenu goes to its parent")
a.route_key("\x1b")
check(a.menu is None, "esc at the top closes")

print("== routing: the view, then the shell")
a = app()
v = Spy("main", claims=("t", "c"))
a.add_view(v)
check(a.route_key("t") is True, "the active view claims its own key")
check(a.route_key("q") is False, "and lets q through to the shell")
check(v.seen == ["t", "q"], "it was offered both, in order")
check(a.route_key(None) is False, "a timed-out read routes nowhere")

print("== routing: only the ACTIVE view is offered the key")
a = app()
m, s = Spy("main", claims=("t",)), Spy("sched", key="s", claims=("d",))
a.add_view(m)
a.add_view(s)
a.switch_to("sched")
a.route_key("t")
check(s.seen == ["t"] and m.seen == [], "the inactive view is not consulted")
check(s.opened == 1 and m.closed == 1, "on_open and on_close both fired")

print("== views: a key or a name claimed twice is a start-up error")
a = app()
a.add_view(Spy("main"))
try:
    a.add_view(Spy("main"))
    check(False, "a duplicate NAME is refused")
except RegistrationError as exc:
    check("main" in str(exc), "a duplicate name is refused, naming it")
a = app()
a.add_view(Spy("sched", key="s"))
try:
    a.add_view(Spy("insights", key="s"))
    check(False, "a duplicate KEY is refused")
except RegistrationError as exc:
    check("'sched'" in str(exc) and "'insights'" in str(exc),
          "a duplicate key is refused, naming BOTH views")

print("== open_view_key")
a = app()
a.add_view(Spy("main"))
a.add_view(Spy("sched", key="s"))
check(a.open_view_key("s") is True and a.view == "sched", "s opens the view")
check(a.open_view_key("s") is False, "and pressing it again is not a switch")
check(a.open_view_key("z") is False, "an unclaimed key opens nothing")

print("== tabs: views that share a group, cycled with the arrows")
a = app()
a.add_view(Spy("main"))
a.add_view(Spy("sched", key="s", group="s", order=10))
a.add_view(Spy("handovers", group="s", order=20))
a.switch_to("sched")
check([v.name for v in a.tabs_of(a.view_of())] == ["sched", "handovers"],
      "the strip is the group, in order")
check(a.cycle_tab(1) and a.view == "handovers", "→ goes to the next tab")
check(a.cycle_tab(1) and a.view == "sched", "...and wraps")
check(a.cycle_tab(-1) and a.view == "handovers", "← goes back")
a.switch_to("main")
check(a.cycle_tab(1) is False, "a view with no group has no tabs to cycle")

print("== a strip that does not fit: every tab still reachable with →")
from rich.panel import Panel               # noqa: E402
from dashboard.tabstrip import LOCKED      # noqa: E402


class Tab(Spy):
    def tab_label(self, app):
        return "%s tab with a long label" % self.name

    def build(self, app):
        return [(self.name, Panel(Text(self.name)))]


a = App(2.0, Console(width=40, height=24, force_terminal=False))
names = ["t%02d" % i for i in range(10)]
for i, nm in enumerate(names):
    a.add_view(Tab(nm, key="s" if i == 0 else None, group="s", order=i))
a.switch_to("t00")
seen, scrolled = [], False
for _ in names:
    seen.append(a.view)
    fitted = a.fit_strip(a.view_of())
    scrolled = scrolled or fitted.scrolled
    check(len(Text.from_markup(fitted.markup).plain) <= a.strip_width(),
          "%s: the strip fits 40 columns" % a.view)
    idx = [v.name for v in a.tabs_of(a.view_of())].index(a.view)
    check(idx in fitted.shown and all(i in fitted.shown for i in range(LOCKED)),
          "%s: drawn, and so are the six locked tabs" % a.view)
    a.route_key("RIGHT")
check(seen == names and a.view == "t00", "→ walks all ten and wraps, drawn or not")
check(scrolled, "...and at 40 columns ten tabs do scroll, so that was tested")
a.switch_to("t09")
top = a.console.render_lines(a.build(), a.console.options)[0]
line = "".join(seg.text for seg in top)
check("▸" in line and "«" in line, "the scrolled tab's frame says so: %r" % line)
foot = "".join(seg.text for seg in a.console.render_lines(a.build(), a.console.options)[2])
check("←→ tab 10/10" in foot, "...and the subtitle says where: %r" % foot)

print("== add_rows: order places them, and import order decides nothing")


def base():
    return [{"label": "Settings ▸"}, {"sep": True}, {"label": "Watchdog"},
            {"label": "Quit"}]


def one(_app):
    return [{"label": "Zebra", "act": lambda: ""}]


def two(_app):
    return [{"label": "Aardvark", "act": lambda: ""}]


def labels(a):
    a.menu = {"kind": "mux", "i": 0}
    return [it.get("label", "—") for it in a.menu_entries()]


a = app()
a.add_menu("mux", base)
check(labels(a) == ["Settings ▸", "—", "Watchdog", "Quit"],
      "a menu nobody added to is untouched")

a = app()
a.add_menu("mux", base)
a.add_rows("mux", one, order=15)
a.add_rows("mux", two, order=15)
first = labels(a)
b = app()
b.add_menu("mux", base)
b.add_rows("mux", two, order=15)      # the SAME two, registered the other way
b.add_rows("mux", one, order=15)
check(first == labels(b), "two modules at one order come out the same way "
                          "whichever was imported first")
check(first == ["Settings ▸", "Aardvark", "Zebra", "—", "Watchdog", "Quit"],
      "...sorted by label, between the base rows their order puts them")

a = app()
a.add_menu("mux", base)
a.add_rows("mux", one, order=99)
check(labels(a)[-1] == "Zebra", "a high order lands at the end")
a = app()
a.add_menu("mux", base)
a.add_rows("mux", one, order=5)
check(labels(a)[0] == "Zebra", "a low one lands at the front")

print("== badges: one that raises is dropped, once")
a = app()
calls = []


def boom(_app, session):
    calls.append(session)
    raise ValueError("no")


def fine(_app, session):
    return Text("?")


a.add_badge(boom)
a.add_badge(fine)
check([str(t) for t in a.badges("s1")] == ["?"],
      "the good badge still draws when the other one throws")
check(a.notice and "dropped" in a.notice, "and the notice says one was dropped")
a.notice = None
check([str(t) for t in a.badges("s2")] == ["?"], "the next session still draws")
check(len(calls) == 1, "the broken badge is not called again")
check(a.notice is None, "and is not reported again")

print("== badges and hints: order, and None means nothing")
a = app()
a.add_badge(lambda _a, _s: Text("b"), order=20)
a.add_badge(lambda _a, _s: None, order=30)
a.add_badge(lambda _a, _s: Text("a"), order=10)
check([str(t) for t in a.badges("s")] == ["a", "b"],
      "badges draw in order, and a None is simply not there")
a.add_hint(lambda _a: Text("· 3 ?"))
a.add_hint(lambda _a: None)
check([str(t) for t in a.hints()] == ["· 3 ?"], "so are footer hints")

print("== help: sections in order, ties by title")
a = app()
a.add_help("Zulu", "z", order=10)
a.add_help("Beta", "b", order=50)
a.add_help("Alpha", "a", order=50)
check([t for t, _x in a.help_sections()] == ["Zulu", "Alpha", "Beta"],
      "order first, then the title")

print("== states: registered, and the fallback for one that is not")
a = app()
before = dict(core.STATES)
a.add_state("waiting", "needs you", core.YELLOW)
check(core.STATES["waiting"] == ("needs you", core.YELLOW, False),
      "a module can teach the STATE column a new state")
check("working" in core.STATES and "onlyinthefuture" not in core.STATES,
      "today's states are seeded and an unknown one stays unknown")
core.STATES.clear()
core.STATES.update(before)

print("== the frame: sections, footer, and the menu placed among them")
a = app()
a.add_view(Spy("main"))
frame = a.build()
check(frame is not None, "a frame is built from the view's sections")
a.add_menu("mux", base)
a.open_menu("mux")
check(a.build() is not None, "and with a menu open it is placed, not appended")

print("== a prompt's placeholder: what enter on an empty line takes")
a = app()
a.add_view(Spy("main"))
got = []
a.prompt = {"title": "name", "buf": "", "placeholder": "scripts-otter",
            "fn": lambda s: got.append(s) or ""}
a.route_key("\r")
check(got == ["scripts-otter"], "enter on an empty line takes the placeholder")
got.clear()
a.prompt = {"title": "name", "buf": "", "placeholder": "scripts-otter",
            "fn": lambda s: got.append(s) or ""}
for ch in "mine":
    a.route_key(ch)
a.route_key("\r")
check(got == ["mine"], "and anything typed replaces it")
a.prompt = {"title": "name", "buf": "", "placeholder": "scripts-otter",
            "fn": lambda s: ""}
panel = a._submode_foot()
text = "".join(seg.text for seg in a.console.render(panel))
check("[scripts-otter]" in text, "the offer is drawn in brackets: %r"
      % text.strip()[:60])
a.prompt["buf"] = "m"
text = "".join(seg.text for seg in a.console.render(a._submode_foot()))
check("[scripts-otter]" not in text, "and the brackets go the moment one is typed")
a.prompt = None

print("== a submode goes where the menu layout setting says")
# THE ANSWERS FOLLOW THE QUESTION. A picker used to land in the footer
# whatever `Menu layout` said, so `modal` gave a centred menu and then a
# footer panel for the answers that menu was collecting. place_submode is
# place_menu's rule applied to the other three screens.
import dashboard.app as appmod                       # noqa: E402
from rich.align import Align                         # noqa: E402
from rich.panel import Panel                         # noqa: E402

a = app()
a.add_view(Spy("main"))
sections = [("top", Panel(Text("top"))), ("mid", Panel(Text("mid"))),
            ("low", Panel(Text("low")))]
sub = Panel(Text("pick one"))
real_knob = appmod.knob
try:
    for layout, want in (("bottom", 4), ("table", 3), ("modal", 1)):
        appmod.knob = lambda key, prof=None, _l=layout: _l
        parts = a.place_submode(sections, 1, Panel(Text("pick one"))).renderables
        check(len(parts) == want,
              "%s: %d renderables in the frame" % (layout, len(parts)))
    appmod.knob = lambda key, prof=None: "modal"
    parts = a.place_submode(sections, 1, sub).renderables
    check(isinstance(parts[0], Align), "modal centres it and drops the panels")
    check(sub.expand is False, "and lets it shrink to its content")
    appmod.knob = lambda key, prof=None: "table"
    parts = a.place_submode(sections, 1, Panel(Text("x"))).renderables
    check(parts[0] is sections[0][1] and parts[1] is sections[1][1],
          "table keeps the panels down to the cursor's and drops the rest")
    # NO ROOM: a 6-line console cannot hold three panels and a picker, so
    # this degrades to modal exactly as place_menu does.
    small = App(2.0, Console(width=80, height=6, force_terminal=False))
    small.add_view(Spy("main"))
    parts = small.place_submode(sections, 2, Panel(Text("x"))).renderables
    check(isinstance(parts[0], Align), "and degrades to modal when it will not fit")
finally:
    appmod.knob = real_knob

print()
print("%d assertions passed" % PASSES if not FAILS
      else "%d passed, %d FAILED" % (PASSES, FAILS))
sys.exit(1 if FAILS else 0)
