"""dashboard.views.insights -- the `i` screen: what was used, from the ledger.

Every figure on this screen is computed by `muxstats.query`, which is a pure
function of ledger rows and has its own unit tests. This module DRAWS one --
it owns a cursor, a period, a filter, a group-by and a drill stack, and
nothing else. That division is the reason the same numbers can be printed by
`muxtopus stats`, sent by the Telegram bot and drawn here without three
spellings of "average session peak" drifting apart.

COUNTS ONLY. The ledger behind this screen holds numbers, model ids, tool
names, session ids and working directories -- no prompt, no reply, no tool
input, ever (muxstats' docstring, and the README paragraph this view is
pointed at by `?`). `muxtopus stats --forget` is the off switch.

COLLECTING IS NOT DRAWING. `collect` reads transcript bytes and can take
seconds on the first backfill, and this is a 2-second frame: it runs on a
daemon thread, the title says so while it runs, and the ledger is re-read on
the frame after it finishes. A collector that fails leaves the ledger as it
is and says why -- a stale report beats no report, which is the same choice
the CLI makes.

WHAT IT REGISTERS
    add_view      the `i` screen (group None: a screen of its own)
    add_rows      "Insights ▸" in the esc menu, at order 45 -- under the two
                  switches and above the separator. NOT at the top: the route
                  arrows down from Settings to Watchdog, and a row in between
                  would make that press toggle something else.
    add_help      its slice of `?`, at 52

THE `f` KEY. It filters this view, and the shell also has an `f` that filters
the main view's lanes table. The routing rule (docs/dashboard-views.md) gives
the active view's on_key the key before the shell's own list, so `f` here is
this view's and `f` on the main view is still the lanes filter. That is the
answer the split's handover asked the third view to settle, arrived at
without editing the shell; the recommendation to move the shell's `f` into
views/main.py is in QUESTIONS-insights-dash.md.
"""
from __future__ import annotations

import threading
import time

from rich import box
from rich.console import Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import muxstats
from dashboard.app import View
from dashboard.core import (DIM, FRAME, GREEN, HANDOVERS_DIR, HOME, PROFILE,
                            PROFILE_LABEL, RED, SCHEDULES_DIR, YELLOW,
                            mux_home)
from dashboard.menulayout import (CHROME, MENU_MIN, PAGE_KEYS,
                                  menu_viewport, page_jump,
                                  rendered_height)

# How far `enter` goes, and it stops where a filter cannot follow. A breakdown
# key is only a filter if muxstats.FILTER_KEYS holds its dimension, so a day,
# a week or a month is a leaf: there is no --day to pin it with, and drilling
# into one would silently show the unfiltered period again.
DRILL = {"project": "session", "model": "session", "lane": "session",
         "side": "project", "session": "day"}

# What `f` offers, and the ledger column each answer filters on. `session` is
# deliberately absent: a session id is not something a hand picks off a list,
# and `enter` on a session row is how you get there.
FILTER_DIMS = (("project", "project"), ("model", "model"), ("lane", "lane"),
               ("main / subagent", "side"))
ANY = "(any — clear this filter)"

# The ledger is re-read this often while the screen is open, so the watchdog's
# five-minute collect shows up without anybody pressing r.
RELOAD_AFTER = 20.0


