#!/usr/bin/env python3
"""decode_key -- the dashboard's key reader, byte for byte.

Run it:  .venv/bin/python tests/test_decode_key.py   (no pytest; needs rich)

Its docstring has claimed since the split that it is "pure, so the key
handling is testable", and until this file nothing tested it. What it got
wrong is what this table is for: it read only the FINAL byte and mapped four
of them, so every other escape sequence -- PageUp, PageDown, Home, End, F5,
Insert, Delete, shift-Tab, a mouse report, a bracketed paste -- came back as
"\\x1b", a bare Escape, which is the views' own "leave this screen" key. The
reported bug is one line of the table below; the rest of them were the same
bug wearing another key's name.

THE SEQUENCES ARE MEASURED, not copied out of a terminfo page. Captured on
this machine with tmux 3.5a driving a pane at TERM=tmux-256color (which is
what tmux.conf sets, and therefore what the dashboard actually reads) and
cross-checked against xterm-256color's terminfo for the SS3 forms a
dashboard started outside tmux sees:

    key         tmux-256color   xterm-256color   others kept working
    PageUp      ESC [ 5 ~       ESC [ 5 ~
    PageDown    ESC [ 6 ~       ESC [ 6 ~
    Home        ESC [ 1 ~       ESC O H          ESC [ H, ESC [ 7 ~ (rxvt)
    End         ESC [ 4 ~       ESC O F          ESC [ F, ESC [ 8 ~ (rxvt)
    ctrl-Home   ESC [ 1 ; 5 H   ESC [ 1 ; 5 H
    F5          ESC [ 1 5 ~     ESC [ 1 5 ~
    Insert      ESC [ 2 ~       ESC [ 2 ~
    Delete      ESC [ 3 ~       ESC [ 3 ~
    shift-Tab   ESC [ Z         ESC [ Z

`~` is shared by Home, End, PageUp, PageDown, Insert, Delete and twelve F
keys, which is why the PARAMETER and not the final byte has to be read.
"""
import os
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import deck_status as d                   # noqa: E402

FAILS = 0
PASSES = 0


def check(cond, what):
    global FAILS, PASSES
    if cond:
        PASSES += 1
        print("  ok   %s" % what)
    else:
        FAILS += 1
        print("  FAIL %s" % what)


def decodes(data, want, why=""):
    got = d.decode_key(data)
    check(got == want, "%-16r -> %-8r %s%s"
          % (data, want, why, "" if got == want else "  (got %r)" % got))


print("== the four keys the user asked for, in every form a terminal sends")
# tmux-256color, which is what the dashboard is read through: measured.
decodes(b"\x1b[5~", "PGUP", "PageUp, tmux")
decodes(b"\x1b[6~", "PGDN", "PageDown, tmux")
decodes(b"\x1b[1~", "HOME", "Home, tmux")
decodes(b"\x1b[4~", "END", "End, tmux")
# xterm/vt100 SS3, which is what a dashboard started OUTSIDE tmux reads.
decodes(b"\x1bOH", "HOME", "Home, xterm SS3")
decodes(b"\x1bOF", "END", "End, xterm SS3")
# CSI final-byte, the linux console and several others.
decodes(b"\x1b[H", "HOME", "Home, CSI")
decodes(b"\x1b[F", "END", "End, CSI")
# rxvt.
decodes(b"\x1b[7~", "HOME", "Home, rxvt")
decodes(b"\x1b[8~", "END", "End, rxvt")

print("== modified variants still name the key, as modified arrows already did")
decodes(b"\x1b[1;5H", "HOME", "ctrl-Home (measured)")
decodes(b"\x1b[1;2H", "HOME", "shift-Home (measured)")
decodes(b"\x1b[1;5F", "END", "ctrl-End")
decodes(b"\x1b[5;5~", "PGUP", "ctrl-PageUp")
decodes(b"\x1b[6;2~", "PGDN", "shift-PageDown")

print("== the arrows, which must not have moved")
for seq, want in ((b"\x1b[A", "UP"), (b"\x1b[B", "DOWN"),
                  (b"\x1b[C", "RIGHT"), (b"\x1b[D", "LEFT"),
                  (b"\x1bOA", "UP"), (b"\x1bOB", "DOWN"),
                  (b"\x1b[1;5A", "UP"), (b"\x1b[1;2D", "LEFT")):
    decodes(seq, want)

print("== AN UNKNOWN ESCAPE SEQUENCE IS IGNORED, NOT ESCAPE")
# This is the same bug as the reported one. Every line here used to come back
# as "\x1b" and therefore QUIT the schedule view, the handovers tab and the
# insights screen -- the user has been hitting it without a name for it.
for seq, why in ((b"\x1b[15~", "F5"), (b"\x1b[17~", "F6"),
                 (b"\x1b[24~", "F12"), (b"\x1b[2~", "Insert"),
                 (b"\x1b[3~", "Delete"), (b"\x1b[Z", "shift-Tab"),
                 (b"\x1b[200~", "bracketed paste start"),
                 (b"\x1b[201~", "bracketed paste end"),
                 (b"\x1b[M ! !", "an X10 mouse report"),
                 (b"\x1b[3;5~", "ctrl-Delete"),
                 (b"\x1b[?1;2c", "a device attributes reply")):
    decodes(seq, d.IGNORED, why)
check(d.IGNORED != "\x1b", "and IGNORED is not Escape, which is the whole point")

