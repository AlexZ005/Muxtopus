"""dashboard.views.handovers -- the `s` screen's second tab.

One lifecycle, one place. A schedule entry launches a window, the window
writes a handover, the handover asks questions, the questions are answered,
the lane is marked done -- and the `s` view already drew the first half of
that and the WHY line already read the second. This is the rest of it, as a
TAB of the same screen rather than a key of its own: `group = "s"` is all it
takes, the shell draws the strip in the panel title (which costs no rows) and
←→ cycles between them.

WHAT IT READS THAT IS NOT ITS OWN, all of it through the seam:

    muxhandovers            the rows, the states and the summariser
    dashboard.data          read_tree, live_windows, claude_sessions
    dashboard.schedules     read_schedules, for HOLDS
    dashboard.core          the palette and the two folders

and nothing at all from another view. The strip, the ←→ and the placing of
an open menu are the App's; this file draws two panels and answers keys.

THE COUNTS ARE ON THE STRIP, not in the table, because that is the whole
reason a tab strip earns its line: from the schedules tab you can still see
that three question files are waiting on you.
"""
from __future__ import annotations

import time

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import muxhandovers
from dashboard.app import View
from dashboard.core import (DIM, FRAME, GREEN, HANDOVERS_DIR,
                            QUESTIONS_DIR, RED, YELLOW, human_age)
from dashboard.data import claude_sessions, lane_slug_of, live_windows, read_tree
from dashboard.menulayout import menu_viewport, rendered_height
from dashboard.schedules import read_schedules

# How a row's state is drawn. Same shape as core.STATES -- name: (label,
# style) -- but these are handover states, not watchdog session states, so
# they are this module's and not a registration into that table.
ROW_STATES = {
    "unanswered": ("? ask", "bold " + YELLOW),
    "answered": ("? done", DIM),
    "open": ("open", ""),
    "done": ("done", DIM),
}
# The detail panel shows this much of the body, and the table gets the rest.
BODY_MIN, BODY_MAX = 3, 10
# HOW OFTEN THE FOLDER IS RE-GLOBBED. The strip's count has to be true while
# the OTHER tab is the one being drawn -- that is the entire argument for
# spending a line on a strip -- so tab_label scans too, and this is what
# stops it costing a glob per frame per tab. The file contents are cached by
# (mtime, size) on top of this; only the directory listing is repeated.
SCAN_EVERY = 1.0

HELP_HANDOVERS = """
  [%s]HANDOVERS AND QUESTIONS (the second tab of s)[/]
    ←→          move between the schedules and the handovers
    ↑↓          pick a row; the cursor starts on what is OWED
    r           re-read the folder
    s / esc     back to the main view

    The rows are every STATUS and QUESTIONS file of this account, in both
    folders, ordered by what is owed: unanswered questions first, then open
    handovers, then everything finished.

    STATE   ? ask   a QUESTIONS file with no ANSWERED marker line
            ? done  one that has been marked answered
            open    a handover whose lane has not been marked done
            open ⚠  red: the watchdog calls that window stranded
                    yellow: a done/ twin of this file ALREADY satisfies
                    every `after: <slug>` -- the lane ran, was marked done,
                    and is running again
    WINDOW  the window the lane was launched in, ● while it is still open
    HOLDS   how many PENDING schedule entries are waiting on this lane
""" % DIM


