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
    column_window(cols, width, pinned, hidden, offset)
                                  -> (keep, left, right, offset): the same
                                     table through a horizontal window
    column_note(left, right)      -> str, what the title says is off screen
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


def column_window(cols: list, width: int, pinned: set, hidden: set,
                  offset: int, want: int = 20) -> tuple[list, int, int, int]:
    """The columns a table draws through a HORIZONTAL window, and what is
    off each side: (keep, left, right, offset).

    fit_columns above answers "what does a narrow terminal give up?" by
    RANK, and it still answers it for the schedules table. This answers a
    different question -- "what did the user ask to see, and where is the
    window on it?" -- so the `rank` of a spec IS IGNORED HERE: order is the
    rule now, because a column the user scrolled to must not jump to the
    other end of the table because somebody once typed a 3 in its spec.

    `pinned` and `hidden` are sets of header NAMES.
      * hidden: out of the table entirely, and counted nowhere -- not in
        `keep`, not in `left`, not in `right`.
      * pinned: always drawn, at natural width, wherever the window is.
      * a column whose header is "" -- the cursor marker both main tables
        start with -- is STRUCTURAL: always drawn, never hidden, never
        unpinned. A "" in either set is ignored rather than obeyed, so a
        settings file that grew one cannot take the cursor off the screen.
      * hidden wins over pinned, so a column named in both goes; a column
        that is pinned AND invisible is a row of questions with no answer.

    THE COLUMNS KEEP THEIR LIST ORDER on screen -- a table whose columns
    reorder as you scroll is unreadable. The unpinned, unhidden columns are
    the horizontal sequence: the first `offset` of them are off-screen left,
    and then the walk runs in list order (pinned and unpinned interleaved as
    listed) drawing every pinned one and the unpinned ones while they fit.
    It is a CONTIGUOUS PREFIX: the walk stops at the first unpinned column
    that does not fit and never skips ahead to a narrower one behind it.
    Skipping would put a column on screen that scrolling right could never
    reach, and it is how a "▶ 3 more" that never arrives gets written.

    NOTHING IS EVER SQUEEZED. A column is drawn at its natural width or not
    drawn: fixed costs kwargs["width"] + 2 (fit_columns's own cell padding),
    the one flexible column (ratio=1) costs max(min_width, want) + 2 and,
    once drawn, still takes whatever is left. `avail = width - 4`, the
    panel's two borders and their padding, exactly as fit_columns. Rich's
    own answer to running out is to shrink everything to nothing, which is
    the bug fit_columns exists to avoid; this one keeps it avoided while the
    window moves.

    `offset` COMES BACK CLAMPED, and the clamp is the whole reason it is
    returned: never below 0, never past the first offset at which the last
    unpinned column is drawn -- scrolling further would take a column off
    the left and put nothing new on the right -- and exactly 0 whenever
    everything fits. An offset whose effect the user cannot see is how a
    column goes missing: the table looks complete, the title says nothing,
    and the answer to "where is DIRTY" is a number nothing on screen shows.

    MEASURED, on the claude table's eleven columns (which want 144 characters
    of terminal, with the flexible WINDOW at its 20): at width 80, WINDOW
    pinned and nothing hidden, five columns are drawn and the note reads
    "6 more ▶"; the offset runs 0..6 and clamps at 6, the first window that
    reaches RESUMED. At 160 everything is drawn, offset 0, note "".
    """
    avail = width - 4
    seq: list[int] = []          # the unpinned, unhidden ones, in list order
    pin: set[int] = set()
    cost: dict[int, int] = {}
    for i, (header, kw, _rank) in enumerate(cols):
        if header and header in hidden:
            continue
        cost[i] = (max(kw.get("min_width", 0), want) if kw.get("ratio")
                   else kw.get("width", 0)) + 2
        if header == "" or header in pinned:
            pin.add(i)
        else:
            seq.append(i)
    fixed = sum(cost[i] for i in pin)

    def drawn(off: int) -> list[int]:
        """The unpinned columns drawn at this offset -- a prefix of seq[off:].

        The pinned columns are paid for first and in full, even when they
        alone are wider than `avail`: the caller asked for them, Rich
        ellipsises what does not fit, and the title says how many columns
        are away. Dropping one would be this module deciding, silently,
        that the user did not mean it."""
        room = avail - fixed
        out = []
        for i in seq[off:]:
            room -= cost[i]
            if room < 0:
                break
            out.append(i)
        return out

    # The clamp, WALKED rather than derived: try the offsets from 0 and
    # stop at the FIRST one whose window reaches the last unpinned column.
    # It cannot be computed as "len(seq) - visible" the way a vertical
    # window can, because the columns are different widths and how many fit
    # depends on where the window starts. Eleven columns is the widest table
    # here (claude), so this loop is at most eleven short walks.
    last = 0
    for off in range(len(seq) + 1):
        got = drawn(off)
        if got and got[-1] == seq[-1]:
            last = off
            break
    offset = max(0, min(offset, last))
    got = drawn(offset)
    return sorted(pin | set(got)), offset, len(seq) - offset - len(got), offset


