"""dashboard.views.budget -- `b`: how much of the account's budget is left, and
what the budget guard is doing about it.

docs/budget.md. claude-watchdog.sh judges; this draws the verdict. The daemon
writes `budget` (key <TAB> value, the shape of usage.tsv) every time it
judges the schedules, and everything on this screen is read from that file,
status.tsv, sched-why.tsv, tree.tsv and the wound ledger -- files the
daemon already keeps. NOTHING HERE FORKS: the screen is redrawn every two
seconds and a frame that forks is a frame that stutters.

    session   the ESTIMATE the guard judges by, how it was made, the reset,
              and when the window runs out at the current rate
    week      the reading, the manual resets counted as weeks spent, the
              effective figure against the pace
    windows   running / limited / queued / paused / held, each with the
              first reason the guard gave
    lanes     every window and held entry the guard has an opinion on, with
              its priority class

A VERDICT THAT IS OLD IS SAID TO BE OLD. The file is only rewritten while the
daemon is armed and judging; a stale one is drawn dim with its age, never as
the present -- the dashboard once reported "scheduled" for windows nothing
was going to open, and that is the failure this file must not repeat.
"""
from __future__ import annotations

import time

from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dashboard.app import View
from dashboard.core import (DIM, FRAME, GREEN, RED, SCHEDULES_DIR, WATCHDOG_DIR,
                            YELLOW, human_tokens, pressure)

BUDGET_FILE = WATCHDOG_DIR / "budget"
STATUS_FILE = WATCHDOG_DIR / "status.tsv"
WHY_FILE = WATCHDOG_DIR / "sched-why.tsv"
TREE_FILE = WATCHDOG_DIR / "tree.tsv"
WOUND_FILE = WATCHDOG_DIR / "wound"

# The order the guard serves classes in, and the shift it gives each line.
CLASSES = ("release", "p1", "ops", "p2")
SHIFT = {"release": 10, "p1": 0, "ops": -5, "p2": -10}
# A verdict older than this many seconds is drawn as old (the daemon judges
# every 30 s; three missed passes is a daemon that is not judging).
STALE_S = 120


def norm_prio(raw: str) -> str:
    """The same folding as claude-watchdog.sh budget_prio_norm."""
    v = (raw or "").strip().lower()
    if v in ("release", "release-gating", "release-gate", "gating", "p0"):
        return "release"
    if v in ("p2", "low"):
        return "p2"
    if v in ("ops", "op"):
        return "ops"
    return "p1"


