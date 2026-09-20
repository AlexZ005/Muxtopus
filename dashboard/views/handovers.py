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

import datetime
import os
import subprocess
import time

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import muxhandovers
import muxsettings
from dashboard.app import View
from dashboard.core import (DIM, FRAME, GREEN, HANDOVERS_DIR, PROFILE,
                            QUESTIONS_DIR, RED, SCRIPTS, YELLOW, human_age)
from dashboard.data import claude_sessions, lane_slug_of, live_windows, read_tree
from dashboard.menulayout import (PAGE_KEYS, menu_viewport, page_jump,
                                  rendered_height)
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

# THE TWO FILTERS, and why they are on disk rather than in memory (plan §4,
# fork Q2 as the user answered it). `R` re-execs the dashboard and the code's
# own comment says it "gets pressed a lot"; an in-memory toggle dies with
# every one of them, so a done list that came back on each R would be
# switched off once and for good. The sibling lane refused to persist the
# main view's `t` and `f` -- "nobody asked". Here somebody asked.
#
# done   governs every FINISHED thing, done handovers and answered questions
#        alike, so two switches cover four kinds of row without a third key.
DONE_KEY = "DASHBOARD_HANDOVERS_DONE"
ASKS_KEY = "DASHBOARD_HANDOVERS_QUESTIONS"