def column_note(left: int, right: int) -> str:
    """What a panel title appends when a column is off the side.

    The same voice as make_table's "▲ N more" / "▼ N more" markers, and the
    KEY IS NAMED IN IT: a screen that says something is missing without
    saying what to press has told the user they have a problem and left them
    with it (CLAUDE.md, degrade honestly). "" when nothing is off screen --
    a title that always carries a note stops being read."""
    parts = []
    if left:
        parts.append("◀ %d more" % left)
    if right:
        parts.append("%d more ▶" % right)
    if not parts:
        return ""
    return " · " + " · ".join(parts + ["shift-←→"])


def make_table(cols: list, keep: list, rows: list, cur: int, marker: int,
               lines: int | None) -> Table:
    """A SIMPLE_HEAD table of the kept columns, holding `lines` row lines --
    every row when None -- scrolled with menulayout's rule, and the
    "▲ N more" / "▼ N more" markers drawn in column `marker` (a wide one
    that is never dropped: a marker that wraps is a frame one line too tall,
    which is how the handovers tab once lost its footer).

    WHICH COLUMN A CALLER PASSES AS `marker`: one that is ALWAYS DRAWN, and
    wide enough to hold "▲ 12 more". Under fit_columns that means a rank of
    None (the three callers all pass their flexible column); under
    column_window it means a pinned column, or the structural "" one."""
    t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
              header_style=DIM, border_style=FRAME)
    for i in keep:
        header, kw, _rank = cols[i]
        t.add_column(header, **dict({"no_wrap": True, "overflow": "ellipsis"}, **kw))
    n = len(rows)
    top, span, up, down = table_window(n, cur, n if lines is None else lines)

    # ...AND WHAT HAPPENS WHEN IT IS NOT DRAWN AFTER ALL. It cannot be the ""
    # column, which column_window refuses to drop, but every other candidate
    # is pinned by a settings file, and a settings file is a thing a user
    # edits. keep.index() raised ValueError there, which is the dashboard
    # dying on a frame rather than drawing one. The fallback is the widest
    # column still drawn, preferring the flexible one: the marker lands a
    # column to the side instead of nowhere, and every column is no_wrap +
    # ellipsis, so the worst case is a marker cut short and never a wrapped
    # row -- the failure this whole argument exists to prevent.
    if marker in keep:
        at = keep.index(marker)
    elif keep:
        at = max(range(len(keep)),
                 key=lambda j: (bool(cols[keep[j]][1].get("ratio")),
                                cols[keep[j]][1].get("width", 0)))
    else:
        at = 0

    def mark(text: str) -> None:
        if not keep:
            return
        cells = [""] * len(keep)
        cells[at] = Text(text, style=DIM)
        t.add_row(*cells)

    if up:
        mark("▲ %d more" % top)
    for r in rows[top:top + span]:
        t.add_row(*[r[i] for i in keep])
    if down:
        mark("▼ %d more" % (n - top - span))
    return t
