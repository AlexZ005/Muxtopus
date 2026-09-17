"""dashboard.app -- the App: shared state, the menu engine, and THE SEAM.

Everything on this page is what more than one screen needs: the notice, the
console, the submodes that own the keyboard while they are open, the menu
engine, and the six places a module registers itself. Everything a single
screen needs belongs to that screen's own module instead.

THE SIX REGISTRIES, and what each one exists to stop being an edit to
somebody else's file:

    add_view(view)                              a screen, or a tab of one
    add_menu(kind, entries_fn, ...)             a menu of your own
    add_rows(menu_kind, rows_fn, order=50)      a row in someone else's menu
    add_badge(fn, order=50) / add_hint(fn)      a mark on a session row, a
                                                note in the main footer
    add_help(title, text, order=50)             one section of `?`
    add_state(name, label, style)               how a watchdog state is drawn

A module is DISCOVERED, not listed (see the shell's `load_modules`): no file
anywhere names the modules, because a list is a line every lane would have to
edit, which is the queue this split exists to end. A module that fails to
import is skipped with a red notice and the dashboard runs without it.

KEY ROUTING, ONE RULE, and it is today's order exactly:

    a submode (prompt, confirm, picker, or a view's own modal)
      -> an open menu
        -> the active view's on_key
          -> the shell's globals (q R ? p u U w m f)
            -> the keys that open a view

A submode swallows everything while it is open, `q` included: typing a window
name with a "q" in it must not quit the dashboard. Two views claiming one key
is a registration ERROR at start-up naming both, not last-one-wins.
"""
from __future__ import annotations

import time

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

from dashboard.core import (DIM, PROFILE, RED, SCRIPTS, STATES, knob)
from dashboard.menulayout import (MENU_MIN, menu_needed, menu_panel,
                                  rendered_height)

# The hint under a menu when its kind does not name its own.
MENU_HINT = "↑↓ pick · enter choose · esc close"


class RegistrationError(RuntimeError):
    """Two modules claiming one thing. Raised at start-up, naming both."""


class View:
    """What a view provides. Subclassing is optional -- any object with these
    attributes works -- but it is the written-down shape.

        name        unique; how other modules ask for it (app.view("main"))
        key         opens it from the main view; None for the main view itself
        group       views sharing a group are TABS of one screen, ←→ cycles
        order       position within the group, and among the view keys

        tab_label(app)      the strip's text for this tab
        build(app)          -> [(section name, panel)], top to bottom
        menu_anchor(app)    which section index an open menu hangs under
        footer(app)         -> Text, the key line when nothing else owns it
        on_key(app, key)    -> True if the key was this view's
        on_open/on_close(app)
    """

    name = ""
    key = None
    group = None
    order = 50

    def tab_label(self, app):
        return self.name

    def build(self, app):
        return []

    def menu_anchor(self, app):
        return 0

    def footer(self, app):
        return None

    def on_key(self, app, key):
        return False

    def on_open(self, app):
        pass

    def on_close(self, app):
        pass