class InsightsView(View):
    """The `i` screen. Its own state is the question being asked -- period,
    filter, grouping, drill depth and the cursor -- and a cached answer."""

    name, key, group, order = "insights", "i", None, 30

    def __init__(self, app) -> None:
        self.app = app
        self.period = "week"
        self.group_by = "project"
        self.filters: dict[str, list] = {}
        self.all_accounts = False
        self.cur = 0
        # THE BREAKDOWN'S PAGE, for PageUp/PageDown: the row lines
        # breakdown_panel measured for it this frame.
        self._page = 3
        # (filters, group_by, cursor) per level of `enter`, so backspace puts
        # the screen back exactly where it was rather than guessing a parent.
        self.stack: list[tuple] = []
        self._ledger = None
        self._prices = None
        self._loaded_at = 0.0
        self._rep = None
        self._rep_key = None
        self._collecting = False
        self._collect_msg: str | None = None

    # ------------------------------------------------------ the protocol
    def build(self, app) -> list:
        return self.build_insights()

    def footer(self, app):
        return self._foot

    def menu_anchor(self, app) -> int:
        return 0

    def on_open(self, app) -> None:
        """Opening the screen collects, because the answer should be about
        now and not about whenever the daemon last ran."""
        self.start_collect()

    def on_key(self, app, key) -> bool:
        return self.insights_key(key)

    # ------------------------------------------------------- the ledger
    def stats_dirs(self) -> list:
        """This account's stats dir, or every account's -- which is all `a`
        is: sessions are distinct per account, so the rows concatenate."""
        base = muxstats.stats_dir(PROFILE)
        if not self.all_accounts:
            return [base]
        try:
            dirs = sorted(p for p in base.parent.glob("stats*") if p.is_dir())
        except OSError:
            dirs = []
        return dirs or [base]

    def account_label(self) -> str:
        if not self.all_accounts:
            return PROFILE_LABEL
        return "%d account(s)" % len(self.stats_dirs())

    def load(self) -> None:
        self._ledger = muxstats.load(self.stats_dirs())
        self._prices = muxstats.prices(muxstats.prices_path())
        self._loaded_at = time.time()
        self._rep_key = None

    def report(self) -> dict:
        """The current question's answer, recomputed when the question or the
        ledger changes and not once per frame: `query` walks every row several
        times, and the frame runs every two seconds whether or not a key was
        pressed."""
        if self._ledger is None or time.time() - self._loaded_at > RELOAD_AFTER:
            self.load()
        key = (self.period, self.group_by, self.all_accounts, self._loaded_at,
               tuple(sorted((k, tuple(v)) for k, v in self.filters.items())))
        if key != self._rep_key or self._rep is None:
            self._rep = muxstats.query(self._ledger, self.period, self.filters,
                                       self.group_by, None, self._prices)
            self._rep["prices_errors"] = self._prices.errors if self._prices else []
            self._rep_key = key
        return self._rep

    def invalidate(self) -> None:
        self._rep_key = None

    # ------------------------------------------------------- collecting
    def start_collect(self) -> str:
        """Read what is new into the ledger, on a thread. The frame must not
        wait for a first backfill of eighty transcripts."""
        if self._collecting:
            return "already collecting"
        self._collecting = True
        threading.Thread(target=self._collect_run, daemon=True,
                         name="muxstats-collect").start()
        return ""

    def _collect_run(self) -> None:
        try:
            rep = muxstats.collect(
                # The PROFILE, never CLAUDE_CONFIG_DIR as a path: a work
                # session's environment would otherwise feed the work
                # transcripts into whichever ledger this dashboard owns.
                muxstats.config_dir_of(PROFILE), muxstats.stats_dir(PROFILE),
                wd_dir=muxstats.watchdog_dir(PROFILE),
                schedules_dir=SCHEDULES_DIR, handovers_dir=HANDOVERS_DIR)
            self._collect_msg = ("collected: %d new request(s), %d ledger row(s)"
                                 % (rep.requests, rep.rows))
        except Exception as exc:                                # noqa: BLE001
            # A collector that fails must not empty the screen: the ledger on
            # disk is still the truth about every day before this one.
            self._collect_msg = ("collect failed (%s: %s) — showing the ledger "
                                 "as it is" % (type(exc).__name__, exc))
        finally:
            # Not `self._ledger = None`: build() may be reading it right now.
            # An old timestamp simply makes the next frame re-read.
            self._loaded_at = 0.0
            self._collecting = False

    # ------------------------------------------------------------ keys
    def insights_key(self, key: str) -> bool:
        if key == "LEFT":
            self.cycle_period(-1)
        elif key == "RIGHT":
            self.cycle_period(1)
        elif key == "UP":
            self.move(-1)
        elif key == "DOWN":
            self.move(1)
        elif key in PAGE_KEYS:
            self.page(key)
        elif key == "g":
            self.cycle_group(1)
        elif key == "G":
            self.cycle_group(-1)
        elif key in ("\r", "\n"):
            self.app.say(self.drill())
        elif key in ("\x7f", "\b"):
            self.app.say(self.climb() or "at the top — esc goes back")
        elif key == "f":
            self.ask_filter()
        elif key == "F":
            self.filters = {}
            self.stack = []
            self.cur = 0
            self.invalidate()
            self.app.say("filters cleared")
        elif key == "a":
            self.all_accounts = not self.all_accounts
            self._loaded_at = 0.0
            self.app.say("all accounts" if self.all_accounts
                         else "this account (%s)" % PROFILE_LABEL)
        elif key == "e":
            self.app.say(self.export())
        elif key == "r":
            # Re-read the ledger AND the price file at once, rather than only
            # when the collector finishes: r is "show me what is there now",
            # and an edited prices.md should land on the next frame whether or
            # not there are new transcript bytes to read.
            self._loaded_at = 0.0
            self.app.say(self.start_collect() or "collecting…")
        elif key == "\x1b":
            # esc climbs one drill level first: the same "back, then out"
            # esc means in a submenu and in the options table.
            if not self.climb():
                self.app.switch_to("main")
        elif key == "i":
            self.app.switch_to("main")
        elif key == "t":
            pass        # the tree keys belong to the sessions table
        else:
            return False
        return True

    def cycle_period(self, delta: int) -> None:
        i = muxstats.PERIODS.index(self.period)
        self.period = muxstats.PERIODS[(i + delta) % len(muxstats.PERIODS)]
        self.cur = 0
        self.invalidate()

    def cycle_group(self, delta: int) -> None:
        i = muxstats.GROUPS.index(self.group_by)
        self.group_by = muxstats.GROUPS[(i + delta) % len(muxstats.GROUPS)]
        self.cur = 0
        self.invalidate()

    def move(self, delta: int) -> None:
        n = len(self.report()["breakdown"])
        if n:
            self.cur = max(0, min(n - 1, self.cur + delta))

    def page(self, key: str) -> None:
        """PageUp/PageDown/Home/End down the breakdown, clamped at both ends.

        End on a ledger grouped by session is the one that earns its keep:
        that list is hundreds of rows long and holding ↓ down was the only
        way to the bottom of it."""
        n = len(self.report()["breakdown"])
        j = page_jump(key, self.cur, n, self._page)
        if j is not None:
            self.cur = j

    def selected(self) -> dict | None:
        bd = self.report()["breakdown"]
        if 0 <= self.cur < len(bd):
            return bd[self.cur]
        return None

    # ----------------------------------------------------- drill / climb
    def drill(self) -> str:
        """enter: pin the row under the cursor as a filter and regroup by
        whatever is one level down -- a project by its sessions, a session by
        its days."""
        rep = self.report()
        g = rep["group_by"]
        nxt = DRILL.get(g)
        if nxt is None:
            return "%s is as deep as it goes — g regroups" % g
        row = self.selected()
        if row is None:
            return "nothing to drill into"
        key = row["key"]
        if not key:
            return "that row has no %s to filter on" % g
        self.stack.append((dict(self.filters), self.group_by, self.cur))
        self.filters = dict(self.filters)
        self.filters[g] = [key]
        self.group_by = nxt
        self.cur = 0
        self.invalidate()
        return "%s %s — by %s" % (g, key if g != "session" else key[:8], nxt)

    def climb(self) -> str:
        """backspace / esc: exactly back where `enter` came from."""
        if not self.stack:
            return ""
        self.filters, self.group_by, self.cur = self.stack.pop()
        self.invalidate()
        return "back to by %s" % self.group_by

    # ---------------------------------------------------------- filters
    def ask_filter(self) -> None:
        """`f`, step one: which dimension. Step two is its values, so a
        filter is two presses and never a typed string."""
        self.app.picker = {
            "title": "filter by", "i": 0,
            "options": [lbl for lbl, _k in FILTER_DIMS],
            "fn": self._filter_dim}

    def _filter_dim(self, choice: str) -> str:
        dim = dict(FILTER_DIMS).get(choice)
        if dim is None:
            return ""
        values = self.filter_values(dim)
        if not values:
            return "no %s in the ledger yet" % dim
        self.app.picker = {"title": "filter · " + dim, "i": 0,
                           "options": [ANY] + values,
                           "fn": lambda c, d=dim: self._filter_value(d, c)}
        return ""

    def filter_values(self, dim: str) -> list[str]:
        """What the LEDGER holds for that dimension, biggest first -- not a
        fixed list, so a filter can never offer something that would show an
        empty screen."""
        if self._ledger is None:
            self.load()
        tot: dict[str, int] = {}
        for r in self._ledger.rows:
            v = ("sub" if r["side"] else "main") if dim == "side" else r.get(dim, "")
            if not v:
                continue
            tot[v] = tot.get(v, 0) + r["in"] + r["out"] + r["cache_read"] \
                + r["cache_w5m"] + r["cache_w1h"]
        return [k for k, _v in sorted(tot.items(), key=lambda kv: (-kv[1], kv[0]))]

    def _filter_value(self, dim: str, choice: str) -> str:
        self.filters = dict(self.filters)
        if choice == ANY:
            self.filters.pop(dim, None)
            msg = "%s filter cleared" % dim
        else:
            self.filters[dim] = [choice]
            msg = "%s %s" % (dim, choice)
        # A filter chosen by hand is a new question, not a step of the drill
        # that got here: keeping the stack would make backspace restore a
        # filter the hand just replaced.
        self.stack = []
        self.cur = 0
        self.invalidate()
        return msg

    # ----------------------------------------------------------- export
    def export(self) -> str:
        """`e`: this exact screen as .md, .csv and .json beside each other.

        All three rather than a fourth picker: they are small, they are the
        same report, and which one is wanted depends on where it is going --
        a spreadsheet, a handover, or another program."""
        rep = self.report()
        out = mux_home(PROFILE) / "exports"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = "insights-%s-by-%s-%s" % (self.period, self.group_by, stamp)
        try:
            out.mkdir(parents=True, exist_ok=True)
            for ext, text in (("md", muxstats.to_md(rep)),
                              ("csv", muxstats.to_csv(rep)),
                              ("json", muxstats.to_json(rep))):
                (out / (base + "." + ext)).write_text(text)
        except OSError as exc:
            return "export failed: %s" % exc
        return "exported %s.{md,csv,json} to %s" % (base, str(out).replace(str(HOME), "~"))

    # ------------------------------------------------------------ frame
    def title_markup(self, rep: dict) -> str:
        """`insights · ◂ this week ▸ · all projects · all models — collecting
        since <date>`, which is the plan's own mock. The period sits between
        the arrows that change it, so the key is on the screen rather than
        only in the footer."""
        f = rep["filters"]
        bits = ["[bold]insights[/]",
                "[%s]◂[/] [bold]%s[/] [%s]▸[/]" % (DIM, rep["period"]["label"], DIM)]
        bits.append(_filter_bit(f, "project", "all projects"))
        bits.append(_filter_bit(f, "model", "all models"))
        if f.get("lane"):
            bits.append(_filter_bit(f, "lane", ""))
        if f.get("side"):
            bits.append("[%s]%s[/]" % (YELLOW, escape(", ".join(
                {"main": "main only", "sub": "subagents only"}.get(s, s)
                for s in f["side"]))))
        if f.get("session"):
            bits.append("[%s]session %s[/]"
                        % (YELLOW, escape(", ".join(s[:8] for s in f["session"]))))
        if self.all_accounts:
            bits.append("[%s]%s[/]" % (GREEN, escape(self.account_label())))
        head = ("[%s] · [/]" % DIM).join(bits)
        # THE SINCE-DATE NEVER LEAVES. "collecting since <date>" is what makes
        # a sparse screen honest (plan-insights §2), so a collect in flight
        # adds a chip in front of it rather than replacing it.
        busy = ("[%s]collecting…[/] " % GREEN) if self._collecting else ""
        return "%s [%s]── [/]%s[%s]collecting since %s[/]" % (
            head, DIM, busy, DIM, escape(rep["since"] or "—"))

    def figures_panel(self, rep: dict) -> Panel:
        """The eight rows, ONE Text EACH -- not a two-column table.

        A grid whose value column is no_wrap measures its minimum as the whole
        untruncated line, so on a long period ("all", where the TOKENS row
        gains the coarse-days figure) Rich squeezed the fixed LABEL column
        instead and drew "TOK…". One Text per line cannot be squeezed: it is
        ellipsised at the right edge, where the figures that did not fit are,
        and the panel is exactly eight lines tall whatever the period."""
        return Panel(Group(*[_figure_line(row, text)
                             for row, text in muxstats.figure_lines(rep)]),
                     title=self.title_markup(rep), title_align="left",
                     border_style=FRAME, box=box.ROUNDED)

    def breakdown_panel(self, rep: dict, rows: int) -> Panel:
        """The one table under the figures, scrolled to the cursor.

        `rows` is the whole panel's height. The window is measured the way a
        menu's is -- menulayout.menu_viewport, the same centred-cursor rule --
        so a long list behaves here exactly as it does under space."""
        cells = muxstats._breakdown_cells(rep)
        g = rep["group_by"]
        t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                  header_style=DIM, border_style=FRAME)
        t.add_column("", width=2)
        t.add_column(g.upper(), ratio=1, overflow="ellipsis", no_wrap=True)
        for col in muxstats.BREAKDOWN_COLS:
            t.add_column(col, justify="right", width=max(7, len(col)))
        if not cells:
            t.add_row("", Text(_empty_line(rep, self._ledger), style=DIM),
                      *[""] * len(muxstats.BREAKDOWN_COLS))
        else:
            self.cur = max(0, min(self.cur, len(cells) - 1))
            # SIX lines of chrome, counted off a real capture rather than
            # guessed: two panel borders, and box.SIMPLE_HEAD's blank line,
            # header, rule and trailing blank line. At four the frame was two
            # lines too tall and Live cropped the footer off the bottom.
            budget = max(3, rows - 6)
            self._page = budget
            top, up, down = menu_viewport(len(cells), self.cur, budget + CHROME)
            span = budget - up - down
            if up:
                t.add_row("", Text("▲ %d more" % top, style=DIM),
                          *[""] * len(muxstats.BREAKDOWN_COLS))
            for i in range(top, min(top + span, len(cells))):
                c = cells[i]
                mark = Text("▸" if i == self.cur else " ", style="bold #c9a0dc")
                t.add_row(mark, Text(c[0], style="bold" if i == self.cur else ""),
                          *[Text(v) for v in c[1:]])
            if down:
                left = len(cells) - top - span
                t.add_row("", Text("▼ %d more" % left, style=DIM),
                          *[""] * len(muxstats.BREAKDOWN_COLS))
        note = []
        if any(b["unpriced"] and b["usd"] is not None for b in rep["breakdown"]):
            note.append("* part of that group has no price")
        for e in rep.get("prices_errors") or []:
            note.append("prices.md: " + e)
        sub = ("[%s]%s" % (DIM, escape(" · ".join(note)))) if note else None
        return Panel(t, title="[bold]by %s[/] [%s]· g regroups · enter drills in"
                              % (g, DIM),
                     title_align="left", subtitle=sub, subtitle_align="left",
                     border_style=FRAME, box=box.ROUNDED)

    def build_insights(self) -> list:
        if self._collect_msg is not None:
            msg, self._collect_msg = self._collect_msg, None
            self.app.say(msg)
        rep = self.report()
        head = self.figures_panel(rep)

        keys = Text.assemble(
            (" ←→", DIM), " period  ", ("↑↓", DIM), " pick  ",
            ("enter", DIM), " drill  ", ("⌫", DIM), " up  ",
            ("g", DIM), " group  ", ("f", DIM), " filter  ", ("F", DIM), " clear  ",
            ("a", DIM), " accounts  ", ("e", DIM), " export  ",
            ("r", DIM), " collect  ", ("i", DIM), "/", ("esc", DIM), " back  ",
            ("q", DIM), " quit",
        )
        foot_lines = 1
        if self.app.showing_notice():
            keys = Text.assemble((" " + self.app.notice, "#c9a0dc"), "\n", keys)
            foot_lines = 2
        self._foot = keys

        # THE TABLE GETS WHAT IS LEFT, measured rather than guessed: the
        # figures block is eight lines today and the next figure added to
        # muxstats makes it nine, which would silently push the table's last
        # row off a 24-row terminal. THE NOTICE IS COUNTED TOO -- it makes the
        # footer two lines, and a budget that forgot it would clip the frame
        # by exactly one line for the eight seconds a message is up, which is
        # the one moment the screen is being read.
        height = self.app.console.size.height
        used = rendered_height(self.app.console, head)
        room = max(MENU_MIN, height - used - foot_lines)
        body = self.breakdown_panel(rep, room)
        return [("insights", head), ("breakdown", body)]

    # ---------------------------- the row this view puts in the esc menu
    def mux_rows(self, app) -> list[dict]:
        return [{"label": "Insights ▸  tokens, cache, cost, context, sessions, "
                          "budget, lanes, rhythm  (i)",
                 "act": self.act_open}]

    def act_open(self) -> str:
        self.app.switch_to("insights")
        return ""


