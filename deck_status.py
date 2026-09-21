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


# How long a LONE ESC waits to see whether it is really the head of an arrow.
#
# 100ms, AND THE NUMBER IS A COMPROMISE BETWEEN TWO MEASUREMENTS, both made
# on this project:
#
#   * 250ms (what this was) is plainly laggy on the key pressed most -- esc
#     leaves every view and opens the muxtopus menu, and a quarter second of
#     nothing after it reads as a dashboard that did not hear the keypress.
#   * 50ms was tried here before and recorded as TOO TIGHT OVER SSH: ESC and
#     its tail arrived in separate reads, the sequence was abandoned, and the
#     arrow did nothing while eating the two presses after it.
#
# So: comfortably above the split that was actually observed, and below the
# ~150ms where a delay stops reading as instant. The overwhelming case is not
# a race at all -- a terminal writes ESC [ A in ONE write, so the tail is
# already in the kernel buffer and this budget is never spent.
#
# OVERRIDABLE, because the machine this can still be wrong on is a slow link:
# MUXTOPUS_ESC_TIME=0.25 restores the old behaviour, 0.02 suits a local tty.
# Clamped, so a typo cannot make Escape unusable in either direction.
try:
    ESC_TIME = min(0.5, max(0.005, float(os.environ.get("MUXTOPUS_ESC_TIME") or 0.10)))
except ValueError:
    ESC_TIME = 0.10


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
    #
    # TWO BUDGETS, because the two waits are not the same question.
    #
    # A LONE ESC is ambiguous: it is either the Escape key or the first byte
    # of a sequence whose tail has not arrived. Waiting 250ms to find out made
    # Escape itself feel broken -- esc is how every view is left and how the
    # muxtopus menu is opened, so a quarter second of nothing on the most
    # pressed key on the dashboard is the one delay everybody notices. A
    # terminal writes ESC [ A in a SINGLE write, so the tail is already in the
    # kernel buffer in the overwhelming case and ESC_TIME only has to cover a
    # packet boundary that split it. 40ms is the same order as tmux's
    # escape-time and vim's ttimeoutlen, and is below what a keypress feels.
    #
    # ONCE WE HOLD "ESC [" OR "ESC O" there is no ambiguity left -- that is a
    # sequence, and the only question is how long its tail takes -- so the
    # generous budget stays exactly where it was earned.
    esc_time = ESC_TIME if data == b"\x1b" else 0.25
    deadline = time.time() + esc_time
    while data.startswith(b"\x1b") and not _complete_key(data):
        left = deadline - time.time()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            break
        # The tail arrived: this is a real sequence, so allow the full budget
        # for the rest of it rather than the short ambiguity window.
        deadline = max(deadline, time.time() + 0.25)
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


# WHAT A FINAL BYTE NAMES, when the sequence is ESC [ <params> <final> or
# ESC O <final>. Home and End have a final-byte form (xterm's SS3 `ESC O H`,
# and `ESC [ 1 ; 5 H` for a MODIFIED Home, which every terminal measured here
# sends whatever it sends unmodified) as well as the `~` form below.
_FINAL_KEYS = {0x41: "UP", 0x42: "DOWN", 0x43: "RIGHT", 0x44: "LEFT",
               0x48: "HOME", 0x46: "END"}

# AND WHAT THE FIRST PARAMETER NAMES when the final byte is `~`, which is
# shared by a dozen keys -- so the parameter, not the final byte, is what
# tells PageUp from F5. Measured on this machine (tmux 3.5a, TERM
# tmux-256color): PageUp ESC[5~, PageDown ESC[6~, Home ESC[1~, End ESC[4~;
# 7 and 8 are the rxvt Home/End, and 2 (Insert), 3 (Delete), 11-24 (the F
# keys) and 200/201 (bracketed paste) are deliberately absent -- they are
# IGNORED, which is the point of this table being a whitelist.
_TILDE_KEYS = {1: "HOME", 4: "END", 5: "PGUP", 6: "PGDN", 7: "HOME", 8: "END"}

# An escape sequence this dashboard has no name for. NOT "\x1b": a bare
# Escape is the views' own "leave this screen"/"open the muxtopus menu" key,
# so decoding F5, Insert, Delete, shift-Tab or a mouse report as Escape made
# every one of them quit the schedule view. "" is a key every caller ignores
# -- route_key, the submodes and each view's on_key all fall through it --
# and a key that does nothing is the only honest answer for one we cannot
# name. A BARE ESC byte does not come through here: it never enters the CSI
# branch, and still decodes to "\x1b".
IGNORED = ""


def decode_key(data: bytes) -> str:
    """Bytes to a key name. Pure, so the key handling is testable."""
    if data.startswith((b"\x1b[", b"\x1bO")):
        body = data[2:]
        for i, b in enumerate(body):
            if 0x40 <= b <= 0x7E:
                # The first final byte ends the sequence; everything before
                # it is the parameters (ESC [ 1 ; 5 A is ctrl-up), and a
                # modified arrow should still move the cursor.
                if b == 0x7E:
                    head = body[:i].split(b";")[0]
                    try:
                        return _TILDE_KEYS.get(int(head), IGNORED)
                    except ValueError:
                        return IGNORED
                return _FINAL_KEYS.get(b, IGNORED)
        # A PREFIX THAT NEVER FINISHED -- the 250ms in read_key ran out
        # holding "ESC [". Half a sequence is not an Escape either.
        return IGNORED
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