class App:
    """The state every screen shares, and the registries every screen fills."""

    def __init__(self, interval: float, console: Console | None = None) -> None:
        self.interval = interval
        # The console is what knows the terminal's height, and the height is
        # what a menu is measured against (place_menu). One object, shared
        # with Live, so the size it reports is the size being drawn to.
        self.console = console or Console()
        self.notice: str | None = None
        self.notice_at = 0.0
        self.party_at = 0.0
        # ONE STATE FOR EVERY MENU: the per-window one on space, the
        # per-entry one in the schedule view, the dashboard's own on esc and
        # its Settings submenu. They share the mover, the activator and the
        # drawing; only the registered entries function differs.
        self.menu: dict | None = None      # {"kind": ..., "i": int}
        self.prompt: dict | None = None    # inline text entry (rename)
        self.confirm: dict | None = None   # yes/no gate (close)
        self.picker: dict | None = None    # arrow-driven option list
        # A VIEW'S OWN MODAL -- the options table is the one today. The App
        # does not know what is in it: {"key": fn(key), "panel": fn()} plus
        # whatever the view keeps there. It sits BELOW the other three in the
        # routing order, so a value the prompt or the picker is collecting
        # FOR it still owns the keys while that is up.
        self.modal: dict | None = None
        # Reload and quit have to happen in main(), where Live and the saved
        # terminal state are; a menu row can only ask for them.
        self.pending_reload = False
        self.pending_quit = False
        # A --check report to show full screen, the way the editor and btop
        # take the terminal over: main() owns Live and the tty state.
        self.pending_report: str | None = None
        self.pending_edit: str | None = None   # file the main loop opens
        # THE ONE PIECE OF A VIEW'S STATE THE SHARED CANCEL STILL TOUCHES:
        # esc in a prompt, a confirm or a picker abandons the new-session
        # flow, because those three screens are what that flow is made of.
        # It lives here so App can be built and tested on its own; whether a
        # submode should instead carry its own on_cancel is a question for
        # whoever next has a flow, and it is in the handover.
        self.ns: dict | None = None
        self.view = "main"                 # the ACTIVE view's name
        self.version = (SCRIPTS / "VERSION").read_text().strip() \
            if (SCRIPTS / "VERSION").exists() else "?"

        # ------------------------------------------------- the registries
        self._views: dict[str, View] = {}
        self._view_keys: dict[str, str] = {}
        self._menus: dict[str, dict] = {}
        self._rows: dict[str, list] = {}
        self._badges: list = []
        self._badge_broken: set = set()
        self._hints: list = []
        self._help: list = []
        # What did not load. The notice says it once when it happens; this
        # keeps it for a screen that wants to say it again (phase 5's `?`).
        self.load_errors: list[str] = []
        # Registration order is never allowed to decide anything, but sorted()
        # must not be asked to compare two functions either; this is the
        # tie-break that keeps it from having to.
        self._seq = 0

    def module_failed(self, name: str, exc: Exception) -> None:
        """A view or a menu module that would not load. Said out loud and
        remembered, and the dashboard carries on without it -- one lane's bad
        commit must not take down the screen the others are tested in."""
        self.load_errors.append("%s: %s" % (name, exc))
        self.say("%s failed to load: %s" % (name, exc))

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    # ====================================================== the registries
    def add_view(self, view) -> None:
        """A screen, or a tab of one.

        A name or a key claimed twice is a RegistrationError naming both
        modules: last-one-wins would make which module loaded first decide
        what a key does, and that is a bug nobody can read off the screen."""
        if view.name in self._views:
            raise RegistrationError(
                "two views are called %r: %s and %s"
                % (view.name, type(self._views[view.name]).__module__,
                   type(view).__module__))
        if view.key:
            if view.key in self._view_keys:
                raise RegistrationError(
                    "%r opens two views: %r and %r"
                    % (view.key, self._view_keys[view.key], view.name))
            self._view_keys[view.key] = view.name
        self._views[view.name] = view

    def add_menu(self, kind: str, entries_fn, title_fn=None, hint_fn=None,
                 esc_to: str | None = None) -> None:
        """A menu of your own. `esc_to` names the parent kind esc goes back
        to, which generalises the one hard-coded "settings goes back to mux"."""
        if kind in self._menus:
            raise RegistrationError("two menus are called %r" % kind)
        self._menus[kind] = {"entries": entries_fn, "title": title_fn,
                             "hint": hint_fn, "esc_to": esc_to}

    def add_rows(self, menu_kind: str, rows_fn, order: int = 50) -> None:
        """Rows INTO someone else's menu -- how `ESC ▸ Insights` arrives
        without dashboard/menus/mux.py being edited.

        ORDER places them. A menu's own rows take the positional orders 10,
        20, 30 ... unless a row names its own, so `order=35` lands between
        the third and the fourth. Ties sort by LABEL, never by registration,
        so two modules adding rows at the same order come out the same way
        whatever sequence they were imported in."""
        self._rows.setdefault(menu_kind, []).append((order, self._next(), rows_fn))

    def add_badge(self, fn, order: int = 50) -> None:
        """A short mark beside a session's name: fn(app, session) -> Text|None.

        IT MUST NOT FORK. The main frame is measured in forks per second (2),
        and a badge runs once per session per frame; read a file, or read
        something already cached, and nothing else.

        A badge that RAISES is dropped -- not for that row, for good -- and
        said once. A badge that throws for one session almost always throws
        for the next one, and catching it per row per frame is a cost the
        frame is too tight to pay to be told the same thing sixty times."""
        self._badges.append((order, self._next(), fn))

    def add_hint(self, fn) -> None:
        """A note for the main view's footer: fn(app) -> Text | None."""
        self._hints.append(fn)

    def add_help(self, title: str, text: str, order: int = 50) -> None:
        """One section of `?`. Sections print in order; ties sort by title."""
        self._help.append((order, title, text, self._next()))

    def add_state(self, name: str, label: str, style: str,
                  with_reset: bool = False) -> None:
        """How the STATE column draws one watchdog state. An unregistered
        state keeps the fallback it has always had: dim, under its own name.
        `with_reset` appends the row's reset time, as due and limited do."""
        STATES[name] = (label, style, with_reset)

    # --------------------------------------------------------- the lookups
    def view_of(self, name: str | None = None):
        """A view by name, or the active one. The named accessors a view
        offers other views are the ONLY supported way across the line; see
        docs/dashboard-views.md for the list."""
        return self._views.get(name or self.view)

    def views(self) -> list:
        return sorted(self._views.values(), key=lambda v: (v.order, v.name))

    def tabs_of(self, view) -> list:
        """The views that share this one's group, in order -- its tab strip.
        A view with no group is its own screen and has no strip."""
        if not getattr(view, "group", None):
            return []
        return [v for v in self.views() if getattr(v, "group", None) == view.group]

    def badges(self, session) -> list:
        out = []
        for _order, _seq, fn in sorted(self._badges, key=lambda b: (b[0], b[1])):
            if fn in self._badge_broken:
                continue
            try:
                mark = fn(self, session)
            except Exception as exc:                      # noqa: BLE001
                self._badge_broken.add(fn)
                self.say("badge %s dropped: %s"
                         % (getattr(fn, "__module__", "?"), exc))
                continue
            if mark is not None:
                out.append(mark)
        return out

    def hints(self) -> list:
        out = []
        for fn in self._hints:
            mark = fn(self)
            if mark is not None:
                out.append(mark)
        return out

    def help_sections(self) -> list:
        return [(t, x) for _o, t, x, _s
                in sorted(self._help, key=lambda h: (h[0], h[1]))]

    def help_screen(self) -> str:
        """`?`, assembled from what the LOADED MODULES say about themselves.

        Each section is the whole block, its own dim heading included, and
        they are simply concatenated -- so registering today's sections at
        the orders they already had reproduces the old 290-line string
        exactly, which is what phase 5 of the split did. A module that loads
        adds its section; a module that does not, does not, and the screen
        still describes the dashboard the reader is actually looking at."""
        return "".join(text for _title, text in self.help_sections())

    # ============================================================== notice
    def say(self, msg: str) -> None:
        self.notice, self.notice_at = msg, time.time()

    def showing_notice(self) -> bool:
        return bool(self.notice) and time.time() - self.notice_at < 8

    # ========================================================= the menu
    def menu_entries(self) -> list[dict]:
        """The rows of whichever menu is open, rebuilt every frame so the
        labels state what is true right now -- the menu's own, plus whatever
        other modules registered into it."""
        kind = self.menu["kind"] if self.menu else "session"
        spec = self._menus.get(kind)
        if spec is None:
            return []
        items = list(spec["entries"]())
        added = self._rows.get(kind)
        if not added:
            return items
        rows = [(it.get("order", (i + 1) * 10), 0, "", i, it)
                for i, it in enumerate(items)]
        for order, seq, fn in sorted(added, key=lambda r: (r[0], r[1])):
            for j, it in enumerate(fn(self) or []):
                rows.append((it.get("order", order), 1, it.get("label", ""), j, it))
        rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
        return [r[4] for r in rows]

    def menu_title(self) -> str:
        """Markup, minus the leading [bold] menu_panel adds. A menu that
        names no title function gets the plain one."""
        kind = self.menu["kind"] if self.menu else "session"
        spec = self._menus.get(kind) or {}
        fn = spec.get("title")
        return fn() if fn else "menu"

    def menu_hint(self) -> str:
        kind = self.menu["kind"] if self.menu else "session"
        spec = self._menus.get(kind) or {}
        fn = spec.get("hint")
        hint = fn() if fn else MENU_HINT
        # THE NOTICE HAS TO LIVE HERE while a menu is open: the menu replaces
        # the footer that normally shows it, and a Settings row that stays
        # open would otherwise report "not a directory" to nobody -- the same
        # hole the options table had. It shares the hint line, so the panel's
        # height is the same with or without it.
        if self.showing_notice():
            return "%s   ·   %s" % (self.notice, hint)
        return hint

    def place_menu(self, sections: list, at: int) -> Group:
        """The frame with the open menu in it, NEVER clipped.

        `sections` are the frame's panels top to bottom and `at` is the index
        of the one the cursor is in. Which of them stay depends on the
        layout setting; the room left under the ones that stay is MEASURED
        (rendered_height: what Rich will really draw, not a row count), and
        the menu is given min(room, what it needs) lines and scrolls inside
        them. That is the whole fix for the reported bug -- the footer menu
        was the last thing in a Group that Live crops from the bottom.

          table   the cursor's panel stays, the menu goes right under it,
                  everything below is dropped while it is open
          modal   the menu alone, centred; the frame comes back on esc
          bottom  the old position, capped and scrolling

        With less than MENU_MIN lines left -- a 24-row terminal and a tall
        sessions table -- the frame degrades to modal for this one open,
        and the title says so; a menu is scrolled, never cut."""
        layout = knob("DASHBOARD_MENU_LAYOUT", PROFILE) or "table"
        items = self.menu_entries()
        cur = self.menu["i"]
        height = self.console.size.height
        if layout == "bottom":
            kept = [p for _n, p in sections]
        elif layout == "modal":
            kept = []
        else:
            layout = "table"
            kept = [p for _n, p in sections[:at + 1]]
        room = height - rendered_height(self.console, Group(*kept)) if kept else height
        title = self.menu_title()
        if room < MENU_MIN:
            layout, kept, room = "modal", [], height
            title += "[/] [%s](modal: no room below)" % DIM
        rows = max(MENU_MIN, min(room, menu_needed(items)))
        panel = menu_panel(items, cur, title, rows, self.menu_hint())
        if layout == "modal":
            panel.expand = False
            return Group(Align.center(panel, vertical="middle", height=height))
        return Group(*kept, panel)

    def open_menu(self, kind: str) -> None:
        self.menu = {"kind": kind, "i": 0}
        self.menu_move(0)

    def menu_move(self, delta: int) -> None:
        if self.menu is None:
            return
        items = self.menu_entries()
        if not items:
            return
        i = self.menu["i"]
        if delta == 0 and 0 <= i < len(items) and not items[i].get("sep") \
                and not items[i].get("disabled"):
            return
        step = delta or 1
        for _ in range(len(items)):
            i = (i + step) % len(items)
            if not items[i].get("sep") and not items[i].get("disabled"):
                self.menu["i"] = i
                return

    def menu_activate(self) -> None:
        if self.menu is None:
            return
        items = self.menu_entries()
        i = self.menu["i"]
        if not (0 <= i < len(items)):
            return
        it = items[i]
        if it.get("sep") or it.get("disabled"):
            return
        if it.get("sub"):
            self.open_menu(it["sub"])
            return
        msg = it["act"]()
        # A submode owns the screen until it is answered; a plain action is
        # done, unless the row says it stays (a toggle you may want to flip
        # back, a setting beside other settings).
        if self.prompt is None and self.confirm is None and self.picker is None:
            if not it.get("stay"):
                self.menu = None
        if msg:
            self.say(msg)

    def menu_esc(self) -> None:
        """esc means "back" in a submenu and "close" at the top, exactly as
        it does everywhere else on this screen. Which is which is the menu's
        own `esc_to`, not a name this file knows."""
        kind = self.menu["kind"] if self.menu else ""
        parent = (self._menus.get(kind) or {}).get("esc_to")
        if parent:
            self.open_menu(parent)
        else:
            self.menu = None

    # ======================================================= the submodes
    def prompt_key(self, key: str) -> None:
        pr = self.prompt
        if pr is None:
            return
        if key in ("\r", "\n"):
            fn = pr["fn"]
            text = pr["buf"]
            self.prompt = None
            if not pr.get("keep_menu"):
                self.menu = None
            self.say(fn(text))
        elif key == "\x1b":
            self.prompt = None
            self.ns = None
            self.say("cancelled")
        elif key in ("\x7f", "\b"):
            pr["buf"] = pr["buf"][:-1]
        elif len(key) == 1 and key.isprintable():
            pr["buf"] += key

    def confirm_key(self, key: str) -> None:
        cf = self.confirm
        if cf is None:
            return
        if key in ("y", "Y"):
            fn = cf["fn"]
            self.confirm = None
            self.menu = None
            self.say(fn())
        elif key in ("n", "N", "\r", "\n") and cf.get("no_fn"):
            # "no" is an answer, not an abort, when the confirm sits inside a
            # flow (the bypass warning: no means "this window only").
            fn = cf["no_fn"]
            self.confirm = None
            self.say(fn())
        elif key in ("n", "N", "\x1b", "\r", "\n"):
            self.confirm = None
            self.ns = None
            self.say("cancelled")

    def picker_key(self, key: str) -> None:
        pk = self.picker
        if pk is None:
            return
        n = len(pk["options"])
        if key == "UP":
            pk["i"] = n - 1 if pk["i"] < 0 else (pk["i"] - 1) % n
        elif key == "DOWN":
            pk["i"] = 0 if pk["i"] < 0 else (pk["i"] + 1) % n
        elif key in ("\r", "\n"):
            if pk["i"] < 0:
                return
            fn, choice = pk["fn"], pk["options"][pk["i"]]
            self.picker = None
            msg = fn(choice)
            if msg:
                self.say(msg)
        elif key == "\x1b":
            self.picker = None
            self.ns = None
            self.say("cancelled")

    def _submode_foot(self):
        """The footer panel when a text prompt, confirm, picker or a view's
        own modal owns the keyboard -- shared by every view, so a flow works
        from whichever one started it."""
        if self.prompt is not None:
            return Panel(
                Text.assemble((self.prompt["title"] + ": ", "bold"),
                              (self.prompt["buf"], "#c9a0dc"), ("_", "bold #c9a0dc"),
                              ("      enter save · esc cancel", DIM)),
                border_style="#c9a0dc", box=box.ROUNDED)
        if self.confirm is not None:
            return Panel(
                Text.assemble((self.confirm["label"], "bold"), "    ",
                              ("y", "bold " + RED), (" yes    ", DIM),
                              ("n", "bold"), (" no", DIM)),
                border_style=RED, box=box.ROUNDED)
        if self.picker is not None:
            body = Text()
            for i, opt in enumerate(self.picker["options"]):
                cur = (i == self.picker["i"])
                body.append(" ▸ " if cur else "   ", style="bold #c9a0dc")
                body.append(opt + "\n", style="bold" if cur else "")
            # i < 0 is "nothing preselected": no row is marked until an
            # arrow moves, and enter says so. That is what "always ask" means
            # for an arrow-driven list.
            body.append("   ↑↓ pick · enter choose · esc cancel"
                        if self.picker["i"] >= 0 else
                        "   nothing preselected — ↑↓ pick one · esc cancel", style=DIM)
            return Panel(body, title="[bold]" + self.picker["title"],
                         title_align="left", border_style="#c9a0dc", box=box.ROUNDED)
        if self.modal is not None:
            return self.modal["panel"]()
        return None

    def in_submode(self) -> bool:
        return (self.prompt is not None or self.confirm is not None
                or self.picker is not None or self.modal is not None)

    # ========================================================== the frame
    def tab_strip(self, view) -> str | None:
        """The strip of tabs for the group this view is in, as markup, or
        None when it is a screen of its own.

        IT COSTS NO ROWS: it is drawn as the first panel's TITLE, which is a
        line that exists anyway. That is why a tab is cheap enough to be the
        answer for the handovers list and for anything else that is a second
        table of the same kind of thing."""
        tabs = self.tabs_of(view)
        if len(tabs) < 2:
            return None
        bits = []
        for tab in tabs:
            label = tab.tab_label(self)
            bits.append("[bold]▸%s[/]" % label if tab is view
                        else "[%s]%s[/]" % (DIM, label))
        return ("[%s] │ [/]" % DIM).join(bits)

    def build(self) -> Group:
        """One frame: the active view's sections, with the open menu placed
        among them or the footer under them."""
        view = self.view_of()
        sections = view.build(self)
        strip = self.tab_strip(view)
        if strip and sections:
            # The panel is built fresh every frame, so this is a decoration
            # of this frame's copy and not a change to the view's own idea of
            # its title.
            panel = sections[0][1]
            panel.title = strip
            panel.title_align = "left"
            panel.subtitle = "[%s]←→ tab" % DIM
            panel.subtitle_align = "right"
        sub = self._submode_foot()
        if self.menu is not None and sub is None:
            return self.place_menu(sections, view.menu_anchor(self))
        return Group(*[p for _n, p in sections], sub or view.footer(self))

    # ======================================================== key routing
    def route_key(self, key: str | None) -> bool:
        """The first three steps of the one rule. True when the key was eaten.

        A SUBMODE OWNS THE KEYBOARD while it is open, and it is checked
        before every global key -- including q. Typing a window name that
        contains a "q" must not quit the dashboard, and neither must
        answering a confirm."""
        if key is None:
            return False
        if self.in_submode() or self.menu is not None:
            if self.prompt is not None:
                self.prompt_key(key)
            elif self.confirm is not None:
                self.confirm_key(key)
            elif self.picker is not None:
                self.picker_key(key)
            # The modal is checked AFTER those three, so a value the prompt
            # or the picker is collecting FOR it still owns the keys while it
            # is up, and the modal comes back when it is answered.
            elif self.modal is not None:
                self.modal["key"](key)
            elif key == "UP":
                self.menu_move(-1)
            elif key == "DOWN":
                self.menu_move(1)
            elif key in ("\r", "\n"):
                self.menu_activate()
            elif key in ("\x1b", " ", "q", "Q"):
                if key == "\x1b":
                    self.menu_esc()
                else:
                    self.menu = None
            return True
        view = self.view_of()
        # ←→ BELONG TO THE TAB STRIP when there is one, and to the view when
        # there is not: the main view folds its tree with them, and it is a
        # screen of its own, so it keeps them.
        if key in ("LEFT", "RIGHT") and len(self.tabs_of(view)) > 1:
            return self.cycle_tab(1 if key == "RIGHT" else -1)
        return bool(view and view.on_key(self, key))

    def open_view_key(self, key: str | None) -> bool:
        """The last step: a key that opens a view, or leaves the one it
        opened. Views sharing a group are tabs and are reached with ←→ from
        inside the group, not by a key each."""
        name = self._view_keys.get(key)
        if not name or name == self.view:
            return False
        self.switch_to(name)
        return True

    def switch_to(self, name: str) -> None:
        if name == self.view or name not in self._views:
            return
        old = self.view_of()
        if old is not None:
            old.on_close(self)
        self.view = name
        self.view_of().on_open(self)

    def cycle_tab(self, delta: int) -> bool:
        """←→ between the views that share the active one's group."""
        view = self.view_of()
        tabs = self.tabs_of(view)
        if len(tabs) < 2:
            return False
        i = tabs.index(view)
        self.switch_to(tabs[(i + delta) % len(tabs)].name)
        return True
