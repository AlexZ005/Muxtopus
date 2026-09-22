"""menulayout -- the dashboard's context menus, drawn at an exact height.

deck_status.py draws its menu as the last element of the frame, and Rich's
Live(screen=True) crops a frame taller than the terminal from the BOTTOM --
so the long menus (the session menu is 15 rows plus chrome) lose their tail,
cursor and hint included, on a short terminal. The fix is to give
the menu a measured number of rows and have it draw exactly that many,
scrolling its items inside them. This module is that half, and it is pure:
no dashboard state, no I/O, only Rich.

    MENU_MIN                               6: border, ▲, one item, ▼, hint, border
    menu_chrome(hint, desc, header)-> int  the panel lines that are not items
    menu_desc_lines(items, width) -> int   lines reserved for a row's `desc`
    menu_head_lines(header, width)-> int   lines the menu's own header takes
    menu_needed(items, chrome)    -> int   rows to draw every item
    menu_viewport(n, cur, rows, chrome)    -> (top, show_up, show_down)
    menu_panel(items, cur, title, rows, ...) -> Panel, exactly `rows` tall
    modal_width(console_width)    -> int   the widest a CENTRED panel is drawn
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
desc (the sentence that explains the row), sep, disabled (the reason, shown
in brackets), danger, on, key. The styling is the one build() used for the
footer menu, unchanged.

A ROW'S `desc` IS DRAWN AT THE BOTTOM, on the reserved line(s) directly above
the hint, and only while the cursor is on that row. Not above the list, where
it would shift every row down by a line the moment it appeared -- and the
list is the thing the eye is tracking. Below it, nothing the eye is on moves;
it is also where the TUIs a hand already knows put it (htop's F-key line,
dialog and whiptail, lazygit's bottom help, vim's cmdline).

The line is RESERVED FOR THE WHOLE OPEN of a menu in which any row has one,
and left blank on a row that has none, because the panel's height must not
depend on where the cursor is: a panel that grew a line under one row would
move every panel above it in the `table` layout, and jump the whole frame in
`modal`. The reservation is the MAXIMUM number of lines any one row of THIS
menu needs at THIS width (menu_desc_lines), capped at DESC_MAX; a description
that needs more is ellipsised on its last reserved line rather than allowed
to add one. `header` is the same thing for the MENU: drawn once under the
title border, before the rows, for a submenu that explains itself once it is
open instead of on the row that led to it.

The hint argument is THE MENU'S OWN HINT LINE -- the "↑↓ pick · enter choose
· esc close" line inside the panel, which add_menu's `hint_fn` fills -- and
not the main view's footer key line (App.add_hint), which this module never
draws. hint=None draws no such line AND reserves none, so the row it held
goes back to the list.

THE ROWS BUDGET is the whole panel: two border lines, the hint line, the
description line(s) and the header line(s) reserved above, and the item lines
that are left (menu_chrome counts everything that is not an item). A
"▲ N more" / "▼ N more" marker takes an item line out of that budget rather
than being drawn on top of one, so the height never moves when the cursor
scrolls. Once the window has to scroll, the cursor stays on the
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
BODY_MIN = MENU_MIN - CHROME   # 3: the ▲ marker, one item, the ▼ marker
HINT = "↑↓ pick · enter choose · esc close"

# A description is reserved, never drawn on demand, so two lines is the cap:
# a third would cost the list an item line on every row of the menu to serve
# the one row that wanted it. Past it the last line is ellipsised.
DESC_MAX = 2
# The same three spaces a row's label is drawn behind, so a description lines
# up under the row it explains rather than under the cursor arrow.
DESC_INDENT = "   "

# A CENTRED PANEL IS CAPPED. 78 columns, because a line much past 80 is hard
# to come back to on the next one -- and because 80 is what a terminal still
# is when nobody has resized it, so 78 is the widest a modal can be and still
# have air either side of it there. The cap is a ceiling and not a width: a
# panel whose content is narrower stays narrower, which is what made the
# labels worth splitting in the first place.
MODAL_MAX = 78
MODAL_MARGIN = 4       # two columns of air either side of a centred panel

# Wrapping is MEASURED, not counted in characters: these labels carry "▸",
# "·" and box glyphs, and len() is wrong about every one of them. A console
# of a fixed width, so the measurement does not depend on the terminal the
# dashboard happens to be running in -- the width is passed to wrap().
_MEASURE = Console(width=200, force_terminal=False, no_color=True)


def menu_chrome(hint: bool = True, desc: int = 0, header: int = 0) -> int:
    """The panel lines that are not item lines.

    Two borders, the menu's own hint line when it has one, the description
    line(s) reserved above it and the header line(s) under the title."""
    return 2 + (1 if hint else 0) + desc + header


def _block(text: str, width: int, cap: int = DESC_MAX) -> list[Text]:
    """`text` as at most `cap` dim, indented lines inside a panel `width` wide.

    The last line is ELLIPSISED when the text needs more, because the caller
    reserved a fixed number of lines and a block that returned more of them
    would push the hint and the border off the panel -- the very thing this
    module exists to stop."""
    room = width - 4 - len(DESC_INDENT)      # two borders, their padding, the indent
    if room < 8 or not text:
        return []
    lines = Text(text, style=DIM, no_wrap=False).wrap(_MEASURE, room,
                                                      overflow="fold")
    kept = [line for line in lines[:cap]]
    if len(lines) > cap and kept:
        # truncate(width, overflow="ellipsis") does nothing to a line that
        # already fits, so the room for the "…" is made by hand first.
        kept[-1].truncate(max(0, room - 1), overflow="crop")
        kept[-1].append("…", style=DIM)
    out = []
    for line in kept:
        line.rstrip()
        t = Text(DESC_INDENT, style=DIM, no_wrap=True, overflow="crop")
        t.append_text(line)
        t.no_wrap, t.overflow = True, "crop"
        out.append(t)
    return out


def _has_desc(it: dict) -> bool:
    """A row whose description is drawn: a separator has no cursor to sit on
    it and a disabled row already says its reason in brackets."""
    return bool(it.get("desc")) and not it.get("sep") and not it.get("disabled")


def menu_desc_lines(items: list[dict], width: int) -> int:
    """The lines this menu reserves for the row descriptions, at `width`.

    THE MAXIMUM ANY ONE ROW NEEDS, not the current row's: a reservation that
    followed the cursor would move every row of the list the moment the
    cursor crossed a two-line description. 0 when no row that can hold a
    cursor has one, which is every menu until a lane gives it some."""
    return max([len(_block(it["desc"], width)) for it in items
                if _has_desc(it)] or [0])


def menu_head_lines(header: str, width: int) -> int:
    """The lines a menu's own header takes under its title border."""
    return len(_block(header, width)) if header else 0


