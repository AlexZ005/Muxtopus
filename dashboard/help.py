"""dashboard.help -- the shell's own two slices of `?`, and nothing else.

`?` is assembled from what the LOADED MODULES say about themselves
(App.add_help / App.help_screen). These two are the shell's: the title with
the keys the shell itself owns, and the line at the bottom. Every other
section lives in the module whose screen it describes -- the window tree with
the main view, the options table with the schedule view, and so on.

They keep the ORDER they had when this was one 290-line string, so the help
screen reads exactly as it did. The split moved who owns the words.

THE THIRD IS NEW AND IS ALSO THE SHELL'S: PageUp, PageDown, Home and End are
decoded by deck_status.decode_key and work in EVERY list on this dashboard,
so they belong to no one screen. They are one section here rather than a line
repeated in five.
"""
from dashboard.core import DIM

# The manual is docs/ in the checkout, published by GitHub Pages; the README
# and the repo homepage point at the same address.
MANUAL_URL = "https://alexz005.github.io/Muxtopus/"

HELP_INTRO = f"""
  [bold]deck-status[/] -- lane dashboard

  [bold]q[/] quit        [bold]r[/] redraw now      [bold]R[/] reload this script
  [bold]s[/] scheduled windows      [bold]enter[/] on the extras row stops/starts them
  [bold]w[/] watchdog    [bold]m[/] monitoring      [bold]p[/] btop   [bold]?[/] this screen
  [bold]u[/] read usage limits      [bold]up/down[/] pick   [bold]space[/] menu   [bold]esc[/] muxtopus menu
  [bold]pgup/pgdn[/] one screenful    [bold]home/end[/] first / last -- in every list
  [bold]c[/] a new claude session (folder, model, effort, mode, where, name, first prompt)
  [bold]enter[/] open the selected session's window (Ctrl-b 0 comes back here)
  [bold]f[/] lanes: this account only / every account
  [bold]←/→[/] fold / unfold a subtree      [bold]t[/] tree ordering on / off
"""

HELP_PAGING = f"""
  [bold]pgup[/] / [bold]pgdn[/] move the cursor ONE SCREENFUL -- the rows that list
  is actually showing, so it is fewer on a short terminal -- and [bold]home[/] /
  [bold]end[/] jump to the first and the last row. Both CLAMP: pgup at the top is
  the first row, not a wrap to the bottom.

  They work in the sessions list, the schedules table, the handovers tab, the
  insights breakdown, every menu, the options table and the pickers. In a
  menu and in the options table they skip the headings and the separators,
  exactly as the arrows do.

  [{DIM}]These four used to decode to a bare Escape, which is this screen's
  "leave" key: pressing End in the schedule view left the schedule view. So do
  F5, Insert, Delete and shift-Tab -- an escape sequence the dashboard cannot
  name is now ignored instead of being read as Escape.[/]
"""

HELP_FOOT = f"""
  [{DIM}]The manual, with every screen and field: {MANUAL_URL}[/]
  [{DIM}]press any key[/]
"""

def register(app) -> None:
    app.add_help("", HELP_INTRO, order=0)
    app.add_help("PAGING A LIST (pgup/pgdn, home/end)", HELP_PAGING, order=14)
    app.add_help("", HELP_FOOT, order=100)