class HandoversView(View):
    """A tab of the `s` screen. Its own state is the cursor, the filters and
    a (mtime, size) cache; everything else it draws is read fresh."""

    name, key, group, order = "handovers", None, "s", 40

    def __init__(self, app) -> None:
        self.app = app
        self.i = 0
        self.rows: list[dict] = []          # what is drawn, after the filters
        self.all: list[dict] = []           # everything, for the counts
        # FILES ARE RE-READ ONLY WHEN (mtime, size) CHANGED. The folder is
        # scanned every frame and 30-odd files would otherwise be read twice a
        # second to draw one line each.
        self.cache: dict = {}
        self.show_done = False
        self.show_questions = True
        self._foot = None
        self._body_cache: dict = {}
        self._scanned = 0.0

    # ------------------------------------------------------ the protocol
    def tab_label(self, app) -> str:
        """`handovers 4 open · 3 ?` -- and the `3 ?` is why the strip is
        worth its line: it is legible from the schedules tab, whatever the
        filters over here are hiding.

        IT SCANS. The strip is drawn by the App for every tab in the group,
        including the ones whose build() is not running, so a label that used
        only what build() last collected read `handovers 0 open` from the
        schedules tab -- which is worse than no count at all, because it is a
        number and it is wrong."""
        self.scan()
        c = muxhandovers.counts(self.all)
        label = "handovers %d open" % c["open"]
        if c["unanswered"]:
            label += " · %d ?" % c["unanswered"]
        return label

    def build(self, app) -> list:
        return self.build_handovers()

    def footer(self, app):
        return self._foot

    def menu_anchor(self, app) -> int:
        return 0

    def on_key(self, app, key) -> bool:
        return self.handover_key(key)

    # THERE IS NO on_open THAT RESETS THE CURSOR, deliberately. The cursor
    # starts at 0 -- the actionable end, which is what the order is for -- and
    # then it is the USER's: ←→ is how you check the schedules while reading a
    # handover, and coming back to the top row every time would make that
    # trip cost your place. scan() clamps it when rows come and go.

    # ------------------------------------------------------------ the rows
    def scan(self, force: bool = False) -> None:
        """The rows, re-globbed at most once a second, then filtered.

        The FILTERS are applied every call whatever the throttle says: they
        change on a keypress and the next frame has to show it."""
        now = time.time()
        if force or not self._scanned or now - self._scanned >= SCAN_EVERY:
            self.all = muxhandovers.scan(HANDOVERS_DIR, QUESTIONS_DIR, self.cache)
            self._scanned = now
        self.rows = muxhandovers.visible(self.all, self.show_done,
                                         self.show_questions)
        self.i = max(0, min(self.i, len(self.rows) - 1)) if self.rows else 0

    def sel(self):
        if 0 <= self.i < len(self.rows):
            return self.rows[self.i]
        return None

    def move(self, delta: int) -> None:
        if self.rows:
            self.i = max(0, min(len(self.rows) - 1, self.i + delta))

    def body(self, row: dict) -> list[str]:
        """The file's lines under its title, cached the way the rows are."""
        key = str(row["path"])
        hit = self._body_cache.get(key)
        if hit and hit[0] == row["mtime"]:
            return hit[1]
        try:
            lines = row["path"].read_text(errors="replace").splitlines()
        except OSError as exc:
            lines = ["cannot read: %s" % exc]
        self._body_cache[key] = (row["mtime"], lines)
        return lines

    # ------------------------------------- what the lifecycle says about it
    def holds(self) -> dict[str, list[str]]:
        """slug -> the PENDING entries waiting on it.

        `after:` is READ here and never reinterpreted: the split is the
        executor's own (commas or spaces, as sched_after_deps does it), and
        what this adds is only the other direction -- who is waiting for
        whom, which the entry knows and the lane never did."""
        out: dict[str, list[str]] = {}
        for entry in read_schedules():
            if entry["status"] != "pending" or entry["bad"]:
                continue
            for dep in entry["after"].replace(",", " ").split():
                out.setdefault(dep, []).append(
                    entry["resolved"] or entry["file"].stem)
        return out

    def stranded(self) -> set[str]:
        """The lanes the watchdog calls stranded -- a fact about the FUTURE
        (nothing is ever going to touch that window again), which is why it
        is worth a colour on a handover that is still open."""
        sessions, _age = claude_sessions()
        return {lane_slug_of(s.window) for s in sessions if s.state == "stranded"}

    def window_of(self, row: dict, tree: dict, live: set) -> Text:
        node = tree.get(row["slug"])
        if not node:
            # The tree never knew this slug: a hand-named lane, or one from
            # before the tree existed. Not an error, and not worth a warning.
            return Text("—", style=DIM)
        if node["wid"] in live:
            return Text.assemble((node["wid"], ""), (" ●", GREEN))
        return Text("exited", style=DIM)

    def state_of(self, row: dict, stranded: set) -> Text:
        label, style = ROW_STATES.get(row["state"], (row["state"], DIM))
        if row["kind"] == "status" and row["state"] == "open":
            if row["slug"] in stranded:
                return Text.assemble((label, style), (" ⚠", "bold " + RED))
            if row["shadowed"]:
                # THE TRAP THIS TAB EXISTS TO SHOW. A done/ twin from an
                # earlier run satisfies every `after: <slug>` right now,
                # while this file says the work is not finished.
                return Text.assemble((label, style), (" ⚠", "bold " + YELLOW))
        return Text(label, style=style)

    # --------------------------------------------------------- the drawing
    def build_handovers(self) -> list:
        self.scan()
        console = self.app.console
        height = console.size.height
        tree, live = read_tree(), live_windows()
        holds, stranded = self.holds(), self.stranded()

        detail = self.detail_panel(tree, live, holds)
        self._foot = self.foot()
        # MEASURE, do not count: what is left for the table is the height
        # minus what Rich will really draw for the panels around it, and
        # minus the table's own chrome -- which is itself measured, by
        # drawing the empty table once.
        below = rendered_height(console, Group(detail, self._foot))
        # The empty table, drawn: two borders, the header and its rule. Three
        # rows is the floor -- under it menu_viewport has no window to give,
        # and a terminal that short has bigger problems than this tab.
        chrome = rendered_height(console, self.table_panel(self.table(), ""))
        budget = max(3, height - below - chrome)

        n = len(self.rows)
        if n <= budget:
            top, up, down = 0, False, False
            span = n
        else:
            # The same arithmetic the menus scroll with, so there is not a
            # second scrolling implementation on this screen. menu_viewport
            # thinks in whole-panel rows (two borders and a hint), hence the
            # +3: the budget here is item lines, which is what it returns.
            top, up, down = menu_viewport(n, self.i, budget + 3)
            span = budget - up - down

        table = self.table()
        # THE MARKER GOES IN THE LANE COLUMN, which is 24 wide and never
        # wraps. In the 8-wide STATE column "▼ 25 more" wrapped onto a second
        # line -- and a scroll marker that is sometimes two lines tall is a
        # frame that is sometimes one line too tall, which on a 24-row
        # terminal cost the FOOTER. Measured, on the screen this whole
        # viewport exists for.
        if up:
            table.add_row("", "", "", Text("▲ %d more" % top, style=DIM),
                          "", "", "")
        for i in range(top, min(top + span, n)):
            self.add_row(table, self.rows[i], i == self.i, tree, live,
                         holds, stranded)
        if down:
            table.add_row("", "", "",
                          Text("▼ %d more" % (n - top - span), style=DIM),
                          "", "", "")
        if not self.rows:
            table.add_row("", Text("—", style=DIM), "",
                          Text(self.empty_reason(), style=DIM), "", "", "")

        # THE HIDDEN COUNT IS ON THE DETAIL PANEL, not on the table's bottom
        # border where plan §3 drew it: the shell owns the FIRST panel's
        # title and subtitle for a view that is part of a tab group (it puts
        # the strip in one and `←→ tab` in the other), so anything this view
        # writes there is overwritten every frame. The bottom border of the
        # detail panel is the bottom of the screen, which is where the eye
        # was going to look for it anyway.
        detail.subtitle = self.subtitle()
        detail.subtitle_align = "right"
        return [("handovers", self.table_panel(table, "")),
                ("detail", detail)]

    def table(self) -> Table:
        t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                  header_style=DIM, border_style=FRAME)
        t.add_column("", width=3)
        t.add_column("STATE", width=8)
        t.add_column("AGE", width=5)
        t.add_column("LANE", width=24, overflow="ellipsis", no_wrap=True)
        t.add_column("WINDOW", width=8)
        t.add_column("HOLDS", width=6)
        t.add_column("SAID", ratio=1, overflow="ellipsis", no_wrap=True)
        return t

    def table_panel(self, table, subtitle: str) -> Panel:
        p = Panel(table, title="[bold]handovers[/] "
                  f"[{DIM}]· {HANDOVERS_DIR}",
                  title_align="left", border_style=FRAME, box=box.ROUNDED)
        if subtitle:
            p.subtitle = subtitle
            p.subtitle_align = "right"
        return p

    def add_row(self, table, row: dict, cur: bool, tree, live, holds, stranded):
        mark = Text("▸" if cur else " ", style="bold #c9a0dc")
        waiting = holds.get(row["slug"], [])
        lane = Text(row["slug"])
        if row["legacy"]:
            lane = Text.assemble((row["slug"], ""), (" ·legacy", DIM))
        elif row["stamp"]:
            lane = Text.assemble((row["slug"], ""), (" ·earlier", DIM))
        said = Text(row["said"], style=RED if row["error"] else "")
        table.add_row(mark, self.state_of(row, stranded),
                      Text(human_age(time.time() - row["mtime"]), style=DIM),
                      lane, self.window_of(row, tree, live),
                      Text(str(len(waiting)) if waiting else "—",
                           style=YELLOW if waiting else DIM),
                      said)

    def subtitle(self) -> str:
        """WHAT THE FILTERS ARE HIDING, always. A filter may hide a row; it
        may never hide the fact that the row exists."""
        h = muxhandovers.hidden(self.all, self.show_done, self.show_questions)
        bits = []
        if h["done"]:
            bits.append("done hidden: %d" % h["done"])
        if not self.show_questions and h["questions"]:
            bits.append("questions hidden: %d" % h["questions"])
        return "[%s]%s" % (DIM, " · ".join(bits)) if bits else ""

    def empty_reason(self) -> str:
        if self.all:
            return "every row is filtered away — %d hidden" % len(self.all)
        return "no handovers yet — a lane writes one with handover.sh write"

    # ------------------------------------------------------- the detail panel
    def detail_panel(self, tree, live, holds) -> Panel:
        row = self.sel()
        if row is None:
            return Panel(Text("nothing selected", style=DIM),
                         border_style=FRAME, box=box.ROUNDED)
        body = Text()
        body.append(str(row["path"]) + "\n", style=DIM)
        if row["error"]:
            body.append("cannot read this file: %s" % row["error"], style=RED)
            return Panel(body, title="[bold]detail", title_align="left",
                         border_style=FRAME, box=box.ROUNDED)
        if row["kind"] == "questions":
            self._questions_detail(body, row)
        else:
            self._status_detail(body, row)
        self._lifecycle(body, row, tree, live, holds)
        return Panel(body, title="[bold]detail", title_align="left",
                     border_style=FRAME, box=box.ROUNDED)

    def _status_detail(self, body: Text, row: dict) -> None:
        if row["title"]:
            body.append(row["title"] + "\n", style="bold")
        lines = self.body(row)
        shown = 0
        for line in lines[1:]:
            if shown >= BODY_MAX:
                break
            if not line.strip() and shown < BODY_MIN:
                continue
            body.append(line.rstrip()[:160] + "\n")
            shown += 1

    def _questions_detail(self, body: Text, row: dict) -> None:
        """The FIRST FORK, in full -- which is the one thing a person looking
        at an unanswered questions file wants, and the thing the old panel
        (a list of filenames) could not say."""
        forks = muxhandovers.parse_forks("\n".join(self.body(row)))
        body.append("%d fork%s\n" % (row["forks"], "" if row["forks"] == 1 else "s"),
                    style=DIM)
        if not forks:
            body.append(row["title"] or "(no forks could be read)")
            return
        fork = next((f for f in forks if not f["answer"]), forks[0])
        body.append(fork["title"] + "\n", style="bold")
        for line in fork["text"].splitlines()[1:BODY_MAX]:
            body.append(line.rstrip()[:160] + "\n")
        if fork["answer"]:
            body.append("every fork is answered\n", style=GREEN)

    def _lifecycle(self, body: Text, row: dict, tree, live, holds) -> None:
        """Where the lane ran, what launched it, and who is waiting on it --
        the three facts the handover file itself never carries."""
        node = tree.get(row["slug"])
        bits = []
        if node:
            alive = node["wid"] in live
            bits.append(("window %s %s" % (node["wid"], "open" if alive else "exited"),
                         GREEN if alive else DIM))
            if node["parent"]:
                bits.append(("parent %s" % node["parent"], DIM))
            if node["file"]:
                bits.append(("launched from %s" % node["file"], DIM))
        if row["shadowed"]:
            bits.append(("⚠ done/STATUS-%s.md from an earlier run already "
                         "satisfies every `after: %s`" % (row["slug"], row["slug"]),
                         YELLOW))
        if row["stamp"]:
            bits.append(("earlier run, %s" % row["stamp"], DIM))
        if row["legacy"]:
            bits.append(("in the legacy folder %s" % QUESTIONS_DIR, DIM))
        waiting = holds.get(row["slug"], [])
        if waiting:
            bits.append(("holds: %s (after:)" % ", ".join(waiting), YELLOW))
        if not bits:
            return
        body.append("\n")
        for i, (text, style) in enumerate(bits):
            if i:
                body.append("  ·  ", style=DIM)
            body.append(text, style=style)

    def foot(self) -> Text:
        keys = Text.assemble(
            (" ↑↓", DIM), " pick  ", ("←→", DIM), " tab  ",
            ("r", DIM), " reload  ",
            ("s", DIM), "/", ("esc", DIM), " back  ", ("q", DIM), " quit",
        )
        if self.app.notice and time.time() - self.app.notice_at < 8:
            keys = Text.assemble((" " + self.app.notice, "#c9a0dc"), "\n", keys)
        return keys

    # --------------------------------------------------------------- keys
    def handover_key(self, key: str) -> bool:
        """This tab's keys.

        c, o, l and d SAY THEY ARE NOT THIS TAB'S rather than falling through
        to the schedules view, which is the tab beside this one and would
        otherwise act on a row nobody can see -- the same bug class the
        schedule view's own `space` case fixed after the split.
        """
        if key == "UP":
            self.move(-1)
        elif key == "DOWN":
            self.move(1)
        elif key == "r":
            self.cache.clear()
            self._body_cache.clear()
            self.scan(force=True)
            self.app.say("handovers re-read")
        elif key in ("s", "\x1b"):
            self.app.switch_to("main")
        elif key in ("c", "o", "l", "d"):
            self.app.say("%s: schedules tab only — ← goes back to it" % key)
        elif key == "t":
            # The tree keys belong to the sessions table, as on the schedules
            # tab; swallowed so they cannot fold a row nobody can see.
            pass
        else:
            return False
        return True


def register(app) -> None:
    view = HandoversView(app)
    app.add_view(view)
    app.add_help("HANDOVERS AND QUESTIONS (the second tab of s)",
                 HELP_HANDOVERS, order=52)
