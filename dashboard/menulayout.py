"""menulayout -- the dashboard's context menus, drawn at an exact height.

deck_status.py draws its menu as the last element of the frame, and Rich's
Live(screen=True) crops a frame taller than the terminal from the BOTTOM --
so the long menus (the session menu is 15 rows plus chrome) lose their tail,
cursor and hint included, on a short terminal. The fix is to give
the menu a measured number of rows and have it draw exactly that many,
scrolling its items inside them. This module is that half, and it is pure:
no dashboard state, no I/O, only Rich.

    MENU_MIN                               6: border, ▲, one item, ▼, hint, border
    menu_needed(items)            -> int   rows to draw every item (len + 3)
    menu_viewport(n, cur, rows)   -> (top, show_up, show_down)
    menu_panel(items, cur, title, rows)    -> Panel, exactly `rows` lines tall
    rendered_height(console, renderable)   -> int, what Rich will really draw

AND THE SAME ARITHMETIC FOR A TABLE on a short terminal, so there is one
scrolling rule on the screen and not one per table:

    TABLE_MIN                              3: ▲, one row, ▼ (MENU_MIN less chrome)
    table_window(n, cur, lines)   -> (top, span, show_up, show_down)
    share_rows(room, needs)       -> [lines per table] or None: no room
    page_jump(key, i, n, page)    -> the index PageUp/PageDown/Home/End means
    page_land(key, i, n, page, skip) -> the same, off unselectable rows
    fit_columns(cols, width)      -> the columns a narrow terminal keeps
    make_table(cols, keep, rows, cur, marker, lines) -> Table, windowed

Items are the dicts Dashboard.menu_entries() builds: label, and optionally
sep, disabled (the reason, shown in brackets), danger, on, key. The styling is
the one build() used for the footer menu, unchanged.

THE ROWS BUDGET is the whole panel: two border lines, the hint line, and the
item lines. A "▲ N more" / "▼ N more" marker takes an item line out of that
budget rather than being drawn on top of one, so the height never moves when
the cursor scrolls. Once the window has to scroll, the cursor stays on the
window's centre line and the items move under it, so moving it by one moves
the view by one instead of paging.

EVERY LINE IS no_wrap + ellipsis: a label wider than the panel is cut with
"…", never wrapped onto a second line that would push the border off-screen.
Panel(height=rows) is the backstop on top of that, and the tests check the
backstop is never what saved it (the hint is still the second-to-last line).
"""
from rich import box
from rich.console import Console, ConsoleRenderable, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# The dashboard's palette (deck_status.py), copied rather than imported:
# importing the dashboard would pull in all of it to draw one panel.
GREEN, RED = "#7ec699", "#d47f7f"
DIM, FRAME = "grey42", "grey30"
ACCENT = "#c9a0dc"

MENU_MIN = 6      # border, ▲ marker, one item, ▼ marker, hint line, border
CHROME = 3        # two borders and the hint line
HINT = "↑↓ pick · enter choose · esc close"


def menu_needed(items: list[dict]) -> int:
    """Rows to draw every item with no scrolling."""
    return len(items) + CHROME


def menu_viewport(n_items: int, cur: int, rows: int) -> tuple[int, bool, bool]:
    """The first item drawn, and whether the ▲ and ▼ marker lines are drawn.

    `rows` is the total panel height. The window holds `rows - 3` lines,
    minus one per marker shown; `cur` is always inside it."""
    if rows < MENU_MIN:
        raise ValueError("a menu needs at least %d rows, got %d" % (MENU_MIN, rows))
    budget = rows - CHROME
    if n_items <= budget:
        return 0, False, False
    cur = max(0, min(cur, n_items - 1))
    one = budget - 1          # item lines with one marker
    both = budget - 2         # item lines with both, >= 1 because rows >= 6
    # The cursor's line is the window's centre. At the top the window starts
    # at 0 and has no ▲; at the bottom it ends at the last item and has no ▼.
    # In between both markers show and the window follows the cursor, which
    # lands on the same screen line as at either end (▲ takes the line the
    # extra item had), so crossing into the middle does not make it jump.
    if cur <= (one - 1) // 2:
        return 0, False, True
    bottom = n_items - one
    if cur >= bottom + (one - 1) // 2:
        return bottom, True, False
    top = cur - (both - 1) // 2
    top = max(1, min(top, n_items - both - 1))
    return top, True, True