def modal_width(console_width: int) -> int:
    """The widest a CENTRED panel is drawn on a console this wide.

    MODAL_MAX, less the margin when the console is not much wider than it.
    Under 40 columns the margin is given back instead: this module promises a
    panel drawn at any width >= 40, prove.sh drives 40-column terminals, and
    a margin taken out of one of those comes out of the labels."""
    return max(min(MODAL_MAX, console_width - MODAL_MARGIN),
               min(console_width, 40))


def menu_needed(items: list[dict], chrome: int = CHROME) -> int:
    """Rows to draw every item with no scrolling."""
    return len(items) + chrome


def menu_viewport(n_items: int, cur: int, rows: int,
                  chrome: int = CHROME) -> tuple[int, bool, bool]:
    """The first item drawn, and whether the ▲ and ▼ marker lines are drawn.

    `rows` is the total panel height and `chrome` what of it is not items
    (menu_chrome). The window holds `rows - chrome` lines, minus one per
    marker shown; `cur` is always inside it."""
    if rows - chrome < BODY_MIN:
        raise ValueError("a menu needs at least %d rows, got %d"
                         % (chrome + BODY_MIN, rows))
    budget = rows - chrome
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
               hint: str | None = HINT, width: int | None = None,
               header: str = "", desc_rows: int | None = None,
               shrink: bool = False) -> Panel:
    """The menu as a Panel exactly `rows` lines tall at any width >= 40.

    `title` is markup, drawn as `[bold]<title>`, so a caller may add a dim
    note to it; escape a raw file or window name before passing it.

    `hint` IS THE MENU'S OWN HINT LINE -- the one inside the panel that
    add_menu's `hint_fn` fills -- and hint=None draws none and reserves none,
    which is one more item line rather than a blank one.

    `header` explains the MENU, once, under the title border. A row's own
    `desc` is drawn on the reserved line(s) just above the hint while the
    cursor is on it, and left blank on a row without one. Both are measured
    at `width`, THE WIDTH THE PANEL WILL BE DRAWN AT, so either of them
    without it is a ValueError and not a guess -- a description measured at
    the wrong width is a panel one line too tall, which is the bug this
    module exists to prevent.

    `desc_rows` overrides the reservation this would measure for itself, for
    a caller that has already measured it (place_menu, which needs the number
    to work out how many rows to ask for) or one that cannot afford it at all
    (0, on a terminal too short to hold a list AND an explanation).

    `shrink` draws the panel at its CONTENT's width, capped at `width`,
    instead of filling the console: what a centred panel wants, and what
    keeps a menu of six short rows from being a box the width of the
    screen."""
    has_text = bool(header) or any(_has_desc(it) for it in items)
    if has_text and width is None:
        raise ValueError("menu_panel needs width= to measure a description")
    head = _block(header, width) if (header and width) else []
    if desc_rows is None:
        desc_rows = menu_desc_lines(items, width) if width else 0
    chrome = menu_chrome(hint is not None, desc_rows, len(head))
    top, show_up, show_down = menu_viewport(len(items), cur, rows, chrome)
    span = rows - chrome - show_up - show_down
    shown = items[top:top + span]
    below = len(items) - top - len(shown)

    lines: list[Text] = list(head)
    body: list[Text] = []
    if show_up:
        body.append(Text("   ▲ %d more" % top, style=DIM, no_wrap=True,
                         overflow="ellipsis"))
    for i, it in enumerate(shown, start=top):
        body.append(_item_line(it, i == cur))
    if show_down:
        body.append(Text("   ▼ %d more" % below, style=DIM, no_wrap=True,
                         overflow="ellipsis"))
    # More rows than items (a caller that did not cap at menu_needed): the
    # slack goes above the description and the hint, so both always sit on
    # the border.
    body += [Text("") for _ in range(rows - chrome - len(body))]
    lines += body
    if desc_rows:
        # PADDED TO THE RESERVATION, always: the blank lines under a row with
        # no description are what stops the list moving as the cursor passes
        # over it. Sliced to it too, in case a caller passed a number smaller
        # than this row needs.
        shown_desc = _block(items[cur]["desc"], width) \
            if (0 <= cur < len(items) and _has_desc(items[cur])) else []
        lines += shown_desc[:desc_rows]
        lines += [Text("") for _ in range(desc_rows - len(shown_desc))]
    if hint is not None:
        lines.append(Text("   " + hint, style=DIM, no_wrap=True,
                          overflow="ellipsis"))
    # One Text per line in a Group, not one joined Text: overflow belongs to a
    # whole Text, and a separator is cropped where a label is ellipsised.
    markup = "[bold]" + title
    panel = Panel(Group(*lines), title=_fit_title(markup, width),
                  title_align="left", border_style=ACCENT, box=box.ROUNDED,
                  height=rows)
    if shrink and width:
        # RICH'S OWN WIDTH, not padded strings: the panel is drawn at exactly
        # this many columns, and every line in it is already no_wrap +
        # ellipsis, so a label past the cap is cut with "…" rather than
        # wrapped onto a line that would push the border off the panel.
        panel.expand = False
        panel.width = min(width, _natural(lines, markup))
    return panel