def _filter_bit(filters: dict, key: str, unset: str) -> str:
    vals = filters.get(key)
    if not vals:
        return "[%s]%s[/]" % (DIM, unset)
    return "[%s]%s %s[/]" % (YELLOW, key, escape(", ".join(vals)))


def _figure_line(row: str, text: str) -> Text:
    """One figure row, label and all. The thin-data markers and the no-price
    notes are the only parts styled, because they are the only parts that are
    not a figure: a reader has to be able to tell "— needs 7 days" from a
    number at a glance, and everything else on the line is a number."""
    out = Text(no_wrap=True, overflow="ellipsis")
    out.append(row.ljust(8) + " ", style=DIM)
    for i, part in enumerate(text.split(" · ")):
        if i:
            out.append(" · ", style=FRAME)
        if "needs" in part:
            out.append(part, style=YELLOW)
        elif part.startswith("—") or "no price" in part:
            out.append(part, style=DIM)
        else:
            out.append(part)
    return out


def _empty_line(rep: dict, ledger) -> str:
    """Day one, and the two ways to arrive at an empty table -- they want
    different sentences, because one of them is not a problem."""
    if ledger is not None and not ledger.rows:
        return ("nothing collected yet — r collects now, and the watchdog "
                "collects every five minutes")
    return "nothing in this period — ←→ tries another one"