def read_kv(path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            k, _, v = line.partition("\t")
            if k:
                out[k] = v
    except OSError:
        pass
    return out


def read_budget() -> dict[str, str]:
    """The daemon's last verdict, or {} when it has never written one."""
    return read_kv(BUDGET_FILE)


def _int(v: str, default: int | None = None) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def entry_priority(name: str) -> str:
    """`priority:` of a schedule entry file, folded; p1 when absent."""
    try:
        with open(SCHEDULES_DIR / name, encoding="utf-8") as fh:
            for line in fh:
                if line.strip() == "---":
                    break
                if line.startswith("priority: "):
                    return norm_prio(line[len("priority: "):])
    except OSError:
        pass
    return "p1"


def budget_lanes(now: float | None = None) -> list[dict]:
    """Every window and held entry the guard has an opinion on.

    From status.tsv: working -> running; limited/due -> limited, or queued
    when the wave has not reached it yet (ACTION = queued); idle and wound
    down hard for a window that has not reset -> paused. From sched-why.tsv:
    an entry the BUDGET held (not the memory guard) -> held. Each row's class
    is its entry's `priority:`, through tree.tsv for a running window.
    """
    now = time.time() if now is None else now
    src: dict[str, str] = {}
    try:
        for line in TREE_FILE.read_text().splitlines():
            p = line.split("\t")
            if len(p) >= 6:
                src[p[0]] = p[5]
    except OSError:
        pass
    paused: set[str] = set()
    try:
        for line in WOUND_FILE.read_text().splitlines():
            p = line.split("\t")
            if len(p) >= 3 and p[1] == "2" and (_int(p[2], 0) or 0) > now:
                paused.add(p[0])
    except OSError:
        pass
    rows: list[dict] = []
    try:
        lines = STATUS_FILE.read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        p = line.split("\t")
        if len(p) < 8:
            continue
        sid, name, state, acted = p[0], p[1], p[5], p[7]
        ctx = _int(p[4], 0) or 0
        slug = name.replace("➥", "")
        if state in ("working", "background"):
            what = "running"
        elif acted == "queued" or state == "queued":
            what = "queued"
        elif state in ("limited", "due", "resume-due"):
            what = "limited"
        elif state == "paused" or (state == "idle" and sid in paused):
            what = "paused"
        else:
            continue
        rows.append({"name": slug, "what": what, "ctx": ctx,
                     "prio": entry_priority(src.get(slug, "")) if src.get(slug, "").endswith(".md") else "p1",
                     "why": p[6] if what == "limited" and p[6] not in ("", "-") else ""})
    try:
        for line in WHY_FILE.read_text().splitlines():
            p = line.split("\t")
            if len(p) >= 3 and p[1] == "held" and p[2].startswith("held: budget"):
                rows.append({"name": p[0][:-3] if p[0].endswith(".md") else p[0],
                             "what": "held", "ctx": 0, "prio": entry_priority(p[0]),
                             "why": p[2][len("held: budget -- "):]})
    except OSError:
        pass
    order = {"running": 0, "queued": 1, "limited": 2, "paused": 3, "held": 4}
    rows.sort(key=lambda r: (CLASSES.index(r["prio"]), order[r["what"]], r["name"]))
    return rows


def clock(epoch: str, now: float) -> str:
    """HH:MM today, `Sat 16:59` further out; "" for nothing."""
    e = _int(epoch)
    if not e:
        return ""
    fmt = "%H:%M" if abs(e - now) < 20 * 3600 else "%a %H:%M"
    return time.strftime(fmt, time.localtime(e))


def summary(b: dict[str, str], now: float | None = None) -> list[Text]:
    """The figures, as lines of Text. Pure: a dict in, lines out, so the test
    can hold every sentence to the file it came from."""
    now = time.time() if now is None else now
    out: list[Text] = []
    if not b:
        out.append(Text("no budget verdict yet -- the watchdog writes one each pass "
                        "while it is armed (w)", style=YELLOW))
        return out
    age = now - (_int(b.get("at", ""), 0) or 0)
    on = b.get("on") == "on"
    head = Text()
    head.append("Guard ", style=DIM)
    head.append("ON" if on else "off", style=GREEN if on else YELLOW)
    head.append("  plan ", style=DIM)
    head.append(b.get("plan", "?"), style="bold")
    head.append(" (%s)" % b.get("plan_src", ""), style=DIM)
    if age > STALE_S:
        head.append("  · judged %dm ago -- the watchdog is not judging" % (age // 60), style=YELLOW)
    out.append(head)

    t = Text()
    t.append("Session ", style=DIM)
    est = _int(b.get("session_est", ""))
    if est is None:
        t.append("blind", style=YELLOW)
        t.append(" -- %s; only the cap and the waves hold" % b.get("blind", "no reading"), style=DIM)
    else:
        t.append("~%d%%" % est, style=pressure(float(est)))
        t.append(" (%s)" % b.get("session_est_src", ""), style=DIM)
        r = clock(b.get("session_reset_at", ""), now)
        if r:
            t.append(" · resets %s" % r, style=DIM)
        ex = clock(b.get("exhaust_at", ""), now)
        if ex:
            t.append(" · runs out ~%s" % ex, style="bold " + RED)
        elif _int(b.get("rate_pct_h", ""), 0):
            t.append(" · lasts to the reset", style=GREEN)
        t.append(" at %s%%/h (%s)" % (b.get("rate_pct_h", "0"), b.get("rate_src", "")), style=DIM)
    out.append(t)

    w = Text()
    w.append("Week    ", style=DIM)
    eff = _int(b.get("week_eff", ""))
    if eff is None:
        w.append("unknown", style=YELLOW)
        w.append(" -- no week reading", style=DIM)
    else:
        allowed = _int(b.get("week_allowed", ""), 0) or 0
        n = _int(b.get("manual_resets", ""), 0) or 0
        w.append("%d%% effective" % eff, style=RED if eff > allowed else GREEN)
        w.append(" (%s%% read" % b.get("week_pct", "?"), style=DIM)
        if n:
            w.append(" + %d manual reset%s, each a week spent" % (n, "" if n == 1 else "s"), style=YELLOW)
        w.append(") · the pace allows %d%% now (%s%%/day)" % (allowed, b.get("day_pct", "?")), style=DIM)
        r = clock(b.get("week_reset_at", ""), now)
        if r:
            w.append(" · resets %s" % r, style=DIM)
    out.append(w)

    c = Text()
    c.append("Windows ", style=DIM)
    for key, style in (("running", GREEN), ("limited", YELLOW), ("queued", YELLOW),
                       ("paused", YELLOW), ("held", RED)):
        n = _int(b.get(key, ""), 0) or 0
        c.append("%d %s" % (n, key), style=style if n else DIM)
        c.append("  ")
    c.append("· cap %s" % b.get("lanes", "?"), style=DIM)
    out.append(c)
    for key, label in (("held_why", "held  "), ("queued_why", "queued")):
        why = b.get(key, "")
        if why:
            out.append(Text.assemble(("  %s " % label, DIM),
                                     (why.replace("held: budget -- ", ""), YELLOW)))
    out.append(Text("Knobs   cap %s · hold %s%% · wind down %s%% · %s%%/lane-hour · start %s%% · "
                    "checkpoint %sm · %s%%/day · waves of %s per %sm · fresh above %s tokens"
                    % (b.get("lanes", "?"), b.get("hold_pct", "?"), b.get("wind_pct", "?"),
                       b.get("lane_pct", "?"), b.get("start_pct", "?"), b.get("checkpoint_min", "?"),
                       b.get("day_pct", "?"), b.get("wave", "?"), b.get("wave_min", "?"),
                       b.get("fresh_ctx", "?")), style=DIM))
    out.append(Text("Classes release +10 · p1 0 · ops -5 · p2 -10 on both lines; "
                    "`priority:` in an entry, p1 when absent", style=DIM))
    return out


def lanes_table(rows: list[dict]) -> Table:
    t = Table(box=None, expand=True, pad_edge=False, show_edge=False,
              header_style=DIM)
    t.add_column("WINDOW", no_wrap=True, ratio=3)
    t.add_column("CLASS", no_wrap=True)
    t.add_column("STATE", no_wrap=True)
    t.add_column("CONTEXT", no_wrap=True, justify="right")
    t.add_column("WHY", ratio=6, overflow="fold")
    style = {"running": GREEN, "queued": YELLOW, "limited": YELLOW,
             "paused": YELLOW, "held": RED}
    for r in rows:
        t.add_row(escape(r["name"]), r["prio"], Text(r["what"], style=style[r["what"]]),
                  human_tokens(r["ctx"]) if r["ctx"] else "-",
                  Text(r["why"], style=DIM))
    return t


HELP_BUDGET = f"""
  [{DIM}]THE BUDGET GUARD (b; esc ▸ Settings ▸ Budget)[/]
    The watchdog holds a schedule entry that is due when starting it would
    overspend the account: past a cap of working windows, past the session
    line (the hold %, moved by the entry's `priority:` -- release +10, p1,
    ops -5, p2 -10), when it could not reach a checkpoint before the budget
    runs out, or when the week is ahead of its pace. A manual weekly reset
    counts as a week already spent. Resumes after a limit go out in waves,
    release first; a window with a huge context resumes FRESH from its
    handover. `b` shows the figures it judged by and every window it has an
    opinion on. docs/budget.md has the measurement the presets came from.
"""


class BudgetView(View):
    name, key, group, order = "budget", "b", None, 35

    def __init__(self, app) -> None:
        self.app = app

    def build(self, app) -> list:
        b = read_budget()
        body = Text("\n").join(summary(b))
        title = "[bold]budget[/]"
        if b.get("held", "0") not in ("", "0"):
            title += " [%s]· %s held[/]" % (RED, b["held"])
        top = Panel(body, title=title, title_align="left", border_style=FRAME,
                    box=box.ROUNDED)
        rows = budget_lanes()
        if rows:
            low = Panel(lanes_table(rows), title="[bold]windows and entries[/] [%s]· by class" % DIM,
                        title_align="left", border_style=FRAME, box=box.ROUNDED)
        else:
            low = Panel(Text("nothing running, limited, queued, paused or held", style=DIM),
                        title="[bold]windows and entries", title_align="left",
                        border_style=FRAME, box=box.ROUNDED)
        return [("budget", top), ("lanes", low)]

    def footer(self, app) -> Text:
        return Text(" u read the usage now  esc ▸ Settings ▸ Budget the knobs  esc back  q quit",
                    style=DIM)

    def on_key(self, app, key) -> bool:
        if key == "\x1b":
            app.switch_to("main")
            return True
        return False


def footer_note(app) -> Text | None:
    """`budget: 2 held · b` in the main footer, only while it is true and
    fresh: on the ordinary day this note is not there."""
    b = read_budget()
    if not b or time.time() - (_int(b.get("at", ""), 0) or 0) > STALE_S:
        return None
    held = _int(b.get("held", ""), 0) or 0
    queued = _int(b.get("queued", ""), 0) or 0
    if not held and not queued:
        return None
    bits = []
    if held:
        bits.append("%d held" % held)
    if queued:
        bits.append("%d queued" % queued)
    return Text("  · budget: %s (b)" % ", ".join(bits), style=YELLOW)


def register(app) -> None:
    app.add_view(BudgetView(app))
    app.add_hint(footer_note)
    app.add_help("THE BUDGET GUARD", HELP_BUDGET, order=36)