def _item_line(it: dict, is_cur: bool) -> Text:
    if it.get("sep"):
        return Text("   " + "·" * 52, style=FRAME, no_wrap=True, overflow="crop")
    line = Text(no_wrap=True, overflow="ellipsis")
    if it.get("disabled"):
        line.append("     " + it["label"], style=FRAME)
        line.append("  (%s)" % it["disabled"], style=FRAME)
        return line
    line.append(" ▸ " if is_cur else "   ", style="bold " + ACCENT)
    style = "bold"
    if it.get("danger"):
        style = "bold " + RED if is_cur else RED
    elif "on" in it:
        style = ("bold " + GREEN) if it["on"] else ("bold " if is_cur else DIM)
    elif not is_cur:
        style = ""
    line.append(it["label"], style=style)
    return line


def menu_panel(items: list[dict], cur: int, title: str, rows: int,
               hint: str = HINT) -> Panel:
    """The menu as a Panel exactly `rows` lines tall at any width >= 40.

    `title` is markup, drawn as `[bold]<title>`, so a caller may add a dim
    note to it; escape a raw file or window name before passing it."""
    top, show_up, show_down = menu_viewport(len(items), cur, rows)
    span = rows - CHROME - show_up - show_down
    shown = items[top:top + span]
    below = len(items) - top - len(shown)

    lines: list[Text] = []
    if show_up:
        lines.append(Text("   ▲ %d more" % top, style=DIM, no_wrap=True,
                          overflow="ellipsis"))
    for i, it in enumerate(shown, start=top):
        lines.append(_item_line(it, i == cur))
    if show_down:
        lines.append(Text("   ▼ %d more" % below, style=DIM, no_wrap=True,
                          overflow="ellipsis"))
    # More rows than items (a caller that did not cap at menu_needed): the
    # slack goes above the hint, so the hint always sits on the border.
    lines += [Text("") for _ in range(rows - CHROME - len(lines))]
    lines.append(Text("   " + hint, style=DIM, no_wrap=True, overflow="ellipsis"))
    # One Text per line in a Group, not one joined Text: overflow belongs to a
    # whole Text, and a separator is cropped where a label is ellipsised.
    return Panel(Group(*lines), title="[bold]" + title, title_align="left",
                 border_style=ACCENT, box=box.ROUNDED, height=rows)


def rendered_height(console: Console, renderable: ConsoleRenderable) -> int:
    """How many lines Rich will draw for `renderable` on `console`.

    One place, so the room under the panels is measured the same way
    everywhere. render_lines does not crop to the console's height."""
    return len(console.render_lines(renderable, console.options))


# ------------------------------------------------------------ tables
# A table on a short terminal gets a measured number of ROW LINES and scrolls
# inside them with the menus' own centred-cursor rule and their own
# "▲ N more" / "▼ N more" markers, which take a row line rather than being
# drawn on one. TABLE_MIN is MENU_MIN without the menu's chrome (the table's
# chrome is measured by the caller, because it is the table's own): below it
# a table cannot show a row and both markers, and the caller DEGRADES --
# drops a panel that matters less -- exactly as place_menu degrades a menu
# with less than MENU_MIN lines to modal.
TABLE_MIN = MENU_MIN - CHROME


def table_window(n_rows: int, cur: int, lines: int) -> tuple[int, int, bool, bool]:
    """(first row drawn, rows drawn, ▲ marker, ▼ marker) for a table given
    `lines` row lines. `cur` < 0 means the cursor is not in this table: the
    window then sits at the top."""
    if n_rows <= lines:
        return 0, n_rows, False, False
    top, up, down = menu_viewport(n_rows, max(0, cur), max(lines, TABLE_MIN) + CHROME)
    return top, max(lines, TABLE_MIN) - up - down, up, down


def share_rows(room: int, needs: list[int]) -> list[int] | None:
    """Split `room` row lines between tables that want `needs` of them.

    Every table first gets what it needs up to TABLE_MIN -- enough to show a
    row and say how many more there are -- and then the rest goes to the
    LAST table first, then the one before it: on the main view that is the
    claude table before the lanes table, because the sessions are what the
    screen is for. None when not even the minimums fit: the caller must drop
    something else first."""
    base = [min(n, TABLE_MIN) for n in needs]
    left = room - sum(base)
    if left < 0:
        return None
    out = list(base)
    for i in range(len(needs) - 1, -1, -1):
        more = min(left, needs[i] - out[i])
        out[i] += more
        left -= more
    return out