# ------------------------------------------------------------------ help
HELP_INSIGHTS = f"""
  [{DIM}]INSIGHTS (i)[/]
    What was used, from muxtopus' own ledger -- which outlives the transcripts
    it was read from, because Claude Code deletes those after 30 days. Eight
    rows of figures (tokens, cache, API-equivalent cost, context, sessions,
    budget, lanes, rhythm) and one breakdown table under them.

    COUNTS ONLY. The ledger holds numbers, model ids, tool names, session ids
    and working directories. No prompt, no reply and no tool input is ever
    read into it, nothing is uploaded, and `muxtopus stats --forget
    [--before DATE]` deletes what is there and stops it being counted again.

    ←→ period (today · this week · last 7 d · this month · last 30 d · all) ·
    g/G the grouping · ↑↓ the table · enter drills in (a project into its
    sessions, a session into its days) · backspace climbs back out · f filter
    (project, model, lane, main/subagent) and F clears it · a merges every
    account's ledger · e exports this screen as .md, .csv and .json · r
    collects now · i or esc goes back.

    A figure that needs a distribution -- a median, "vs previous", the month
    projection -- says [{YELLOW}]— needs 7 days[/] until the ledger has them, and days
    backfilled coarsely from Claude Code's own cache count toward totals only.
    The $ figures are [{YELLOW}]API-equivalent[/]: what the same tokens would cost on
    the API at the list prices in ~/.config/muxtopus/prices.md (the date they
    were copied is in that file, and shown beside the figures). A subscription
    paid none of it, and a model the file does not name shows [{RED}]no price[/]
    rather than a guess -- edit the file, it is yours and install.sh never
    rewrites it.

    The same report on the command line: `muxtopus stats -h`.
"""


def register(app) -> None:
    view = InsightsView(app)
    app.add_view(view)
    # 45: under Watchdog and Monitor, above the separator. A row nearer the
    # top would sit between Settings and Watchdog, where the goldens' route
    # arrows down -- a new row must not change what an old keypress does.
    app.add_rows("mux", view.mux_rows, order=45)
    app.add_help("INSIGHTS (i)", HELP_INSIGHTS, order=52)