HELP_HANDOVERS = """
  [%s]HANDOVERS AND QUESTIONS (the second tab of s)[/]
    ←→          move between the schedules and the handovers
    ↑↓          pick a row; the cursor starts on what is OWED
    f           show or hide everything FINISHED -- done handovers and
                answered question files alike
    a           show or hide the question rows
    enter       on a QUESTIONS file: THE ANSWER SCREEN -- its forks one at a
                time, the options as rows with the recommended one already
                picked, and the editor one key away on every screen of it.
                Each answer is written the moment you give it, as one line at
                the end of its own fork; esc leaves and what was answered
                stays answered. On a HANDOVER: read-only, in the pager -- a
                live lane rewrites its handover whenever it likes, and an
                editor saving over that is how one is lost
    e           edit (a questions file)
    E           edit a handover ANYWAY, behind a warning when its window is
                still open and whichever of you saves last would win
    space       the row's menu: view, edit, mark done, mark answered,
                open its window, tell that window its answers are in
    r           re-read the folder
    s / esc     back to the main view

    Both filters are REMEMBERED (dashboard.conf, and the Settings menu lists
    them): R re-execs the dashboard, and a filter that reset on every R would
    be switched off once and for good. What a filter hides is always counted
    on the bottom border, so a row can be hidden but never the fact that it
    is there.

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

    ON THE MAIN VIEW, a session whose lane has an unanswered QUESTIONS file
    carries a yellow ? beside its name, and the key line says how many files
    are waiting in all. Both read the same folders this tab does, at most
    once every five seconds, so the main frame pays a glob and no fork.
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
        self.show_done = self._knob(DONE_KEY)
        self.show_questions = self._knob(ASKS_KEY)
        self._foot = None
        # THE TABLE'S PAGE, for PageUp/PageDown: the row lines build_handovers
        # measured for it this frame.
        self._page = 3
        self._body_cache: dict = {}
        self._scanned = 0.0
        self.flow: dict | None = None      # the answer screen, when it is up

    # ---------------------------------------------------------- the filters
    @staticmethod
    def _knob(key: str) -> bool:
        return muxsettings.get(key, PROFILE) == "on"

    def toggle(self, key: str, attr: str, label: str) -> str:
        """Flip one filter and WRITE IT, atomically and reread-verified
        (muxsettings.put). The screen always shows what was actually set:
        a refused write leaves the filter where it was and says why, rather
        than showing a state the next `R` would silently undo."""
        want = not getattr(self, attr)
        why = muxsettings.put(key, "on" if want else "off", PROFILE)
        if why:
            return "%s: not saved -- %s" % (label, why)
        setattr(self, attr, want)
        return "%s %s" % (label, "shown" if want else "hidden")

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

    # THE STRIP'S NARROWER NAMES (dashboard/tabstrip.py). No scan of their
    # own: App.tab_labels asks tab_label first, in the same frame, and the
    # `?` survives to the initial because an unanswered fork is the one
    # thing on this tab that is waiting on YOU.
    def tab_short(self, app) -> str:
        c = muxhandovers.counts(self.all)
        return "hand %d" % c["open"] + (" %d?" % c["unanswered"] if c["unanswered"] else "")

    def tab_initial(self, app) -> str:
        return "h?" if muxhandovers.counts(self.all)["unanswered"] else "h"

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

    def follow(self, row) -> None:
        """Keep the cursor on the row that was just acted on.

        Marking a file answered changes its STATE, and the order is BY state,
        so the row moves -- and the cursor, which is an index, would stay
        where it was and end up on somebody else. That matters here more than
        it looks: the row you just changed is the one you might want to change
        back, and the menu is built from whatever is under the cursor."""
        if row is None:
            return
        for i, r in enumerate(self.rows):
            if r["path"] == row["path"]:
                self.i = i
                return

    def move(self, delta: int) -> None:
        if self.rows:
            self.i = max(0, min(len(self.rows) - 1, self.i + delta))

    def page(self, key: str) -> None:
        """PageUp/PageDown/Home/End in the rows table, clamped at both ends.

        THE PAGE KEYS DO NOT SCROLL THE DETAIL PANEL, which is the one body
        on this screen: that panel shows the SELECTED row's head and is
        re-read every frame, and the whole file goes to `less` on enter --
        which pages it with these very keys. Two pagers on one screen, one of
        them silent about which it is, is the bug this key is fixing."""
        j = page_jump(key, self.i, len(self.rows), self._page)
        if j is not None:
            self.i = j

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
        # THE TABLE AT ITS FLOOR AND STILL NO ROOM: the detail panel gives
        # the lines up, from its bottom (Panel(height=) crops), rather than
        # the frame growing past the terminal and Live cropping the FOOTER
        # instead -- found by prove.sh at 24x60, where the question text
        # wraps. `e` still opens the whole file.
        short = 3 - (height - below - chrome)
        if short > 0:
            detail.height = max(3, rendered_height(console, detail) - short)

        n = len(self.rows)
        self._page = max(1, budget)
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
        # EVERY column no_wrap: the viewport below counts one line per row,
        # and at 40 columns "? ask" wrapped onto two and the footer went.
        t.add_column("", width=3, no_wrap=True)
        t.add_column("STATE", width=8, overflow="ellipsis", no_wrap=True)
        t.add_column("AGE", width=5, overflow="ellipsis", no_wrap=True)
        t.add_column("LANE", width=24, overflow="ellipsis", no_wrap=True)
        t.add_column("WINDOW", width=8, overflow="ellipsis", no_wrap=True)
        t.add_column("HOLDS", width=6, overflow="ellipsis", no_wrap=True)
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
        # WHILE THE ANSWER SCREEN IS UP it shows the fork being answered, so
        # the panel above the options is the question they belong to. Off the
        # flow, it is the first one still owed.
        fork = next((f for f in forks if not f["answer"]), forks[0])
        if (self.flow and self.flow["path"] == row["path"]
                and self.flow["i"] >= 0
                and self.flow["i"] < len(self.flow["forks"])):
            fork = self.flow["forks"][self.flow["i"]]
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
            (" ↑↓", DIM), " pick  ", ("pgup/dn home/end", DIM), " jump  ",
            ("←→", DIM), " tab  ",
            ("enter", DIM), " open/answer  ", ("e", DIM), " edit  ",
            ("E", DIM), " force-edit  ", ("space", DIM), " menu  ",
            ("f", DIM), " done  ", ("a", DIM), " asks  ",
            ("r", DIM), " reload  ",
            ("s", DIM), "/", ("esc", DIM), " back  ", ("q", DIM), " quit",
        )
        if self.app.notice and time.time() - self.app.notice_at < 8:
            keys = Text.assemble((" " + self.app.notice, "#c9a0dc"), "\n", keys)
        return keys

    # ------------------------------------------------------------ opening
    def open_selected(self) -> None:
        """enter. A QUESTIONS file opens the ANSWER SCREEN; a STATUS file
        opens READ-ONLY.

        The read-only half is fork Q5 as the user answered it, and it is not
        fussiness: a live lane rewrites its handover whenever it likes, and
        nano saving over that is exactly how a handover is lost. It goes
        through the shell's pending_report, which pipes text to less -- so
        there is nothing for the editor to save back even if it wanted to.
        """
        row = self.sel()
        if row is None:
            self.app.say("nothing to open")
            return
        if row["kind"] == "questions":
            self.app.say(self.start_answering(row))
            return
        try:
            text = row["path"].read_text(errors="replace")
        except OSError as exc:
            self.app.say("cannot read %s: %s" % (row["path"].name, exc))
            return
        self.app.pending_report = "%s\n\n%s" % (row["path"], text)

    def edit_selected(self) -> None:
        """e. The file, in the editor -- and on a STATUS row it says no and
        names the key that means it."""
        row = self.sel()
        if row is None:
            self.app.say("nothing to edit")
        elif row["kind"] == "questions":
            self.app.pending_edit = str(row["path"])
        else:
            self.app.say("a handover opens read-only — E edits it anyway")

    def live_window(self, slug: str):
        """The lane's window id if it is open right now, else ""."""
        node = read_tree().get(slug)
        if node and node["wid"] in live_windows():
            return node["wid"]
        return ""

    def force_edit(self) -> str:
        """E, and the menu's `Edit anyway…`. A confirm ONLY when something
        could be writing the file: for a lane whose window is gone there is
        nothing to race, and a warning nobody needs is a warning nobody
        reads."""
        row = self.sel()
        if row is None:
            return "nothing to edit"
        if row["kind"] == "questions":
            self.app.pending_edit = str(row["path"])
            return ""
        wid = self.live_window(row["slug"])
        if not wid:
            self.app.pending_edit = str(row["path"])
            return ""
        self.app.confirm = {
            "label": "⚠ ➥%s may rewrite this file while you edit; "
                     "whichever saves last wins." % row["slug"],
            "fn": lambda: self._do_edit(row)}
        return ""

    def _do_edit(self, row) -> str:
        self.app.pending_edit = str(row["path"])
        return ""


    # ================================================= answering a fork (§3b)
    # Seeing "awaiting your answers" with no way to answer is half a feature.
    # This is the other half: the forks of one file, one at a time, with its
    # options as rows -- and the EDITOR one key away on every screen of it,
    # because no parser will understand every lane's prose and the file is
    # always the escape hatch.
    #
    # It is a VIEW'S OWN MODAL (app.modal), not the shared picker, for exactly
    # that reason: the picker answers UP/DOWN/enter/esc and drops everything
    # else, so `e` could only have been another row to arrow onto. A modal
    # owns the keyboard, and it is the mechanism the options table already
    # uses -- App routes keys to its `key` and draws the footer with its
    # `panel` and knows nothing else about it. A prompt opened FOR it (the
    # note on an answer) still takes the keys while it is up, which is the
    # documented order.
    def start_answering(self, row) -> str:
        try:
            st = row["path"].stat()
            text = row["path"].read_text(errors="replace")
        except OSError as exc:
            return "cannot read %s: %s" % (row["path"].name, exc)
        forks = muxhandovers.parse_forks(text)
        if not forks:
            self.app.pending_edit = str(row["path"])
            return "no forks could be read in %s — opening it" % row["path"].name
        self.flow = {"row": row, "path": row["path"], "forks": forks,
                     "at": (st.st_mtime, st.st_size), "i": 0, "cur": 0}
        self._to_next_unanswered(first=True)
        self.app.modal = {"key": self.flow_key, "panel": self.flow_panel}
        return ""

    def _to_next_unanswered(self, first: bool = False) -> None:
        f = self.flow
        start = f["i"] if first else f["i"] + 1
        for i in range(start, len(f["forks"])):
            if not f["forks"][i]["answer"]:
                f["i"], f["cur"] = i, self._preselect(f["forks"][i])
                return
        # Nothing left unanswered from here on: wrap once, so a file whose
        # first forks were answered by the lane still offers the later ones.
        for i in range(0, len(f["forks"])):
            if not f["forks"][i]["answer"]:
                f["i"], f["cur"] = i, self._preselect(f["forks"][i])
                return
        f["i"], f["cur"] = -1, 0          # the done screen

    @staticmethod
    def _preselect(fork) -> int:
        """The recommended option, preselected -- that is what RECOMMENDED is
        for, and the lane wrote it down so the reader would not have to."""
        for i, o in enumerate(fork["options"]):
            if o["rec"]:
                return i
        return 0

    def flow_rows(self) -> list[dict]:
        f = self.flow
        if f["i"] < 0:
            rows = [{"label": "Mark the file answered", "act": self.flow_mark}]
            if self.live_window(f["row"]["slug"]):
                rows.append({"label": "Tell ➥%s its answers are in"
                                      % f["row"]["slug"], "act": self.flow_tell})
            rows.append({"label": "Open the file in the editor", "act": self.flow_edit})
            rows.append({"label": "Close", "act": self.flow_close})
            return rows
        fork = f["forks"][f["i"]]
        rows = [{"label": "(%s) %s" % (o["key"], o["text"]), "opt": o,
                 "rec": o["rec"]} for o in fork["options"]]
        if not rows:
            # A fork with no options the parser could see. Accepting it "as
            # written" is still an answer, and it is the one the lane asked
            # for when it wrote its own recommendation into the prose.
            rows = [{"label": "accept it as written / as recommended",
                     "opt": {"key": "", "text": "as written", "rec": True},
                     "rec": True}]
        rows += [{"label": "type an answer…", "typed": True},
                 {"label": "skip this fork", "skip": True},
                 {"label": "open the file in the editor  (e)", "edit": True}]
        return rows

    def flow_panel(self):
        f = self.flow
        rows = self.flow_rows()
        body = Text()
        if f["i"] < 0:
            body.append("every fork in this file is answered\n", style=GREEN)
        else:
            fork = f["forks"][f["i"]]
            n = sum(1 for k in f["forks"] if k["answer"])
            body.append("fork %d of %d · %d answered\n"
                        % (f["i"] + 1, len(f["forks"]), n), style=DIM)
            body.append(fork["title"] + "\n", style="bold")
        for i, r in enumerate(rows):
            cur = (i == f["cur"])
            body.append(" ▸ " if cur else "   ", style="bold #c9a0dc")
            body.append(r["label"], style="bold" if cur else "")
            if r.get("rec"):
                body.append("   ← recommended", style=GREEN)
            body.append("\n")
        # THE NOTICE HAS TO LIVE HERE. A modal owns the footer, which is
        # where a notice is normally drawn -- the same hole the menus and the
        # options table each had -- so "answered: (a)" and "the lane rewrote
        # the file" would be said to nobody while this screen is the screen.
        hint = "↑↓ pick · enter answer · e the file · esc leave"
        if self.app.showing_notice():
            hint = "%s   ·   %s" % (self.app.notice, hint)
        else:
            hint += "   (what is answered stays answered)"
        body.append("   " + hint, style=DIM)
        return Panel(body, title="[bold]answer[/] [%s]· %s" % (DIM, f["path"].name),
                     title_align="left", border_style="#c9a0dc", box=box.ROUNDED)

    def flow_key(self, key: str) -> None:
        f = self.flow
        rows = self.flow_rows()
        if key == "UP":
            f["cur"] = (f["cur"] - 1) % len(rows)
        elif key == "DOWN":
            f["cur"] = (f["cur"] + 1) % len(rows)
        elif key in PAGE_KEYS:
            # The answer screen draws every option, so its page is its
            # length: PageDown is End here, and Home is the first answer.
            f["cur"] = page_jump(key, f["cur"], len(rows), len(rows))
        elif key == "e":
            self.flow_edit()
        elif key == "\x1b":
            self.flow_close()
        elif key in ("\r", "\n"):
            self.flow_activate(rows[f["cur"]])

    def flow_activate(self, row: dict) -> None:
        if row.get("act"):
            msg = row["act"]()
            if msg:
                self.app.say(msg)
            return
        if row.get("edit"):
            self.flow_edit()
        elif row.get("skip"):
            self._to_next_unanswered()
        elif row.get("typed"):
            self.app.prompt = {"title": "your answer", "buf": "",
                               "keep_menu": True, "fn": self._typed}
        else:
            # A CHOSEN OPTION MAY TAKE A NOTE, and enter with nothing typed
            # means no note: the letter alone is a complete answer, and being
            # made to explain it would be a reason not to answer at all.
            opt = row["opt"]
            self.app.prompt = {
                "title": "(%s) — a note, or enter for none" % opt["key"],
                "buf": "", "keep_menu": True,
                "fn": lambda note: self._answer(opt, note)}

    def _typed(self, text: str) -> str:
        if not text.strip():
            return "nothing typed — the fork is still open"
        return self._answer(None, text)

    def _answer(self, opt, note: str) -> str:
        f = self.flow
        if f is None:
            return ""
        fork = f["forks"][f["i"]]
        note = note.strip()
        if opt is None:
            answer = note
        elif opt["key"]:
            answer = "(%s)%s" % (opt["key"], " — " + note if note else "")
        else:
            answer = "as recommended%s" % (" — " + note if note else "")
        msg = self._write_answer(fork["id"], answer)
        self._to_next_unanswered()
        return msg

    def _write_answer(self, fork_id: str, answer: str) -> str:
        """One fork, written AT ONCE, atomically, and only onto the file that
        was parsed.

        A live lane rewrites its QUESTIONS file whenever it likes. If it did
        so since this screen opened, the answer is re-applied to the same
        FORK ID in the new text -- which is why the id is a function of the
        fork's title and not of its position -- and the screen says so."""
        f = self.flow
        path = f["path"]
        note = ""
        try:
            st = path.stat()
            text = path.read_text(errors="replace")
        except OSError as exc:
            return "cannot read %s: %s" % (path.name, exc)
        if (st.st_mtime, st.st_size) != f["at"]:
            note = " (the lane rewrote the file; re-applied to the same fork)"
        try:
            new = muxhandovers.write_answer(
                text, fork_id, answer, datetime.date.today().isoformat())
        except KeyError:
            return "that fork is not in the file any more — nothing written"
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(new)
            os.replace(tmp, path)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            return "could not write %s: %s" % (path, exc)
        try:
            st = path.stat()
            f["at"] = (st.st_mtime, st.st_size)
        except OSError:
            pass
        f["forks"] = muxhandovers.parse_forks(new)
        self.cache.clear()
        self.scan(force=True)
        return "answered: %s%s" % (answer, note)

    def flow_edit(self) -> str:
        self.app.pending_edit = str(self.flow["path"])
        self.flow_close()
        return ""

    def flow_mark(self) -> str:
        row = self.flow["row"]
        self.flow_close()
        for i, r in enumerate(self.rows):
            if r["path"] == row["path"]:
                self.i = i
                break
        return self.mark_answered()

    def flow_tell(self) -> str:
        row = self.flow["row"]
        for i, r in enumerate(self.rows):
            if r["path"] == row["path"]:
                self.i = i
                break
        self.flow_close()
        return self.ask_tell()

    def flow_close(self) -> str:
        self.flow = None
        self.app.modal = None
        return ""

    # ------------------------------------------------------- the state changes
    def handover_sh(self, *args: str) -> str:
        """EVERY state change shells out to handover.sh, so never-clobber and
        the ANSWERED marker have one implementation and not two. The legacy
        questions folder is the one exception -- that script does not own it
        -- and muxhandovers writes the marker there instead."""
        cmd = [str(SCRIPTS / "handover.sh")]
        if PROFILE:
            cmd += ["--profile", PROFILE]
        cmd += list(args)
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            return "handover.sh failed: %s" % exc
        was = self.sel()
        self.cache.clear()
        self.scan(force=True)
        self.follow(was)
        msg = (out.stdout + out.stderr).strip().splitlines()
        return msg[-1] if msg else "handover.sh %s" % " ".join(args)

    def ask_mark_done(self) -> str:
        """Mark done…, and THE CONFIRM NAMES WHAT IT RELEASES. Marking a
        handover done from a menu is launching every entry held `after:` this
        lane within 30 seconds, and a confirm that does not say so is asking
        the wrong question."""
        row = self.sel()
        if row is None:
            return "nothing selected"
        waiting = self.holds().get(row["slug"], [])
        label = "Mark %s done?" % row["slug"]
        if waiting:
            label += "  releases: %s" % ", ".join(waiting)
        self.app.confirm = {"label": label,
                            "fn": lambda: self.handover_sh("done", row["slug"])}
        return ""

    def mark_answered(self) -> str:
        """The ANSWERED marker. handover.sh owns the handovers folder; the
        legacy folder is nobody's, so muxhandovers writes it there directly
        -- atomically, and only if the file has not changed underneath."""
        row = self.sel()
        if row is None or row["kind"] != "questions":
            return "not a questions file"
        if not row["legacy"]:
            return self.handover_sh("answered", row["slug"])
        return self._legacy_marker(row, mark=True)

    def mark_unanswered(self) -> str:
        row = self.sel()
        if row is None or row["kind"] != "questions":
            return "not a questions file"
        if not row["legacy"]:
            return self.handover_sh("unanswer", row["slug"])
        return self._legacy_marker(row, mark=False)

    def _legacy_marker(self, row, mark: bool) -> str:
        import datetime
        import os
        path = row["path"]
        try:
            before = path.stat()
            text = path.read_text(errors="replace")
        except OSError as exc:
            return "cannot read %s: %s" % (path.name, exc)
        if mark:
            new = muxhandovers.mark_answered(
                text, datetime.date.today().isoformat())
        else:
            new = "\n".join(l for l in text.splitlines()
                             if not muxhandovers.ANSWERED_RE.match(l))
            new += "\n" if text.endswith("\n") else ""
        if new == text:
            return "%s was already %s" % (path.name,
                                          "answered" if mark else "unanswered")
        tmp = path.with_name(path.name + ".tmp")
        try:
            if path.stat().st_mtime != before.st_mtime:
                return "%s changed underneath — not written" % path.name
            tmp.write_text(new)
            os.replace(tmp, path)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            return "could not write %s: %s" % (path, exc)
        was = self.sel()
        self.cache.clear()
        self.scan(force=True)
        self.follow(was)
        return "%s: %s (legacy folder)" % (
            path.name, "answered" if mark else "marker removed")

    def ask_tell(self) -> str:
        """Tell ➥slug its answers are in. THE ONLY THING ON THIS TAB THAT
        TOUCHES A LIVE WINDOW, and it is never automatic: a confirm first,
        and it types one sentence into that pane and nothing else."""
        row = self.sel()
        if row is None:
            return "nothing selected"
        node = read_tree().get(row["slug"])
        pane = node["pane"] if node else ""
        if not pane or not self.live_window(row["slug"]):
            return "➥%s has no live pane" % row["slug"]
        line = ("Your questions are answered in %s -- read it and continue."
                % row["path"])
        self.app.confirm = {
            "label": "Type that into ➥%s's pane?" % row["slug"],
            "fn": lambda: self._send(pane, line)}
        return ""

    def _send(self, pane: str, text: str) -> str:
        try:
            subprocess.run(["tmux", "send-keys", "-t", pane, text],
                           capture_output=True, timeout=5)
            time.sleep(0.6)
            subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"],
                           capture_output=True, timeout=5)
            return "told ➥%s" % pane
        except (OSError, subprocess.SubprocessError) as exc:
            return "send failed: %s" % exc

    def goto_handover(self) -> str:
        """Show its handover -- the cursor moves to that lane's STATUS row,
        rather than opening anything. A question and the handover that asked
        it are two rows of one list, and this is the shortest way to say so."""
        row = self.sel()
        if row is None:
            return "nothing selected"
        for i, r in enumerate(self.rows):
            if r["kind"] == "status" and r["slug"] == row["slug"]:
                self.i = i
                return ""
        return "no handover row for %s — f shows the finished ones" % row["slug"]

    def goto_window(self) -> str:
        """Open its window: the tmux window the lane ran in, if it is still
        there. The schedule view's row for the same thing, reused in shape."""
        row = self.sel()
        if row is None:
            return "nothing selected"
        wid = self.live_window(row["slug"])
        if not wid:
            return "➥%s has no live window" % row["slug"]
        try:
            subprocess.run(["tmux", "select-window", "-t", wid],
                           capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            return "could not switch: %s" % exc
        return "switched to %s" % wid

    # ---------------------------------------------------------- the menu
    def menu_entries(self) -> list[dict]:
        """Built from the SELECTED ROW and nothing else, every frame, so a
        row that changes state while the menu is open offers what is true
        now rather than what was true when space was pressed."""
        row = self.sel()
        if row is None:
            return [{"label": "nothing selected", "disabled": "no rows"}]
        wid = self.live_window(row["slug"])
        if row["kind"] == "questions":
            rows = [{"label": "Answer…", "act": self._act_answer},
                    {"label": "Edit the file", "act": self._act_edit}]
            if row["state"] == "unanswered":
                rows.append({"label": "Mark answered", "act": self.mark_answered})
            else:
                rows.append({"label": "Mark unanswered", "act": self.mark_unanswered})
            rows.append({"label": "Tell ➥%s its answers are in" % row["slug"],
                         "act": self.ask_tell} if wid else
                        {"label": "Tell its window", "disabled": "no live window"})
            rows.append({"label": "Show its handover", "act": self.goto_handover})
            return rows
        rows = [{"label": "View (read-only)", "act": self._act_view},
                {"label": "Edit anyway…", "act": self.force_edit, "danger": True}]
        if wid:
            rows.append({"label": "Open its window ➥%s" % row["slug"],
                         "act": self.goto_window})
        if row["state"] == "open":
            rows.append({"label": "Mark done…", "act": self.ask_mark_done})
        elif not row["stamp"]:
            # handover.sh reopen takes the unstamped name only, so a row it
            # could not act on is shown as unavailable rather than offered
            # and then refused.
            rows.append({"label": "Reopen",
                         "act": lambda: self.handover_sh("reopen", row["slug"])})
        else:
            rows.append({"label": "Reopen",
                         "disabled": "an earlier run's stamped file"})
        return rows

    def _act_view(self) -> str:
        self.open_selected()
        return ""

    def _act_answer(self) -> str:
        return self.start_answering(self.sel())

    def _act_edit(self) -> str:
        self.app.pending_edit = str(self.sel()["path"])
        return ""

    def menu_title(self) -> str:
        row = self.sel()
        return "handover[/] [%s]· %s" % (DIM, row["path"].name) if row else "handover"

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
        elif key in PAGE_KEYS:
            self.page(key)
        elif key == "r":
            self.cache.clear()
            self._body_cache.clear()
            self.scan(force=True)
            self.app.say("handovers re-read")
        elif key in ("s", "\x1b"):
            self.app.switch_to("main")
        elif key in ("\r", "\n"):
            self.open_selected()
        elif key == "e":
            self.edit_selected()
        elif key == "E":
            self.force_edit()
        elif key == " ":
            self.app.open_menu("handover")
        elif key == "f":
            self.app.say(self.toggle(DONE_KEY, "show_done", "finished rows"))
        elif key == "a":
            self.app.say(self.toggle(ASKS_KEY, "show_questions", "question rows"))
        elif key in ("c", "o", "l", "d"):
            self.app.say("%s: schedules tab only — ← goes back to it" % key)
        elif key == "t":
            # The tree keys belong to the sessions table, as on the schedules
            # tab; swallowed so they cannot fold a row nobody can see.
            pass
        else:
            return False
        return True


# ===================================== the main view, in one character (§6)
# The most actionable fact on this dashboard should not need a view switch to
# be seen. A session whose lane has an unanswered QUESTIONS file gets a yellow
# `?` beside its name, and the main footer says how many files are waiting.
#
# BOTH OF THESE RUN ON THE MAIN FRAME, which is measured in forks per second
# (2) and milliseconds (12.9), and a badge runs once per session per frame.
# So they read muxhandovers.asking(), which globs two folders and tests the
# marker at most every 5 seconds and caches the rest. No fork, and the same
# definition of "unanswered" the tab uses -- not a second one that could
# disagree with the row it is meant to point at.
def lane_badge(app, session):
    slug = lane_slug_of(session.window)
    if slug and slug in muxhandovers.asking(HANDOVERS_DIR, QUESTIONS_DIR):
        return Text("?", style="bold " + YELLOW)
    return None


def asks_hint(app):
    n = len(muxhandovers.asking(HANDOVERS_DIR, QUESTIONS_DIR))
    return Text("  · %d ?" % n, style=YELLOW) if n else None


def register(app) -> None:
    # THE SETTINGS FIRST: the view reads its filters out of the store as it
    # is built, and muxsettings.get asserts the key is a declared one.
    muxsettings.register({
        DONE_KEY: {
            "label": "Handovers: show finished rows", "kind": "onoff",
            "hint": "done handovers and answered question files (f on the tab)"},
        ASKS_KEY: {
            "label": "Handovers: show question rows", "kind": "onoff",
            "hint": "QUESTIONS files, answered and not (a on the tab)"},
    })
    view = HandoversView(app)
    app.add_view(view)
    app.add_menu("handover", view.menu_entries, title_fn=view.menu_title)
    app.add_badge(lane_badge, order=10)
    app.add_hint(asks_hint)
    app.add_help("HANDOVERS AND QUESTIONS (the second tab of s)",
                 HELP_HANDOVERS, order=52)