# The room a title has: the panel's width less two corners, the leading dash
# and a space either side of the title itself.
TITLE_CHROME = 6


def _fit_title(markup: str, width: int | None) -> Text | str:
    """The title, shortened FROM THE MIDDLE when the panel is too narrow.

    Rich simply cuts a title that does not fit, with nothing to say it did --
    which is how a capped settings menu came out titled ".../mxsplit.dashboa"
    and, worse, lost the "(modal: no room below)" note place_menu appends to
    say the frame degraded. Both ends of this string matter and the middle
    does not: the head names the menu, the tail names the file it writes and
    anything the caller added. So the middle goes, with the "…" that says so."""
    if width is None:
        return markup
    text = Text.from_markup(markup)
    room = width - TITLE_CHROME
    if text.cell_len <= room or room < 8:
        return text
    head = (room - 1) // 2
    out = text[:head]
    out.append("…", style=DIM)
    out.append_text(text[text.cell_len - (room - 1 - head):])
    return out


def _natural(lines: list[Text], markup: str) -> int:
    """The width a panel of these lines wants: its widest line plus the box
    and its padding, and never less than its title needs in the top border
    (two corners, the leading dash, and a space either side of the title)."""
    widest = max([line.cell_len for line in lines] or [0])
    return max(widest + 4, Text.from_markup(markup).cell_len + TITLE_CHROME)


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
