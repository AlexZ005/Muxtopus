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

from dashboard import menulayout  # noqa: E402
from dashboard.menulayout import (CHROME, MENU_MIN, menu_chrome,  # noqa: E402
                        menu_desc_lines, menu_head_lines, menu_needed,
                        menu_panel, menu_viewport, rendered_height)

# The session menu with both global switches off, shaped as
# Dashboard.menu_entries() builds it. The plan (§0.3) counts it as 11 entries,
# 2 separators and 2 "off globally" lines; the last two rows before the
# separator stand in for the entries that bring today's 9 up to that count.
W = "dash-menus-settings-with-a-long-name"
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
    {"label": "Schedule a resume of %s at the next reset  reads its STATUS file" % W},
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
    {"label": "Open its window dash-menus-layout-engine"},
    {"sep": True},
    {"label": "Delete %s" % F, "danger": True},
]
assert len(SESSION) == 15 and len(SCHEDULE) == 9

# ------------------------------------------------------------ descriptions
# A menu with MIXED rows: one with a short description, one with a long one,
# a separator, a disabled row that carries one anyway (it is not drawn), and
# two rows with none. The height must not move as the cursor crosses them.
SHORT = "restart a limited window once its limit resets"
LONG = ("this window is waiting on a lane that has not finished, so the "
        "watchdog leaves it alone until the handover says otherwise and the "
        "next pass picks it up")
HEADER = "menu layout, defaults for a new window, where a mode is made permanent"
DESC = [
    {"label": "Settings"},
    {"sep": True},
    {"label": "Watchdog: ON", "desc": SHORT, "on": True},
    {"label": "Monitor: off", "desc": "ask a working window to wind down near the limit"},
    {"label": "greyed", "disabled": "no window", "desc": "never drawn"},
    {"label": "Quit the dashboard", "danger": True},
]
WIDE = [{"label": "Waiting", "desc": LONG}, {"label": "Plain"}]
NODESC = [{"label": "one"}, {"label": "two"}, {"label": "three"}]
# More rows than a short panel can hold, so the line the hint gave back is
# visibly one more ITEM and not one more blank.
MANY = [{"label": "row %d" % i} for i in range(7)]

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


def bare(line):
    """A rendered line without the panel's own borders and padding."""
    return line.strip(" │")


