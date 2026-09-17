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

## The rules it enforces

* `bin/tmux` is `tmux -L mxsplit`, and it is first on PATH. Nothing here can
  reach the real server, `claude:0`, or any window you are working in.
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
    tests/sandbox/goldens.sh            # compare
    tests/sandbox/goldens.sh --bless    # write tests/goldens/ (phase 0 only)

`SB` defaults to `${TMPDIR:-/tmp}/muxsplit-sandbox`; set it to put the fake
machine somewhere else.
