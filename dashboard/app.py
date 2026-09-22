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
      / add_version_note(fn)                    note in the main footer, a
                                                note beside the version
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
from dashboard.tabstrip import fit
from dashboard.menulayout import (BODY_MIN, PAGE_KEYS,
                                  menu_chrome, menu_desc_lines,
                                  menu_head_lines, menu_needed, menu_panel,
                                  page_jump, page_land,
                                  rendered_height)

# The setting that hides tabs (dashboard/menus/tabs.py draws its menu).
TABS_KEY = "DASHBOARD_TABS_HIDDEN"

# The hint under a menu when its kind does not name its own.
MENU_HINT = "↑↓ pick · enter choose · esc close"


def row_id(it: dict) -> str:
    """What a menu row is called, for finding it again in a LATER frame.

    NOT ITS INDEX. These menus are rebuilt every frame and rows come and go:
    `Restore N windows` is there only while the watchdog holds a snapshot,
    `Update to X ▸` only while a release is waiting, `Open ... once` only for
    a hidden tab. The third row is not the same row a minute later, so an
    index remembered across an open lands on whatever moved into it.

    A row that carries an explicit `key` uses it (the main view's two window
    toggles do). Everything else is matched on the head of its LABEL: the
    part before the two spaces that separate a label from an explanation
    still glued to it, and then the part before the first ": ", because a
    label states its own value ("Watchdog: ON", "Menu layout: modal") and the
    value is exactly the half that changes while you are away from the row.
    """
    if it.get("key"):
        return str(it["key"])
    return str(it.get("label", "")).split("  ")[0].split(": ")[0].strip()


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
        # THE OPEN MENU'S PAGE, for PageUp/PageDown: the item lines
        # place_menu actually gave it this frame, not a constant. A menu is
        # drawn before a key can reach it, so this is only ever the default
        # for a menu nobody has seen.
        self._menu_page = BODY_MIN
        # WHICH ROW A SUBMENU WAS OPENED FROM: {child kind: row_id}, written
        # when enter descends into a `sub` and read when esc comes back up,
        # so `Settings ▸ Tabs ▸` lands on `Tabs ▸` again and not on the first
        # Settings row. Not an index -- see row_id.
        self._menu_from: dict[str, str] = {}
        # An inline text entry (rename, the new window's name). Optionally
        # carries a `placeholder`: what enter on an EMPTY line means, drawn
        # in brackets where the typing would go. See prompt_key.
        self.prompt: dict | None = None
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
        # WHAT IS ON DISK NOW, which after an update is not what is RUNNING:
        # this process imported its modules at start-up and an update
        # replaced them underneath it. The header says so until R re-execs.
        # Read at most every five seconds -- it changes about once a month.
        self._disk_version = self.version
        self._disk_at = 0.0

        # ------------------------------------------------- the registries
        self._views: dict[str, View] = {}
        self._view_keys: dict[str, str] = {}
        self._menus: dict[str, dict] = {}
        self._rows: dict[str, list] = {}
        self._badges: list = []
        self._badge_broken: set = set()
        self._hints: list = []
        self._version_notes: list = []
        self._help: list = []
        # What did not load. The notice says it once when it happens; this
        # keeps it for a screen that wants to say it again (phase 5's `?`).
        self.load_errors: list[str] = []
        # Registration order is never allowed to decide anything, but sorted()
        # must not be asked to compare two functions either; this is the
        # tie-break that keeps it from having to.
        self._seq = 0
        # DASHBOARD_TABS_HIDDEN, read at most once a second: tabs_of is asked
        # several times a frame, and the menu that writes it says forget.
        self._hidden: tuple | None = None

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
                 esc_to: str | None = None, on_esc=None, desc_fn=None) -> None:
        """A menu of your own. `esc_to` names the parent kind esc goes back
        to, which generalises the one hard-coded "settings goes back to mux".

        `on_esc` is what CLOSING it means, for a menu that is holding
        something: the new-session form is half-filled answers, and esc there
        has to throw them away and say so, not just stop drawing. A menu that
        names neither closes silently, which is what a list of actions
        should do.

        `desc_fn() -> str` is the menu's OWN explanation, drawn once under
        its title border. It is where a submenu says what it is for: on the
        parent's row that sentence is read once and then re-read on every
        visit to a menu it is not about, and it makes the parent's row too
        wide for the panel to be worth capping.

        `hint_fn() -> str | None` fills THE MENU'S HINT LINE, the one inside
        the panel; None draws no such line and gives the row to the list."""
        if kind in self._menus:
            raise RegistrationError("two menus are called %r" % kind)
        self._menus[kind] = {"entries": entries_fn, "title": title_fn,
                             "hint": hint_fn, "esc_to": esc_to,
                             "on_esc": on_esc, "desc": desc_fn}

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

    def add_version_note(self, fn) -> None:
        """A note beside the VERSION in the deck header: fn(app) -> markup|None.

        add_hint's sibling, and it exists for the same reason: the one module
        that knows a new release is waiting is dashboard/menus/update.py, and
        the header is drawn by dashboard/views/main.py. Without this, saying
        so in the header would be main.py importing the update menu -- the
        cross-view reach every registry here exists to end.

        MARKUP, not Text, because the subtitle it joins is markup already
        (the "-> X installed, press R" the stale() check appends is the line
        this was modelled on). Escape anything that came off disk.
        """
        self._version_notes.append(fn)

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

    def group_tabs(self, view) -> list:
        """EVERY view that shares this one's group, hidden or not, in order.
        A view with no group is its own screen and has no tabs."""
        if not getattr(view, "group", None):
            return []
        return [v for v in self.views() if getattr(v, "group", None) == view.group]

    def tabs_of(self, view) -> list:
        """The tab strip: the group less the tabs the user hid (Settings ▸
        Tabs) -- but never less `view` itself. A hidden tab reached by its
        key or by "Open once" is in the strip while you are on it, so ←→
        from it has somewhere to start and the cycle cannot break."""
        hidden = self.hidden_tabs()
        return [v for v in self.group_tabs(view) if v.name not in hidden or v is view]

    def hidden_tabs(self) -> set:
        now = time.time()
        if self._hidden is None or now - self._hidden[0] > 1.0:
            raw = knob(TABS_KEY, PROFILE) or ""
            self._hidden = (now, {x.strip() for x in raw.split(",") if x.strip()})
        return self._hidden[1]

    def forget_hidden(self) -> None:
        self._hidden = None

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

    def stale(self) -> str:
        """The version INSTALLED, when it is not the one this process is
        running; "" the rest of the time. An update applied from the menu
        sets pending_reload itself, so this is for the other ways it can
        happen: `muxtopus update` in a terminal, or a second dashboard."""
        now = time.time()
        if now - self._disk_at > 5.0:
            self._disk_at = now
            try:
                self._disk_version = (SCRIPTS / "VERSION").read_text().strip()
            except OSError:
                pass
        return "" if self._disk_version == self.version else self._disk_version

    def hints(self) -> list:
        out = []
        for fn in self._hints:
            mark = fn(self)
            if mark is not None:
                out.append(mark)
        return out

    def version_notes(self) -> list:
        """What the loaded modules want said beside the version, as markup."""
        out = []
        for fn in self._version_notes:
            mark = fn(self)
            if mark:
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

    def menu_hint(self) -> str | None:
        """THE MENU'S OWN HINT LINE, or None for a menu that draws none.

        Not App.add_hint, which writes on the main view's footer key line and
        never reaches a panel. A `hint_fn` returning None is how that line is
        turned off; menu_panel then reserves nothing for it."""
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
            # ...and a menu with NO hint line still has to say it: the line
            # comes back for the eight seconds the notice lasts rather than
            # the notice going nowhere. A menu grown by one line for a
            # message is the honest failure; a message nobody sees is not.
            return "%s   ·   %s" % (self.notice, hint or "")
        return hint

    def menu_desc(self) -> str:
        """The open menu's own explanation, drawn once under its title."""
        kind = self.menu["kind"] if self.menu else "session"
        spec = self._menus.get(kind) or {}
        fn = spec.get("desc")
        return (fn() if fn else "") or ""

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

        With less room left than the menu's own minimum -- a 24-row
        terminal and a tall sessions table -- the frame degrades to modal for
        this one open, and the title says so; a menu is scrolled, never cut.
        That minimum is three item lines plus whatever the menu's header,
        its descriptions and its hint line reserve (_menu_budget)."""
        layout = knob("DASHBOARD_MENU_LAYOUT", PROFILE) or "table"
        items = self.menu_entries()
        cur = self.menu["i"]
        height = self.console.size.height
        width = self.console.size.width
        if layout == "bottom":
            kept = [p for _n, p in sections]
        elif layout == "modal":
            kept = []
        else:
            layout = "table"
            kept = [p for _n, p in sections[:at + 1]]
        room = height - rendered_height(self.console, Group(*kept)) if kept else height
        title = self.menu_title()
        hint, header = self.menu_hint(), self.menu_desc()
        # The reservation for the menu's header and for its rows' descriptions
        # is measured HERE as well as in menu_panel, from the same two pure
        # functions and the same width, because the row budget below is what
        # decides whether this menu fits at all.
        desc_rows: int | None = None
        chrome, least = self._menu_budget(items, header, hint, width)
        if height < least:
            # THE EXPLANATIONS GO BEFORE THE LIST DOES. A terminal too short
            # to hold a header, a description and three item lines keeps the
            # rows -- a menu is a list you pick from, and an explanation of a
            # row you cannot see is worth nothing.
            header, desc_rows = "", 0
            chrome = menu_chrome(hint is not None)
            least = chrome + BODY_MIN
        if room < least:
            layout, kept, room = "modal", [], height
            title += "[/] [%s](modal: no room below)" % DIM
        rows = max(least, min(room, menu_needed(items, chrome)))
        self._menu_page = max(1, rows - chrome)
        panel = menu_panel(items, cur, title, rows, hint, width=width,
                           header=header, desc_rows=desc_rows)
        if layout == "modal":
            panel.expand = False
            return Group(Align.center(panel, vertical="middle", height=height))
        return Group(*kept, panel)

    def _menu_budget(self, items: list, header: str, hint: str | None,
                     width: int) -> tuple[int, int]:
        """(the lines that are not items, the fewest rows the menu can hold).

        One place, so place_menu's budget and menu_panel's drawing cannot
        disagree about how many lines the header and the descriptions took."""
        chrome = menu_chrome(hint is not None,
                             menu_desc_lines(items, width),
                             menu_head_lines(header, width))
        return chrome, chrome + BODY_MIN

    def place_submode(self, sections: list, at: int, sub) -> Group:
        """The frame with the open PROMPT, CONFIRM, PICKER or modal in it,
        under the same layout setting the menus obey.

        A submode is a question a menu row asked -- the folder picker, the
        name prompt, the bypassPermissions warning -- and it used to land at
        the bottom of the screen whatever `Menu layout` said, so a user who
        set `modal` got a centred menu and then a footer panel for its
        answers: the question moved away from where the asking was. There is
        no separate setting for it, because "where does a menu go" and "where
        do its answers go" is one question and nobody would want two answers.

          table   under the cursor's panel, everything below dropped
          modal   the submode alone, centred
          bottom  the whole frame, the submode under it

        A submode is measured rather than given a budget: it is a handful of
        lines that draws every one of them (a picker has no viewport to
        scroll), so when the room under the kept panels is less than it
        needs, this degrades to modal exactly as place_menu does."""
        layout = knob("DASHBOARD_MENU_LAYOUT", PROFILE) or "table"
        height = self.console.size.height
        if layout == "bottom":
            return Group(*[p for _n, p in sections], sub)
        kept = [] if layout == "modal" else [p for _n, p in sections[:at + 1]]
        if kept:
            room = height - rendered_height(self.console, Group(*kept))
            if room < rendered_height(self.console, sub):
                kept = []
        if not kept:
            # expand=False is what makes a centred panel the width of its
            # content instead of the console's -- the same line place_menu
            # needs for the same reason.
            sub.expand = False
            return Group(Align.center(sub, vertical="middle", height=height))
        return Group(*kept, sub)

    def open_menu(self, kind: str, at: str = "") -> None:
        """Open a menu, with the cursor on the row `at` names (row_id) when
        it is still there and on the first one when it is not.

        A FRESH open -- esc, space, c -- passes nothing and starts at the top,
        as it always has; `at` is how esc out of a submenu comes back to the
        row it was opened from."""
        self.menu = {"kind": kind, "i": 0}
        if at:
            for j, it in enumerate(self.menu_entries()):
                if row_id(it) == at and not it.get("sep") and not it.get("disabled"):
                    self.menu["i"] = j
                    break
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

    def menu_page(self, key: str) -> None:
        """PageUp/PageDown/Home/End in an open menu.

        The same jump every other list on this screen makes, and off the
        separators and the disabled rows the mover already skips -- a page
        that parks the cursor on a separator would make the next enter do
        nothing."""
        if self.menu is None:
            return
        items = self.menu_entries()
        if not items:
            return
        j = page_land(key, self.menu["i"], len(items), self._menu_page,
                      lambda k: bool(items[k].get("sep")
                                     or items[k].get("disabled")))
        if j is not None:
            self.menu["i"] = j

    def _menu_edit(self, key: str) -> bool:
        """Hand `key` to the row under the cursor, if that row is a FIELD.

        A row becomes one by carrying `"edit": fn`, where fn(key) returns True
        for a key it consumed and False for one it did not -- so a field takes
        the letters and backspace and leaves everything else to the menu. This
        is deliberately the whole of the mechanism: the row owns its buffer and
        its rules, and App only has to know where in the key order to ask.

        Returns True when the row took the key."""
        if self.menu is None:
            return False
        items = self.menu_entries()
        i = self.menu["i"]
        if not (0 <= i < len(items)):
            return False
        fn = items[i].get("edit")
        return bool(fn and fn(key))

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
            spec = self._menus.get(self.menu["kind"]) or {}
            if it["sub"] == spec.get("esc_to"):
                # A `Back` ROW IS ESC. It walks the same edge esc_to names, so
                # it has to land on the same row esc lands on -- and it must
                # not be recorded as a descent, or the next esc out of THIS
                # menu would try to put the cursor on a "Back" that is in the
                # child and not in the parent.
                self.menu_esc()
                return
            self._menu_from[it["sub"]] = row_id(it)
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
        spec = self._menus.get(kind) or {}
        parent = spec.get("esc_to")
        if parent:
            # POPPED, not kept: the next open of this submenu from somewhere
            # else must not inherit where this one came from.
            self.open_menu(parent, self._menu_from.pop(kind, ""))
        else:
            self.menu = None
            fn = spec.get("on_esc")
            if fn is not None:
                msg = fn()
                if msg:
                    self.say(msg)

    # ======================================================= the submodes
    def prompt_key(self, key: str) -> None:
        pr = self.prompt
        if pr is None:
            return
        if key in ("\r", "\n"):
            fn = pr["fn"]
            # ENTER ON AN EMPTY LINE TAKES THE PLACEHOLDER. A prompt that
            # offers one is saying "this is what you get if you say nothing",
            # and the brackets in the panel are that sentence drawn; the
            # alternative -- prefilling the buffer -- makes typing your own
            # name start with holding backspace.
            text = pr["buf"] or pr.get("placeholder", "")
            self.prompt = None
            if not pr.get("keep_menu"):
                self.menu = None
            self.say(fn(text))
        elif key == "\x1b":
            self.prompt = None
            self._submode_cancel(pr)
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
            self._submode_cancel(cf)

    def picker_key(self, key: str) -> None:
        pk = self.picker
        if pk is None:
            return
        n = len(pk["options"])
        if key == "UP":
            pk["i"] = n - 1 if pk["i"] < 0 else (pk["i"] - 1) % n
        elif key == "DOWN":
            pk["i"] = 0 if pk["i"] < 0 else (pk["i"] + 1) % n
        elif key in PAGE_KEYS:
            # THE WHOLE PICKER IS DRAWN, always: it is a handful of options
            # in the footer panel with no viewport to scroll, so its page is
            # its length and PageDown lands where End does. With nothing
            # preselected a page key picks the end it came from, exactly as
            # the arrows do -- no row is marked until a key moves.
            pk["i"] = (page_jump(key, pk["i"], n, n) if pk["i"] >= 0
                       else (n - 1 if key in ("PGUP", "END") else 0))
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
            self._submode_cancel(pk)

    def _submode_cancel(self, sub: dict) -> None:
        """esc in a prompt, a confirm or a picker -- and what it abandons.

        THE ANSWER USED TO BE "the new-session flow", unconditionally: all
        three branches set self.ns = None, because the only multi-screen flow
        on the dashboard was that one and each of its screens WAS the flow.
        The comment on self.ns said the real fix was for a submode to carry
        its own cancel, and left it to whoever next had a flow.

        This is that: `on_cancel` in the submode's own dict. A screen that is
        one step of something larger says what leaving it means -- the
        new-session form's rows say "nothing; the form is still open behind
        you" -- and a screen that says nothing keeps exactly the old
        behaviour, which is what every caller that has not thought about it
        wants.
        """
        fn = sub.get("on_cancel")
        if fn is not None:
            msg = fn()
            if msg:
                self.say(msg)
            return
        self.ns = None
        self.say("cancelled")

    def _submode_foot(self):
        """The footer panel when a text prompt, confirm, picker or a view's
        own modal owns the keyboard -- shared by every view, so a flow works
        from whichever one started it."""
        if self.prompt is not None:
            # THE BRACKETS ARE THE OFFER. An empty line with a placeholder
            # draws it where the text would be and says what enter does with
            # it, so "press enter and get a sensible name" is legible before
            # the first key rather than something to find out afterwards.
            # The moment anything is typed the brackets go: what is on the
            # line is then what will be used.
            hold = self.prompt.get("placeholder", "") if not self.prompt["buf"] else ""
            return Panel(
                Text.assemble((self.prompt["title"] + ": ", "bold"),
                              (self.prompt["buf"], "#c9a0dc"), ("_", "bold #c9a0dc"),
                              (" [%s]" % hold if hold else "", DIM),
                              ("      enter takes what is in brackets · esc cancel"
                               if hold else "      enter save · esc cancel", DIM)),
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
    def tab_labels(self, tab) -> tuple:
        """(full, short, initial) for one tab. A view may give `tab_short`
        and `tab_initial`; one that gives neither is cut to ten characters
        and to its first letter, so a tab written before this existed still
        degrades instead of pushing the others off the strip."""
        full = tab.tab_label(self)
        short_fn = getattr(tab, "tab_short", None)
        initial_fn = getattr(tab, "tab_initial", None)
        short = short_fn(self) if short_fn else \
            (full if len(full) <= 10 else full[:9].rstrip() + "…")
        initial = initial_fn(self) if initial_fn else full[:1]
        if tab.name in self.hidden_tabs():
            # On a hidden tab, reached by its key: say so, or the strip
            # would show a tab the user believes they switched off.
            full += " (hidden)"
        return full, short, initial

    def strip_width(self) -> int:
        """Columns a panel title may use: the console less the two corners,
        the rule either side of the title and the space Rich pads it with."""
        return max(10, self.console.size.width - 6)

    def fit_strip(self, view):
        """The fitted strip (dashboard.tabstrip.Strip) for the group this
        view is in, or None when it is a screen of its own."""
        # The GROUP decides whether there is a strip, not what is shown of
        # it: a user who hid every other tab still gets the strip, with this
        # one marked hidden and the subtitle's count of the rest.
        if len(self.group_tabs(view)) < 2:
            return None
        tabs = self.tabs_of(view)
        return fit([self.tab_labels(t) for t in tabs], tabs.index(view),
                   self.strip_width())

    def tab_strip(self, view) -> str | None:
        """The strip of tabs for the group this view is in, as markup, or
        None when it is a screen of its own.

        IT COSTS NO ROWS: it is drawn as the first panel's TITLE, which is a
        line that exists anyway. That is why a tab is cheap enough to be the
        answer for the handovers list and for anything else that is a second
        table of the same kind of thing.

        IT IS FITTED TO THE WIDTH (dashboard/tabstrip.py): labels go full ->
        short -> initial before any tab leaves the strip, and then only the
        tabs past the first six scroll, with a count of what is off each
        side. ←→ walks every tab, drawn or not."""
        strip = self.fit_strip(view)
        return strip.markup if strip else None

    def build(self) -> Group:
        """One frame: the active view's sections, with the open menu placed
        among them or the footer under them."""
        view = self.view_of()
        sections = view.build(self)
        # Fitted ONCE a frame: a tab's label may scan (the handovers tab
        # counts its files), and the strip and its subtitle want one answer.
        fitted = self.fit_strip(view)
        if fitted and sections:
            # The panel is built fresh every frame, so this is a decoration
            # of this frame's copy and not a change to the view's own idea of
            # its title.
            panel = sections[0][1]
            panel.title = fitted.markup
            panel.title_align = "left"
            tabs = self.tabs_of(view)
            # Scrolled, the subtitle says WHERE in the whole set you are:
            # the strip no longer shows every tab, so it cannot.
            gone = len(self.group_tabs(view)) - len(tabs)
            panel.subtitle = "[%s]←→ tab%s%s" % (
                DIM, " %d/%d" % (tabs.index(view) + 1, len(tabs))
                if fitted.scrolled else "",
                # Hidden tabs are said where the strip is, so a user who
                # forgot hiding one can see there is more to find.
                " · %d hidden (esc ▸ Settings ▸ Tabs)" % gone if gone > 0 else "")
            panel.subtitle_align = "right"
        sub = self._submode_foot()
        if sub is not None:
            return self.place_submode(sections, view.menu_anchor(self), sub)
        if self.menu is not None:
            return self.place_menu(sections, view.menu_anchor(self))
        return Group(*[p for _n, p in sections], view.footer(self))

    # ======================================================== key routing
    def route_key(self, key: str | None) -> bool:
        """The first three steps of the one rule. True when the key was eaten.

        A SUBMODE OWNS THE KEYBOARD while it is open, and it is checked
        before every global key -- including q. Typing a window name that
        contains a "q" must not quit the dashboard, and neither must
        answering a confirm."""
        # "" IS NO KEY AT ALL: decode_key returns it for an escape
        # sequence this dashboard has no name for (F5, Insert, a mouse
        # report), and the whole point of that is that nothing acts on it.
        # It used to arrive here as "\x1b" and quit whatever view was open.
        if not key:
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
            elif key in PAGE_KEYS:
                self.menu_page(key)
            elif key in ("\r", "\n"):
                self.menu_activate()
            elif key == "\x1b":
                self.menu_esc()
            # A ROW THAT IS ALSO A FIELD. The new-session form's Create row
            # holds the name, typed into the row itself rather than into a
            # modal over the top of it -- so `c` is one screen from start to
            # finish and the layout never jumps. Checked here, AFTER esc and
            # the movers (which a field has no business stealing) and BEFORE
            # q/space, which are ordinary characters in a name and must not
            # close the menu while one is being typed.
            elif self._menu_edit(key):
                pass
            elif key in (" ", "q", "Q"):
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
        # A HIDDEN TAB'S KEY opens the first SHOWN tab of its group -- the
        # key is the way into the screen, and the user hid this tab -- or
        # the tab itself when every one of them is hidden, because a key
        # that does nothing is how data becomes unreachable.
        target = self._views[name]
        if name in self.hidden_tabs():
            shown = [v for v in self.group_tabs(target)
                     if v.name not in self.hidden_tabs()]
            if shown:
                name = shown[0].name
        if name == self.view:
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
