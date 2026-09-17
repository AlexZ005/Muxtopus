# tests/sandbox -- the dashboard, driven

A whole fake machine for `deck_status.py`: its own HOME, XDG dirs, muxtopus
config, watchdog state and tmux server, so the dashboard can be started,
typed at and photographed without touching the real one.

It exists because the dashboard is a full-screen curses-ish program whose
output is a picture. There is no other way to prove that a 3700-line file
split into a package draws the same picture: you take the picture first.

    env.sh          every path in one place; sourced by every other script
    setup.sh        build the fixture machine from tests/fixtures/dashboard/
    start.sh [H]    start the sandbox tmux server and the dashboard, H rows
    k.sh <keys>     send-keys, then wait a frame
    type.sh <str>   type a string ONE KEY PER WRITE (read_key takes one per read)
    cap.sh          capture-pane the dashboard, trailing space stripped
    clean.sh        reset the mutable half between phases
    assert_menu.py  a capture holds a whole, unclipped menu
    normalise.py    mask what the machine decides; see its docstring
    route.sh        THE ROUTE: every screen, captured and normalised
    goldens.sh      route -> compare against tests/goldens/ (or --bless)
    actions.sh      the rows that WRITE something, fired and checked
    moved.py        where every pre-split definition went, and was it changed
    mkledger.py     a synthetic stats ledger, anchored on TODAY
    insights.sh     the `i` view, driven: every key, at 24/40/58 rows
    handovers.sh    the handovers TAB of `s`: rows, states, viewport

## The goldens are pictures; two things they cannot see

`goldens.sh` proves what the dashboard DRAWS along a route somebody thought
to press. Two checks cover what that leaves:

* `actions.sh` presses enter on the rows that write something -- schedule a
  resume, wind a window down, opt one out, duplicate, launch now, delete,
  save the options table -- and looks at the files afterwards. It navigates
  by LOOKING for the row it wants, never by counting Downs, because the
  mover skips separators and a later phase may move one.
* `insights.sh` presses every key the insights view claims and asserts what
  the screen then says, rather than comparing it with a golden: that screen's
  title carries today's date and its periods are "today" and "this week", so a
  golden taken on Tuesday would fail on Wednesday. `mkledger.py` writes its
  ledger against today for the same reason. What the FIGURES say is
  `tests/test_stats.py`'s subject — hand-computed, from rows.
* `handovers.sh` drives the second tab of `s`. Most of what it proves is a
  fact about ONE ROW -- its state, whether its window is still open, how many
  pending entries it holds up -- which a reader of a 40-line golden cannot
  see is being tested. It also carries `scap`, a settled capture: a read that
  lands inside Live's repaint comes back MISSING A LINE (measured: the
  cursor's row), so it takes captures until two agree.
* `tests/test_names.py` (a plain python test, also in CI) checks that every
  global name the code mentions is one it can reach. The split moved two
  methods into a module whose import list was missing a constant they used,
  on paths no route walks, and the 148 captures were green through both.

## The rules it enforces

* `bin/tmux` is `tmux -L "$SANDBOX_SOCKET"` (`mxsplit`), and it is first on
  PATH. Nothing here can reach the real server, `claude:0`, or any window
  you are working in.
* `bin/claude` is a fake that writes a session file and sleeps.
* `CLAUDE_CONFIG_DIR` names a sandbox-only account (`mxsplit`), so the
  dashboard's account suffix, its tmux session name and its watchdog state
  directory are all ones nothing else uses -- AND the lanes table, which reads
  the real /proc, finds no dev server belonging to this account. That is what
  makes the frame reproducible on a machine with servers running.
* Every deletion lives in `clean.sh` and goes through `"${SB:?}"`. Never
  `rm $VAR/...` inline (the habit the dash-menus lane was asked to fix).

## Running it

    tests/sandbox/setup.sh
    tests/sandbox/insights.sh           # the i view
    tests/sandbox/handovers.sh          # the handovers tab of s
    tests/sandbox/goldens.sh            # compare
    tests/sandbox/goldens.sh --bless    # write tests/goldens/ (phase 0 only)

`SB` defaults to `${TMPDIR:-/tmp}/muxsplit-sandbox`; set it to put the fake
machine somewhere else -- but **give it the same length** (21 characters), or
the goldens differ on every line that names it: `normalise.py` masks the path
to `<SB>`, which hides its text and not its width. `SANDBOX_SOCKET` and
`SANDBOX_SESSION` move the tmux server and session the same way, which is how
two lanes run this harness at once without `stop.sh` killing each other's
dashboard -- `tests/sandbox/notify.sh` runs as `mxnotifydash`.
