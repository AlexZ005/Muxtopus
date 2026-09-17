#!/usr/bin/env python3
"""menulayout -- the viewport maths, and the panel's exact height, rendered.

Run it:  .venv/bin/python tests/test_menulayout.py     (no pytest; needs rich)

WHY RENDER and not only test menu_viewport: the dashboard's promise is that a
menu is never clipped, and that is a property of what Rich DRAWS -- a label
that wraps, a title that grows a line, a marker drawn on top of the budget
would all pass a maths-only test and still push the border off the screen.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402

import menulayout  # noqa: E402
from menulayout import (MENU_MIN, menu_needed, menu_panel,  # noqa: E402
                        menu_viewport, rendered_height)

# The session menu with both global switches off, shaped as
# Dashboard.menu_entries() builds it. The plan (§0.3) counts it as 11 entries,
# 2 separators and 2 "off globally" lines; the last two rows before the
# separator stand in for the entries that bring today's 9 up to that count.
W = "➥➥dash-menus-settings-with-a-long-name"
SESSION = [
    {"key": "wd_win", "label": "Restart %s after a limit: YES" % W, "on": True},
    {"key": "mon_win", "label": "Wind %s down near the limit: no, never interrupted" % W,
     "on": False},
    {"sep": True},
    {"label": "Open %s" % W},
    {"label": "Rename %s" % W},
    {"label": "Wind down %s now  ask it to checkpoint and stop" % W},
    {"label": "Resume %s now  tell it to continue" % W},
    {"label": "Continue %s at low priority  spends the WEEKLY budget" % W},
    {"label": "Schedule ➥resume of %s at the next reset  reads its STATUS file" % W},
    {"label": "Open the STATUS file of %s" % W, "disabled": "background session, no window"},
    {"label": "Copy the handover path of %s" % W},
    {"sep": True},
    {"label": "Close %s  kills the claude session in it" % W, "danger": True},
    {"label": "watchdog is off globally  (w turns it on)", "disabled": "global"},
    {"label": "monitoring is off globally  (m turns it on)", "disabled": "global"},
]

WHY = ("blocked: waits for dash-menus-settings to finish, whose handover says "
       "phase 2 is half done and its tree has dirty files.")
assert len(WHY) == 120, len(WHY)
F = "work-20260917-101500-dash-menus-layout-engine.md"
SCHEDULE = [
    {"label": WHY, "disabled": "why"},
    {"label": "Edit %s" % F},
    {"label": "Options %s" % F, "disabled": "only a pending entry"},
    {"label": "Launch now", "disabled": "only a pending entry"},
    {"label": "Duplicate as a new pending entry"},
    {"label": "Check: resolve it and show the report"},
    {"label": "Open its window ➥dash-menus-layout-engine"},
    {"sep": True},
    {"label": "Delete %s" % F, "danger": True},
]
assert len(SESSION) == 15 and len(SCHEDULE) == 9

fails = []
count = 0
mark = 0


def check(cond, what, quiet=False):
    global count
    count += 1
    if not cond:
        fails.append(what)
        print("  FAIL " + what)
    elif not quiet:
        print("  ok   " + what)


def section(what):
    """A summary line for a loop of quiet checks, true to what they found."""
    global mark
    print(("  ok   " if len(fails) == mark else "  FAIL ") + what)
    mark = len(fails)


def selectable(items):
    return [i for i, it in enumerate(items) if not it.get("sep") and not it.get("disabled")]


def cursors(items):
    """First, middle and last item the cursor can actually land on."""
    sel = selectable(items)
    return sorted({sel[0], min(sel, key=lambda i: abs(i - len(items) // 2)), sel[-1]})


def render(items, cur, rows, width):
    con = Console(width=width, height=rows, force_terminal=True,
                  color_system="truecolor")
    lines = con.render_lines(menu_panel(items, cur, "menu · " + W, rows), con.options)
    return ["".join(seg.text for seg in line) for line in lines]


def main():
    # -- the maths, exhaustively: every length, height and cursor --------------
    for n in range(0, 40):
        for rows in range(MENU_MIN, 45):
            for cur in range(max(n, 1)):
                top, up, down = menu_viewport(n, cur, rows)
                span = rows - 3 - up - down
                tag = "n=%d rows=%d cur=%d" % (n, rows, cur)
                check(span >= 1, tag + ": at least one item line", quiet=True)
                check(up == (top > 0), tag + ": ▲ iff items above", quiet=True)
                check(down == (top + span < n), tag + ": ▼ iff items below", quiet=True)
                if n:
                    check(top <= cur < top + span, tag + ": cursor in the window", quiet=True)
                check(top + span <= n or (top == 0 and not up and not down),
                      tag + ": the window never runs past the end", quiet=True)
                if n + 3 <= rows:
                    check((top, up, down) == (0, False, False),
                          tag + ": fits, no scrolling", quiet=True)
    section("menu_viewport: every n in 0..39, rows in 6..44, cursor")

    # Scrolling is smooth: once it scrolls, one step of the cursor moves the
    # cursor's screen line by at most one.
    for n in range(8, 40):
        for rows in range(MENU_MIN, n + 3):
            prev = None
            for cur in range(n):
                top, up, _ = menu_viewport(n, cur, rows)
                line = up + cur - top
                if prev is not None:
                    check(abs(line - prev) <= 1, "n=%d rows=%d cur=%d: no jump" % (n, rows, cur),
                          quiet=True)
                prev = line
    section("the cursor's screen line never jumps by more than one")

    check(menu_viewport(15, 14, 45) == (0, False, False), "everything fits: (0, False, False)")
    for bad in (0, 3, MENU_MIN - 1):
        try:
            menu_viewport(15, 0, bad)
            check(False, "rows=%d raises ValueError" % bad)
        except ValueError:
            check(True, "rows=%d raises ValueError" % bad)
    try:
        menu_panel(SESSION, 0, "menu", MENU_MIN - 1)
        check(False, "menu_panel below MENU_MIN raises ValueError")
    except ValueError:
        check(True, "menu_panel below MENU_MIN raises ValueError")
    check(menu_needed(SESSION) == 18 and menu_needed(SCHEDULE) == 12,
          "menu_needed: len(items) + 3 (18 and 12)")

    # -- the rendering, for both fixtures at every height ----------------------
    for name, items in (("session", SESSION), ("schedule", SCHEDULE)):
        for rows in range(MENU_MIN, 31):
            for cur in cursors(items):
                top, up, down = menu_viewport(len(items), cur, rows)
                tag = "%s rows=%d cur=%d" % (name, rows, cur)
                for width in (120, 40):
                    out = render(items, cur, rows, width)
                    t = "%s w=%d" % (tag, width)
                    check(len(out) == rows, t + ": exactly rows lines (%d)" % len(out), quiet=True)
                    check("╰" in out[-1], t + ": last line is the bottom border", quiet=True)
                    check("╭" in out[0], t + ": first line is the top border", quiet=True)
                    check(sum("▸" in l for l in out) == 1, t + ": one cursor row", quiet=True)
                    check(("▲" in "".join(out)) == up, t + ": ▲ iff show_up", quiet=True)
                    check(("▼" in "".join(out)) == down, t + ": ▼ iff show_down", quiet=True)
                    # Not saved by Panel(height=): nothing wrapped, so the hint
                    # is still right above the border.
                    check("↑↓ pick" in out[-2], t + ": hint is the second-to-last line",
                          quiet=True)
                    check(all(len(l) == width for l in out), t + ": no line wider than the console",
                          quiet=True)
                    if width == 40:
                        check(any("…" in l for l in out[1:-1]),
                              t + ": long labels are ellipsised", quiet=True)
                    if up:
                        check("▲ %d more" % top in out[1], t + ": ▲ counts the items above",
                              quiet=True)
        section("%s menu: rows 6..30 x first/middle/last cursor x width 120/40" % name)

    # At MENU_MIN a cursor in the middle has both markers and one item; at
    # either end one marker is not needed and its line holds a second item.
    for items in (SESSION, SCHEDULE):
        for cur, want in ((len(items) // 2, 1), (0, 2), (len(items) - 1, 2)):
            body = render(items, cur, MENU_MIN, 120)[1:-2]
            n = sum(not ("▲" in l or "▼" in l) for l in body)
            check(n == want, "rows == MENU_MIN, cur=%d draws %d item(s) (got %d)" % (cur, want, n))
    for items in (SESSION, SCHEDULE):
        need = menu_needed(items)
        for rows in (need, need + 5):
            for cur in cursors(items):
                out = render(items, cur, rows, 120)
                check("▲" not in "".join(out) and "▼" not in "".join(out),
                      "rows=%d >= needed %d draws no markers (cur=%d)" % (rows, need, cur),
                      quiet=True)
    section("rows >= needed draws no markers")

    # The disabled why-sentence keeps its reason visible when there is room.
    out = render(SCHEDULE, 1, 20, 160)
    check(any(WHY in l and "(why)" in l for l in out), "a disabled row shows its reason")
    check(any("····" in l and "…" not in l for l in render(SCHEDULE, 1, 20, 40)),
          "a separator is cropped, not ellipsised")

    con = Console(width=120, height=5, force_terminal=True)
    check(rendered_height(con, menu_panel(SESSION, 0, "menu", 18)) == 18,
          "rendered_height measures past the console height (18 on a 5-row console)")
    check(menulayout.ACCENT == "#c9a0dc", "border is the dashboard's #c9a0dc")

    print()
    if fails:
        print("%d of %d checks FAILED" % (len(fails), count))
        return 1
    print("all %d checks passed" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
