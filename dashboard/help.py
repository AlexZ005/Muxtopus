"""dashboard.help -- the shell's own two slices of `?`, and nothing else.

`?` is assembled from what the LOADED MODULES say about themselves
(App.add_help / App.help_screen). These two are the shell's: the title with
the keys the shell itself owns, and the line at the bottom. Every other
section lives in the module whose screen it describes -- the window tree with
the main view, the options table with the schedule view, and so on.

They keep the ORDER they had when this was one 290-line string, so the help
screen reads exactly as it did. The split moved who owns the words.
"""
from dashboard.core import DIM

HELP_INTRO = f"""
  [bold]deck-status[/] -- lane dashboard

  [bold]q[/] quit        [bold]r[/] redraw now      [bold]R[/] reload this script
  [bold]s[/] scheduled windows      [bold]enter[/] on the extras row stops/starts them
  [bold]w[/] watchdog    [bold]m[/] monitoring      [bold]p[/] btop   [bold]?[/] this screen
  [bold]u[/] read usage limits      [bold]up/down[/] pick   [bold]space[/] menu   [bold]esc[/] muxtopus menu
  [bold]c[/] a new claude session (folder, model, effort, mode, where, name, first prompt)
  [bold]enter[/] open the selected session's window (Ctrl-b 0 comes back here)
  [bold]f[/] lanes: this account only / every account
  [bold]←/→[/] fold / unfold a subtree      [bold]t[/] tree ordering on / off
"""

HELP_FOOT = f"""
  [{DIM}]press any key[/]
"""

def register(app) -> None:
    app.add_help("", HELP_INTRO, order=0)
    app.add_help("", HELP_FOOT, order=100)