# --------------------------------------------------- Page Up/Down, Home/End
# A list that scrolls with the rule above also has to answer PageUp, PageDown,
# Home and End, and the arithmetic is the same arithmetic: a "page" is the
# rows the viewport actually shows, which is the number the caller already
# worked out for menu_panel/make_table. One implementation, so the schedules
# table, the sessions table, the handovers tab, the insights breakdown, the
# menus, the picker and the options table cannot disagree about what a page
# is -- a key that pages one list and exits another is worse than no key.
PAGE_KEYS = ("PGUP", "PGDN", "HOME", "END")


def page_jump(key: str, i: int, n: int, page: int) -> int | None:
    """The new cursor index for one of PAGE_KEYS, or None for any other key.

    CLAMPED AT BOTH ENDS -- PageUp at the top is the first row, not a
    negative index and not a wrap -- and O(1), so End on a thousand-row
    ledger costs what End on a three-row one costs."""
    if key not in PAGE_KEYS or n <= 0:
        return None
    page = max(1, page)
    if key == "HOME":
        return 0
    if key == "END":
        return n - 1
    if key == "PGUP":
        return max(0, i - page)
    return min(n - 1, i + page)


def page_land(key: str, i: int, n: int, page: int, skip=None) -> int | None:
    """page_jump, then off any row that cannot hold a cursor.

    `skip(j)` is True for a row the cursor may not sit on -- a menu
    separator, a disabled row, the options table's headings. Home and End
    search INTO the list; a page step searches the way it moved and then the
    other way, so PageUp landing on a heading at the top still ends on the
    first row that IS selectable rather than on the heading or nowhere."""
    j = page_jump(key, i, n, page)
    if j is None or skip is None:
        return j
    first = -1 if key in ("PGUP", "END") else 1
    for step in (first, -first):
        for k in range(j, n if step > 0 else -1, step):
            if not skip(k):
                return k
    return i


def fit_columns(cols: list, width: int, want: int = 20) -> list[int]:
    """The columns a table keeps at this width: (header, kwargs, rank)
    specs, and the ones with the lowest rank go first until the one
    flexible column (ratio=1) has `want` characters. At 160 columns nothing
    goes; at 80 the claude table keeps its window names instead of drawing
    them zero wide, which is what Rich does when it runs out."""
    avail = width - 4          # the panel's two borders and their padding
    keep = list(range(len(cols)))

    def need() -> int:
        return sum(cols[i][1].get("width", 0) + 2 for i in keep) + want

    # Past the last rank Rich shrinks what is left, ellipsised (every column
    # is no_wrap), and the flexible column keeps its min_width -- without
    # which Rich gives it NOTHING, and the table loses the one column that
    # names its rows.

    for rank in sorted({c[2] for c in cols if c[2] is not None}):
        if need() <= avail:
            break
        keep = [i for i in keep if cols[i][2] != rank]
    return keep


def make_table(cols: list, keep: list, rows: list, cur: int, marker: int,
               lines: int | None) -> Table:
    """A SIMPLE_HEAD table of the kept columns, holding `lines` row lines --
    every row when None -- scrolled with menulayout's rule, and the
    "▲ N more" / "▼ N more" markers drawn in column `marker` (a wide one
    that is never dropped: a marker that wraps is a frame one line too tall,
    which is how the handovers tab once lost its footer)."""
    t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
              header_style=DIM, border_style=FRAME)
    for i in keep:
        header, kw, _rank = cols[i]
        t.add_column(header, **dict({"no_wrap": True, "overflow": "ellipsis"}, **kw))
    n = len(rows)
    top, span, up, down = table_window(n, cur, n if lines is None else lines)

    def mark(text: str) -> None:
        cells = [""] * len(keep)
        cells[keep.index(marker)] = Text(text, style=DIM)
        t.add_row(*cells)

    if up:
        mark("▲ %d more" % top)
    for r in rows[top:top + span]:
        t.add_row(*[r[i] for i in keep])
    if down:
        mark("▼ %d more" % (n - top - span))
    return t
