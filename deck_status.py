#!/usr/bin/env python3
"""deck_status.py -- THE SHELL of the muxtopus dashboard.

What is left in this file is what only a program with a terminal can do:
argv, the console, Rich's Live, the raw-mode key reader, the main loop, the
four full-screen hand-offs (the editor, the pager, btop, the help screen) and
the reload and quit that need the saved terminal state. Everything that DRAWS
is in the `dashboard/` package beside it.

NO FILE NAMES THE MODULES. load_modules() walks dashboard.views and
dashboard.menus, so adding a view is adding a file -- which is the whole
point of the exercise: three lanes were queued on this one file, and none of
them has to open it now. A module that fails to import is skipped with a red
notice and the dashboard runs without it, so one lane's bad commit cannot
take down the screen the others are tested in.

docs/dashboard-views.md is the protocol, the registries and the routing rule;
dashboard/data.py carries the frame's measured cost, because that is where
the collectors ended up.

Entry point is deck-status.sh, which falls back to its own bash renderer if
this interpreter or rich is unavailable. The dashboard must never be the
broken thing.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import select
import subprocess
import sys
import termios
import time
import tty

from rich.console import Console
from rich.live import Live
from rich.text import Text

import dashboard.menus
import dashboard.views
from dashboard.app import App
from dashboard.core import DIM, FRAME_INTERVAL
from dashboard.data import refresh_usage, toggle_monitor, toggle_watchdog
import dashboard.help

# RE-EXPORTS, and the only reason they are here: tests/test_entry_options.py
# does `import deck_status as d` and calls d.read_options, d.options_line,
# d.options_section, d.options_fields, d.parse_options_line and
# d.rewrite_options. That test passing UNCHANGED across the whole split is one
# of the proofs that the split changed no behaviour, so this list is not to be
# pruned for being unused here -- being unused here is rather the point.
from dashboard.core import read_options                          # noqa: F401
from dashboard.schedules import (options_fields, options_line,   # noqa: F401
                                 options_section, parse_options_line,
                                 rewrite_options)


def load_modules(app: App) -> None:
    """Import every module under dashboard.views and dashboard.menus and let
    each one register itself.

    SORTED BY NAME, so a bug is reproducible; nothing about the RESULT is
    allowed to depend on that order, which is why App.add_rows breaks its ties
    by label. A module that fails is skipped loudly and everything else still
    loads.
    """
    for pkg in (dashboard.views, dashboard.menus):
        for info in sorted(pkgutil.iter_modules(pkg.__path__),
                           key=lambda m: m.name):
            name = "%s.%s" % (pkg.__name__, info.name)
            short = name[len("dashboard."):]
            try:
                mod = importlib.import_module(name)
            except Exception as exc:                           # noqa: BLE001
                app.module_failed(short, exc)
                continue
            register = getattr(mod, "register", None)
            if register is None:
                continue
            try:
                register(app)
            except Exception as exc:                           # noqa: BLE001
                app.module_failed(short, exc)


def read_key(timeout: float) -> str | None:
    """One keypress, with the arrows decoded.

    READ THE FILE DESCRIPTOR, NOT sys.stdin, and that is the whole point of
    this function. An arrow is the three bytes ESC [ A delivered in a single
    write. sys.stdin is buffered, so the first read(1) pulls all three into
    Python's buffer and hands back one -- after which select() on the fd
    correctly reports NOTHING left to read, because the remaining two are in
    userspace, not the kernel. The previous version then gave up and returned a
    bare Escape, so arrows silently did nothing while every plain key worked.

    os.read has no such buffer: one read takes the whole sequence, and a
    sequence split across writes is picked up by the short second poll.
    """
    fd = sys.stdin.fileno()
    if not select.select([fd], [], [], timeout)[0]:
        return None
    try:
        data = os.read(fd, 16)
    except OSError:
        return None
    if not data:
        return None

    # COMPLETE A SPLIT ESCAPE SEQUENCE. 50ms was the old budget, which is
    # generous on a local tty and tight over ssh: when ESC and "[A" arrive in
    # separate reads the sequence was abandoned as a bare Escape and the "["
    # and "A" were then consumed as two further junk keypresses -- so the arrow
    # did nothing and ate the two presses after it. Keep reading while what we
    # hold is a prefix rather than a whole sequence.
    deadline = time.time() + 0.25
    while data.startswith(b"\x1b") and not _complete_key(data):
        left = deadline - time.time()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            break
        try:
            more = os.read(fd, 16)
        except OSError:
            break
        if not more:
            break
        data += more
    return decode_key(data)


def _complete_key(data: bytes) -> bool:
    """Is this a whole sequence, or still a prefix waiting for its tail?"""
    if not data.startswith(b"\x1b"):
        return True
    if data == b"\x1b" or data == b"\x1b[" or data == b"\x1bO":
        return False
    if data.startswith((b"\x1b[", b"\x1bO")):
        # A CSI/SS3 sequence ends at its first final byte (@ through ~).
        return any(0x40 <= b <= 0x7E for b in data[2:])
    return True


def decode_key(data: bytes) -> str:
    """Bytes to a key name. Pure, so the arrow handling is testable."""
    if data.startswith((b"\x1b[", b"\x1bO")):
        for b in data[2:]:
            if 0x40 <= b <= 0x7E:
                # Final byte identifies the key; anything between is a
                # modifier parameter (ESC [ 1 ; 5 A is ctrl-up), and a
                # modified arrow should still move the cursor.
                return {0x41: "UP", 0x42: "DOWN",
                        0x43: "RIGHT", 0x44: "LEFT"}.get(b, "\x1b")
        return "\x1b"
    return data[:1].decode("utf-8", "replace")


def main() -> int:
    interval = FRAME_INTERVAL
    args = sys.argv[1:]
    if "--int" in args:
        try:
            interval = float(args[args.index("--int") + 1])
        except (IndexError, ValueError):
            pass
    once = "--once" in args

    console = Console()
    dash = App(interval, console)
    # The shell's own two help sections -- the title and the last line -- and
    # then everything else, from whatever modules are there to be found.
    dashboard.help.register(dash)
    load_modules(dash)

    if once or not sys.stdout.isatty():
        dash.build()          # prime the CPU deltas so the frame is real
        time.sleep(0.12)
        console.print(dash.build())
        return 0

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        dash.build()          # prime
        with Live(dash.build(), console=console, screen=True,
                  auto_refresh=False, transient=False) as live:
            while True:
                live.update(dash.build(), refresh=True)

                # A requested file edit suspends the whole display into a real
                # editor (the btop pattern). Fallback is nano: $EDITOR is
                # empty over ssh on the deck.
                if dash.pending_edit:
                    path, dash.pending_edit = dash.pending_edit, None
                    live.stop()
                    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                    subprocess.run([os.environ.get("EDITOR") or "nano", path])
                    tty.setcbreak(fd)
                    live.start()
                    continue

                if dash.pending_quit:
                    break
                if dash.pending_reload:
                    # A running process holds the copy it started with; re-exec
                    # so an edited script takes effect without respawning tmux.
                    # Also nudge the limits, but through --ensure: a reload is
                    # not a reason to start a probe if the figures are minutes
                    # old, and R gets pressed a lot while editing.
                    refresh_usage()
                    live.stop()
                    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                    os.execv(sys.executable, [sys.executable, __file__] + args)

                # A --check report takes the terminal over the way the
                # editor does: through less when there is one (the report is
                # longer than a screen, and the top is the useful half),
                # printed plainly otherwise.
                if dash.pending_report is not None:
                    text, dash.pending_report = dash.pending_report, None
                    live.stop()
                    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                    if os.path.exists("/usr/bin/less"):
                        subprocess.run(["/usr/bin/less", "-R"], input=text, text=True)
                    else:
                        console.clear()
                        console.print(Text(text))
                        console.print(Text("press any key", style=DIM))
                        tty.setcbreak(fd)
                        read_key(120)
                    tty.setcbreak(fd)
                    live.start()
                    continue

                key = read_key(interval)

                # THE ONE ROUTING RULE, and its first three steps are the
                # App's: a submode (prompt, confirm, picker, or a view's own
                # modal) owns the keyboard while it is open -- q included,
                # because typing a window name with a "q" in it must not quit
                # the dashboard -- then an open menu, then the ACTIVE VIEW.
                if dash.route_key(key):
                    continue

                # THE SHELL'S OWN, reachable from every view. q, R, ? and p
                # need this function's Live and its saved terminal state, and
                # u, U, w and m are about the account and the fleet rather
                # than about any one screen.
                if key in ("q", "Q"):
                    break
                if key == "R":
                    dash.pending_reload = True
                    continue
                if key == "?":
                    live.stop()
                    console.clear()
                    console.print(dash.help_screen())
                    read_key(60)
                    live.start()
                elif key in ("p", "P"):
                    live.stop()
                    termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                    subprocess.run(["btop"] if os.path.exists("/usr/bin/btop") else ["htop"])
                    tty.setcbreak(fd)
                    live.start()
                elif key == "u":
                    dash.say(refresh_usage())
                elif key == "U":
                    dash.say(refresh_usage(force=True))
                elif key in ("w", "W"):
                    dash.say(toggle_watchdog())
                elif key in ("m", "M"):
                    dash.say(toggle_monitor())
                elif key == "f":
                    # THE ONE KEY WHOSE HOME IS ARGUABLE. f filters the main
                    # view's lanes table, so it ought to be that view's key --
                    # but it was reachable from the schedule view before the
                    # split, because it sat in this chain, and the split is
                    # not the place to decide it should not be. Whoever adds
                    # the third view gets to settle it.
                    main_view = dash.view_of("main")
                    dash.say(main_view.toggle_lanes() if main_view
                             else "the main view failed to load")
                else:
                    # LAST: a key that opens a view. The schedule view's own
                    # s and esc took it back to main above, so this only ever
                    # opens one. Stopping/starting desktop extras moved onto
                    # the cursor: arrow past the sessions, enter.
                    dash.open_view_key(key)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return 0


if __name__ == "__main__":
    sys.exit(main())