def panel_lines(items, cur, rows, width, **kw):
    """The panel's lines, rendered at `width`, with the description
    arguments this file needs to pass (width=, header=, hint=)."""
    con = Console(width=width, height=rows, force_terminal=True,
                  color_system="truecolor")
    panel = menu_panel(items, cur, "menu", rows, width=width, **kw)
    return ["".join(seg.text for seg in line)
            for line in con.render_lines(panel, con.options)]


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

    # ------------------------------------------- a row's own description
    # The height contract with the description line in it: the reservation is
    # the WHOLE open of the menu, so the panel is the same height on every
    # row, and a description longer than the reservation is ellipsised rather
    # than allowed to add a line.
    check(menu_desc_lines(DESC, 120) == 1, "one-line descriptions reserve one line")
    check(menu_desc_lines(DESC, 44) == 2, "...and two when the same text wraps")
    check(menu_desc_lines(WIDE, 120) == 2, "the reservation is the WIDEST row's, not the cursor's")
    check(menu_desc_lines(NODESC, 40) == 0, "a menu whose rows have none reserves none")
    check(menu_desc_lines([{"label": "x", "desc": SHORT, "disabled": "why"},
                           {"sep": True, "desc": SHORT}], 120) == 0,
          "a disabled row and a separator reserve nothing")
    try:
        menu_panel(DESC, 0, "menu", 12)
        check(False, "a desc with no width= is a ValueError")
    except ValueError:
        check(True, "a desc with no width= is a ValueError, not a guess")

    for name, items in (("desc", DESC), ("wide", WIDE)):
        for width in (120, 78, 44):
            need = menu_needed(items, menu_chrome(True, menu_desc_lines(items, width)))
            for rows in range(menu_chrome(True, menu_desc_lines(items, width)) + 3,
                              need + 3):
                for cur in range(len(items)):
                    if items[cur].get("sep") or items[cur].get("disabled"):
                        continue
                    out = panel_lines(items, cur, rows, width)
                    t = "%s w=%d rows=%d cur=%d" % (name, width, rows, cur)
                    check(len(out) == rows, t + ": exactly rows lines", quiet=True)
                    check("↑↓ pick" in out[-2], t + ": the hint is still second-to-last",
                          quiet=True)
                    check("╰" in out[-1], t + ": and the border under it", quiet=True)
                    check(sum("▸" in l for l in out) == 1, t + ": one cursor row", quiet=True)
    section("the panel height never moves across every cursor position, at three widths")

    # What is actually ON the reserved line, row by row.
    lines = panel_lines(DESC, 0, menu_needed(DESC, 4), 120)
    check(bare(lines[-3]) == "", "a row with no desc leaves the line BLANK")
    i = [j for j, it in enumerate(DESC) if it.get("desc") == SHORT][0]
    lines = panel_lines(DESC, i, menu_needed(DESC, 4), 120)
    check(SHORT in lines[-3], "the row under the cursor explains itself: %r" % lines[-3].strip()[:50])
    check(lines[-3].index(SHORT[0]) == lines[-2].index("↑"),
          "...indented to where the labels start, like the hint")
    j = [k for k, it in enumerate(DESC) if it.get("disabled")][0]
    lines = panel_lines(DESC, j, menu_needed(DESC, 4), 120)
    check(bare(lines[-3]) == "" and "never drawn" not in "".join(lines),
          "a disabled row's desc is not drawn even when it has one")

    # Two lines, and the ellipsis on the second.
    lines = panel_lines(WIDE, 0, max(menu_needed(WIDE, 5), 8), 78)
    check(bare(lines[-3]) and bare(lines[-4]), "a two-line desc uses both reserved lines")
    check("…" in lines[-3], "and is ellipsised on the last one rather than adding a third")

    # ------------------------------------------------- the menu's own header
    head = panel_lines(DESC, 0, menu_needed(DESC, 5), 120, header=HEADER)
    check(HEADER in head[1], "a menu's header is drawn under the title border")
    check(len(head) == menu_needed(DESC, 5), "...out of the same rows budget")
    check(menu_head_lines(HEADER, 120) == 1 and menu_head_lines("", 120) == 0,
          "menu_head_lines counts it, and a menu without one costs nothing")
    check(sum(HEADER in l for l in head) == 1, "and it is drawn ONCE, not per row")

    # ------------------------------------------------- the menu's hint line
    # hint=None is THE PANEL'S OWN HINT LINE off -- not App.add_hint's footer
    # key line -- and the row it held goes back to the list.
    check(menu_chrome(True) == CHROME and menu_chrome(False) == CHROME - 1,
          "no hint line is one line less chrome")
    with_hint = panel_lines(MANY, 0, 8, 120)
    without = panel_lines(MANY, 0, 8, 120, hint=None)
    check("↑↓ pick" in with_hint[-2] and not any("↑↓ pick" in l for l in without),
          "hint=None draws no hint line")
    check(len(without) == len(with_hint) == 8, "both are exactly the rows asked for")
    shown = lambda out: sum(any(it["label"] in l for it in MANY) for l in out)
    check(shown(without) == shown(with_hint) + 1,
          "and the line it reserved holds one more ITEM now (%d -> %d)"
          % (shown(with_hint), shown(without)))

    # ------------------------------------------------ tables on a short screen
    from rich.panel import Panel
    from dashboard.menulayout import (TABLE_MIN, fit_columns, make_table,
                                      share_rows, table_window)
    check(TABLE_MIN == MENU_MIN - 3, "TABLE_MIN is MENU_MIN without the menu's chrome")
    for n in range(0, 30):
        for lines in range(TABLE_MIN, 25):
            for cur in range(-1, n):
                top, span, up, down = table_window(n, cur, lines)
                drawn = span + up + down
                check(drawn <= max(lines, n if n <= lines else 0) and
                      (n <= lines or drawn == lines),
                      "n=%d lines=%d cur=%d draws %d lines" % (n, lines, cur, drawn), quiet=True)
                check(cur < 0 or top <= cur < top + span,
                      "n=%d lines=%d cur=%d cursor inside" % (n, lines, cur), quiet=True)
                check(up == (top > 0) and down == (top + span < n),
                      "n=%d lines=%d cur=%d markers say the truth" % (n, lines, cur), quiet=True)
    section("table_window: exact height, cursor inside, markers true")
    check(share_rows(20, [1, 6]) == [1, 6], "room for both: everything")
    check(share_rows(6, [4, 10]) == [3, 3], "tight: each its minimum")
    check(share_rows(9, [4, 10]) == [3, 6], "the rest goes to the LAST table first")
    check(share_rows(13, [4, 6]) == [4, 6], "...and then to the one before it")
    check(share_rows(5, [4, 10]) is None, "no room for both minimums: None, drop something")
    check(share_rows(2, [1, 1]) == [1, 1], "a one-row table needs one line, not three")
    cols = [("", {"width": 3}, None), ("A", {"width": 20}, 2),
            ("NAME", {"ratio": 1, "min_width": 12}, None), ("B", {"width": 20}, 1)]
    check(fit_columns(cols, 160) == [0, 1, 2, 3], "wide: every column")
    check(fit_columns(cols, 60) == [0, 1, 2], "narrower: rank 1 goes first")
    check(fit_columns(cols, 40) == [0, 2], "narrower still: then rank 2; None never goes")
    rows = [["", "a%d" % i, "row %d" % i, "b"] for i in range(12)]
    for width in (40, 80, 160):
        con = Console(width=width)
        for lines in (TABLE_MIN, 5, 8, None):
            for cur in (-1, 0, 6, 11):
                t = make_table(cols, fit_columns(cols, width), rows, cur, 2, lines)
                h = rendered_height(con, Panel(t))
                want = 6 + (12 if lines is None else lines)
                check(h == want, "w=%d lines=%s cur=%d: %d lines, want %d"
                      % (width, lines, cur, h, want), quiet=True)
    section("make_table: the height is the chrome plus the lines given, at every width")

    # ------------------------------------------ a table through a horizontal window
    # THE FIXTURE IS THE REAL ONE: main.py's ct_cols in its under-100-columns
    # form, copied rather than imported, because importing the view would pull
    # in the whole dashboard to check some arithmetic -- and because a copy
    # that drifts is caught by tests/test_names.py reading both.
    from dashboard.menulayout import column_note, column_window
    CT = [
        ("", {"width": 3}, None),
        ("MON", {"width": 4}, 3),
        ("WINDOW", {"ratio": 1, "min_width": 12}, None),
        ("MODEL", {"width": 11}, 7),
        ("CONTEXT", {"width": 21}, 8),
        ("SPENT", {"justify": "right", "width": 8}, 4),
        ("IDLE", {"justify": "right", "width": 6}, 5),
        ("STATE", {"width": 15}, None),
        ("DIRTY", {"justify": "right", "width": 6}, 6),
        ("WOUND", {"width": 12}, 2),
        ("RESUMED", {"width": 12}, 1),
    ]
    NAMES = [c[0] for c in CT]
    CT_ROWS = [["", "m", "win %d" % i, "sonnet", "ctx", "$1", "2m", "idle", "0",
                "wound", "resumed"] for i in range(12)]

    def natural(kw, want=20):
        """column_window's own width arithmetic, written out a second time so
        the test cannot inherit a bug from the code it is checking."""
        if kw.get("ratio"):
            return max(kw.get("min_width", 0), want) + 2
        return kw.get("width", 0) + 2

    def live(hidden):
        return [i for i, n in enumerate(NAMES) if not (n and n in hidden)]

    def unpinned(pinned, hidden):
        return [i for i in live(hidden) if NAMES[i] and NAMES[i] not in pinned]

    # -- wide: everything is drawn and the offset is 0 whatever was asked for
    for width in (144, 160, 200, 400):
        for ask in (-5, 0, 1, 4, 99):
            keep, lf, rt, off = column_window(CT, width, set(), set(), ask)
            tag = "w=%d ask=%d" % (width, ask)
            check(keep == list(range(len(CT))), tag + ": every column drawn", quiet=True)
            check((lf, rt, off) == (0, 0, 0), tag + ": nothing off either side, offset 0",
                  quiet=True)
    check(column_window(CT, 144, set(), set(), 0)[0] == list(range(11)),
          "144 columns is what the claude table wants, and it gets all eleven")
    section("wide: every column drawn and the offset clamps to 0, whatever was asked")

    # -- narrow, at every width: a contiguous prefix at natural widths, and
    # -- the three counts account for every unhidden column.
    PINS = (set(), {"WINDOW"}, {"WINDOW", "RESUMED"}, {"MON", "STATE"})
    for width in range(20, 201):
        for pinned in PINS:
            seq = unpinned(pinned, set())
            pins = [i for i in live(set()) if i not in seq]
            for ask in range(0, len(seq) + 2):
                keep, lf, rt, off = column_window(CT, width, pinned, set(), ask)
                tag = "w=%d pin=%s ask=%d" % (width, sorted(pinned), ask)
                check(keep == sorted(set(keep)), tag + ": list order, no repeats", quiet=True)
                check(all(i in keep for i in pins), tag + ": every pinned column drawn",
                      quiet=True)
                check(len(keep) + lf + rt == len(live(set())),
                      tag + ": keep + left + right is every unhidden column", quiet=True)
                check(lf == off, tag + ": left is the offset", quiet=True)
                drawn = [i for i in keep if i in seq]
                check(drawn == seq[off:off + len(drawn)],
                      tag + ": a contiguous prefix, never skipping to a narrower one",
                      quiet=True)
                check(rt == len(seq) - off - len(drawn), tag + ": right counts the rest",
                      quiet=True)
                # Natural widths: nothing is squeezed to make it fit. The one
                # exception is the pinned columns alone overflowing, which is
                # the caller's instruction and is drawn anyway.
                cost = sum(natural(CT[i][1]) for i in keep)
                pincost = sum(natural(CT[i][1]) for i in pins)
                check(cost <= width - 4 or pincost > width - 4,
                      tag + ": %d of %d columns, nothing squeezed" % (cost, width - 4),
                      quiet=True)
                # One more unpinned column would NOT have fitted: the walk
                # stopped because it ran out of room, not early.
                nxt = off + len(drawn)
                if nxt < len(seq) and pincost <= width - 4:
                    check(cost + natural(CT[seq[nxt]][1]) > width - 4,
                          tag + ": it stopped at the first one that did not fit", quiet=True)
    section("narrow: a contiguous prefix at natural widths, every width 20..200")

    # -- a pinned column past the cut is drawn; an unpinned one before it is not
    keep, lf, rt, off = column_window(CT, 80, {"WINDOW", "RESUMED"}, set(), 0)
    drawn = [NAMES[i] for i in keep]
    check("RESUMED" in drawn, "a pinned LAST column is drawn at 80 columns")
    check(any(NAMES[i] not in drawn for i in range(len(CT)) if NAMES[i] not in
              ("", "WINDOW", "RESUMED")),
          "...while an unpinned column ahead of it in the list is not")
    check(drawn.index("RESUMED") == len(drawn) - 1,
          "and it keeps its LIST ORDER: RESUMED is still drawn last")

    # -- hidden: out of the table and counted nowhere
    keep, lf, rt, off = column_window(CT, 80, set(), {"CONTEXT"}, 0)
    check(4 not in keep, "a hidden column is not drawn")
    check(len(keep) + lf + rt == 10, "...and is counted nowhere: ten columns, not eleven")
    keep, lf, rt, off = column_window(CT, 200, {"CONTEXT"}, {"CONTEXT"}, 0)
    check(4 not in keep and len(keep) + lf + rt == 10, "hidden beats pinned")
    keep, lf, rt, off = column_window(CT, 40, set(), {""}, 0)
    check(0 in keep, 'the "" cursor column cannot be hidden')
    keep, _lf, _rt, _off = column_window(CT, 20, set(), set(), 0)
    check(keep[0] == 0, 'the "" column is drawn even at 20 columns')
    keep, lf, rt, off = column_window(CT, 80, {""}, set(), 3)
    check(0 in keep and lf == 3, 'a "" in `pinned` is ignored, not obeyed')
    all_but = {n for n in NAMES if n}
    keep, lf, rt, off = column_window(CT, 80, set(), all_but, 4)
    check(keep == [0] and (lf, rt, off) == (0, 0, 0),
          'everything hidden but "": one column, and the offset goes back to 0')

    # -- the offset walks one unpinned column at a time, and the end is clamped
    seq = unpinned({"WINDOW"}, set())
    walk = [column_window(CT, 80, {"WINDOW"}, set(), o)[3] for o in range(len(seq) + 4)]
    check(walk[:7] == list(range(7)), "each step takes exactly one column off the left")
    check(len(set(walk[7:])) == 1 and walk[-1] == 6,
          "and then it clamps at 6 and stays there -- no wrap (%r)" % walk[-3:])
    last = column_window(CT, 80, {"WINDOW"}, set(), 99)
    check(NAMES[last[0][-1]] == "RESUMED" and last[2] == 0,
          "the clamped offset is the first one that reaches the last column")
    check(column_window(CT, 80, {"WINDOW"}, set(), -7)[3] == 0, "a negative offset is 0")
    for width in range(20, 201):
        seq = unpinned(set(), set())
        keep, lf, rt, off = column_window(CT, width, set(), set(), 999)
        check(rt == 0 or not keep or off == 0,
              "w=%d: the clamped offset leaves nothing off the right" % width, quiet=True)
    section("the clamp never lets a scroll run into blank space")

    # -- pinned columns that cannot fit are drawn anyway, and nothing raises
    fat = {"CONTEXT", "STATE", "WOUND", "RESUMED"}
    keep, lf, rt, off = column_window(CT, 30, fat, set(), 2)
    check(all(NAMES[i] in fat or NAMES[i] == "" for i in keep),
          "pinned alone too wide: the pinned columns and nothing else")
    check(len(keep) == 5, "...every one of them, none dropped (%d)" % len(keep))
    check((lf, rt, off) == (0, 6, 0),
          "...the six unpinned ones are all off the right, offset back to 0 (%r)"
          % ((lf, rt, off),))

    # -- the note
    check(column_note(0, 0) == "", "nothing off screen: no note at all")
    check(column_note(2, 0) == " · ◀ 2 more · shift-←→", "left only")
    check(column_note(0, 3) == " · 3 more ▶ · shift-←→", "right only")
    check(column_note(2, 3) == " · ◀ 2 more · 3 more ▶ · shift-←→", "both sides")
    check("shift-←→" in column_note(0, 1),
          "the note says WHICH KEY: a screen that only says something is missing")

    # -- RENDERED: the promise made visible. A table drawn with the `keep` it
    # -- was given is exactly as tall as it said, and no header is cut with "…"
    # -- -- which is what "never squeezed" means on a screen rather than in a
    # -- sum. A column that wraps is a frame one line too tall.
    for width in range(20, 201):
        for pinned in (set(), {"WINDOW"}, {"WINDOW", "RESUMED"}):
            pins = [i for i in range(len(CT)) if NAMES[i] == "" or NAMES[i] in pinned]
            pincost = sum(natural(CT[i][1]) for i in pins)
            for ask in (0, 3, 99):
                keep, lf, rt, off = column_window(CT, width, pinned, set(), ask)
                con = Console(width=width)
                tag = "w=%d pin=%s ask=%d" % (width, sorted(pinned), ask)
                for lines in (TABLE_MIN, 5, 8):
                    t = make_table(CT, keep, CT_ROWS, 4, 2, lines)
                    h = rendered_height(con, Panel(t))
                    check(h == 6 + lines, "%s lines=%d: %d lines, want %d"
                          % (tag, lines, h, 6 + lines), quiet=True)
                if pincost > width - 4:
                    continue          # the caller's pinned columns overflow: Rich cuts them
                # [1], not [0]: a SIMPLE_HEAD table opens with a blank line,
                # then the header row, then its rule.
                head = ["".join(s.text for s in l)
                        for l in con.render_lines(make_table(CT, keep, CT_ROWS, 4, 2, 5),
                                                  con.options)][1]
                check("…" not in head, tag + ": no header cut with … (%r)" % head, quiet=True)
                for i in keep:
                    check(NAMES[i] in head or NAMES[i] == "",
                          tag + ": %s is drawn whole" % NAMES[i], quiet=True)
    section("rendered: the height it promised, and not one header squeezed")

    # -- make_table survives a marker column that is not drawn
    t = make_table(CT, [0, 2], CT_ROWS, 4, 9, 4)
    check(rendered_height(Console(width=80), Panel(t)) == 10,
          "a marker column that was scrolled away does not raise")
    body = ["".join(s.text for s in l) for l in
            Console(width=80).render_lines(make_table(CT, [0, 2], CT_ROWS, 4, 9, 4),
                                           Console(width=80).options)]
    check(any("more" in l for l in body), "...and the ▲/▼ count is still drawn somewhere")


    print()
    if fails:
        print("%d of %d checks FAILED" % (len(fails), count))
        return 1
    print("all %d checks passed" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