print("== a BARE Escape is still Escape -- it does not go through the CSI branch")
decodes(b"\x1b", "\x1b", "the key that leaves a view")
decodes(b"\x1ba", "\x1b", "alt-a: the first byte, exactly as before")

print("== ordinary keys are untouched")
for seq, want in ((b"q", "q"), (b" ", " "), (b"\r", "\r"), (b"\n", "\n"),
                  (b"\x7f", "\x7f"), (b"", "")):
    decodes(seq, want)
# AND ONE THING THIS CHANGE DID NOT FIX, written down so it is a known
# limitation rather than a surprise: a multi-byte character comes back as
# data[:1] decoded with "replace", so é (two bytes) is one replacement
# character. It has always done that, it is what makes "one read, one key"
# true, and the only place it shows is a text prompt -- a window name typed
# with an accent in it. Out of this lane's scope; recorded here.
decodes(b"\xc3\xa9", "\ufffd", "é: the first byte only, unchanged behaviour")

print("== a half-finished sequence is not an Escape either")
decodes(b"\x1b[", d.IGNORED, "the 250ms ran out holding a CSI prefix")
decodes(b"\x1bO", d.IGNORED, "...or an SS3 one")
decodes(b"\x1b[1;", d.IGNORED, "...or half the parameters")

print("== _complete_key: what read_key keeps waiting for")
for data, whole in ((b"\x1b", False), (b"\x1b[", False), (b"\x1bO", False),
                    (b"\x1b[5", False), (b"\x1b[1;", False), (b"\x1b[1;5", False),
                    (b"\x1b[5~", True), (b"\x1b[A", True), (b"\x1bOH", True),
                    (b"\x1b[1;5H", True), (b"q", True)):
    check(d._complete_key(data) is whole,
          "%-10r is %s" % (data, "whole" if whole else "still a prefix"))

print("== A SPLIT READ: the bytes arrive in two chunks, through a real pipe")
# read_key's own loop, not a reimplementation of it: sys.stdin is pointed at
# the read end of a pipe, which has a fileno and selects like a tty.


def through_pipe(chunks, gap=0.04, timeout=1.0):
    """Feed `chunks` to read_key with `gap` seconds between them."""
    r, w = os.pipe()
    saved = sys.stdin
    sys.stdin = os.fdopen(r, "rb", buffering=0)

    def feed():
        for i, c in enumerate(chunks):
            if i:
                time.sleep(gap)
            os.write(w, c)

    t = threading.Thread(target=feed)
    t.start()
    try:
        return d.read_key(timeout)
    finally:
        t.join()
        os.close(w)
        sys.stdin.close()
        sys.stdin = saved


check(through_pipe([b"\x1b[", b"5~"]) == "PGUP",
      "ESC [ then 5 ~ is one PageUp, not an Escape and two junk keys")
check(through_pipe([b"\x1b", b"[6~"]) == "PGDN",
      "ESC then [ 6 ~ is one PageDown")
check(through_pipe([b"\x1b", b"[", b"1", b";", b"5", b"H"]) == "HOME",
      "six chunks still make one ctrl-Home")
check(through_pipe([b"\x1b[4~"]) == "END", "and one chunk is the easy case")
check(through_pipe([b"\x1b"]) == "\x1b",
      "a lone ESC that never grows is still Escape (after ESC_TIME)")

# ------------------------------------------------------------ the two budgets
# esc is the most pressed key on the dashboard -- it leaves every view and
# opens the muxtopus menu -- and it used to take the FULL 250ms sequence
# budget to resolve, because a lone ESC is a prefix. It now has its own,
# shorter one; a sequence that has actually started keeps the generous budget.
t0 = time.time()
k = through_pipe([b"\x1b"])
esc_ms = (time.time() - t0) * 1000
check(k == "\x1b", "a lone ESC is Escape")
check(esc_ms < 200,
      "...and resolves in well under the old 250ms (took %.0fms)" % esc_ms)
check(esc_ms >= d.ESC_TIME * 1000 * 0.5,
      "...but does wait long enough for a tail to arrive (%.0fms)" % esc_ms)

t0 = time.time()
k = through_pipe([b"\x1b[A"])
arrow_ms = (time.time() - t0) * 1000
check(k == "UP", "an arrow delivered in one write is an arrow")
check(arrow_ms < 50,
      "...and costs no wait at all, the usual case (%.1fms)" % arrow_ms)

# A tail that arrives INSIDE the ambiguity window is still a sequence.
check(through_pipe([b"\x1b", b"[A"], gap=d.ESC_TIME / 2) == "UP",
      "ESC and its tail split by half the budget still decode as one arrow")
# ...and once "ESC [" is in hand there is no ambiguity left, so a slow tail
# has the full 250ms, well past ESC_TIME.
check(through_pipe([b"\x1b[", b"A"], gap=d.ESC_TIME * 1.5) == "UP",
      "a sequence already begun keeps the generous budget for its tail")
check(through_pipe([b"\x1b["]) == d.IGNORED,
      "a lone ESC [ that never grows is IGNORED, not Escape")
check(through_pipe([b"q"]) == "q", "an ordinary key does not wait at all")
check(through_pipe([], timeout=0.05) is None, "nothing typed: None")

print()
print("%d assertions passed" % PASSES if not FAILS
      else "%d passed, %d FAILED" % (PASSES, FAILS))
sys.exit(1 if FAILS else 0)
