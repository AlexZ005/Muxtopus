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
