#!/usr/bin/env python3
"""Mask what the MACHINE decides, so two runs of the same route agree.

A golden is a picture of the dashboard. Most of that picture comes from the
fake machine in tests/fixtures/dashboard/ and is therefore fixed. Three
panels are not: `deck` (memory, cpu, temperature, battery, uptime), `lanes`
(the real /proc, which has whatever dev servers happen to be running) and
`system` (process counts, free disk). Those read the host and cannot be
faked without faking /proc.

SO THE MASKS ARE PART OF THE TEST, and they are these -- reviewed once, here,
rather than one regex at a time wherever a diff turned up:

  1. The interior of `deck`, `lanes` and `system` collapses to ONE marker
     line. Not a per-line mask: the number of rows in `lanes` is itself the
     host's answer (how many dev servers exist), and `f` shows every
     account's. What is still proven about those panels is that they are
     drawn, in that order, with their titles.
  2. Numbers in those three panels' TITLES are masked (`0 server(s)`,
     `8 hidden`, `1.1 GB`) -- the titles themselves are not. AND THE UNIT
     BESIDE A MASKED NUMBER, because human_mb prints MB under 1024 and GB
     above: the lanes title reads `<n> MB` on a machine whose dev servers
     hold 950 MB and `<n> GB` on the same machine an hour later. Masking the
     digits and not the unit hid half of one host fact, and a golden taken at
     1.1 GB failed on the machine that took it once a server exited.
  3. Everywhere else, only genuinely moving things:
       the watchdog scan age       scan 3s ago   -> scan <age> ago
       the usage read clock        read 08:40    -> read <time>
       a "N minutes ago" age       (12m ago)     -> (<age> ago)
       a written timestamp         2026-09-17 23:41 -> <stamp>
       the sandbox root            /tmp/muxsplit-sandbox -> <SB>
     An IDLE column age is NOT masked: it comes from the fixture's own
     integer, so it is fixed, and masking it would hide a real change.
  4. THE FILL BEFORE A BORDER, on a line a mask touched, and only there. A
     panel pads its content to a fixed width, so replacing a 3-character age
     with a 5-character token leaves the padding one space short of where the
     same line's padding lands when the age is 2 characters -- the border
     moves and two runs disagree about a line neither of them decided. The
     run of spaces (or of box-drawing fill) before the closing border becomes
     `<pad>` on those lines, and on no others.

Everything else is compared byte for byte. If a later phase needs a new mask,
that is a claim that the refactor made something non-deterministic, and it
belongs in the commit message before it belongs in this file.

    normalise.py <file>...     rewrites each file in place
"""
from __future__ import annotations

import os
import re
import sys

# The three panels whose interior is the host's answer, not the fixture's.
MACHINE_PANELS = ("deck", "lanes", "system")

SB = os.environ.get("SB", "")

NUM = re.compile(r"\d+(?:\.\d+)?")
# The unit that follows a number this file just masked, in a machine panel's
# title. Only there: an MB elsewhere on the screen is the fixture's.
UNIT = re.compile(r"(<n>) (MB|GB)\b")
SUBS = (
    (re.compile(r"scan \d+[smhd] ago"), "scan <age> ago"),
    (re.compile(r"read \d{1,2}:\d{2}"), "read <time>"),
    (re.compile(r"\(\d+[smhd] ago\)"), "(<age> ago)"),
    # The age of the lane's handover file, which is its mtime and therefore
    # the clock: the fixture is copied into the fake machine at setup.
    (re.compile(r"handover (open|done), \d+[smhd] ago"), r"handover \1, <age> ago"),
    (re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?"), "<stamp>"),
    # The create flow names its file after the wall clock before anything is
    # written; the title of the options table carries that name.
    (re.compile(r"(plan|work)-\d{8}-\d{6}"), r"\1-<newname>"),
)

# Every token a mask can leave behind, and the two shapes of fill that a
# panel puts between its content and its closing border.
MASKED = re.compile(r"<age>|<time>|<stamp>|<newname>|<n>|<unit>|<SB>")
PAD_SPACE = re.compile(r" {2,}(│\s*)$")
PAD_FILL = re.compile(r"─{2,}([╮╯]\s*)$")


def repad(line: str) -> str:
    """Neutralise the padding a mask moved. Idempotent, so it is as true of a
    golden read back off disk as of a capture taken a minute ago."""
    if not MASKED.search(line):
        return line
    line = PAD_SPACE.sub(r" <pad>\1", line)
    return PAD_FILL.sub(r"─<pad>\1", line)


def mask_machine(line: str) -> str:
    """A machine panel's border line: its numbers, and the unit after one."""
    return UNIT.sub(r"\1 <unit>", NUM.sub("<n>", line))


def _title_of(border: str) -> str:
    """The panel name out of a top border line, centred or left-aligned."""
    m = re.search(r"[╭─]─ ?([a-z]+)", border)
    if m:
        return m.group(1)
    m = re.search(r"─ ([a-z]+) ─", border)
    return m.group(1) if m else ""


def normalise(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    skipping = False
    for line in lines:
        if skipping:
            if "╰" in line:
                skipping = False
                out.append(mask_machine(line))
            continue
        if "╭" in line and _title_of(line) in MACHINE_PANELS:
            out.append(mask_machine(line))
            out.append("│ <machine: %s>" % _title_of(line))
            skipping = True
            continue
        out.append(line)

    body = "\n".join(out)
    if SB:
        body = body.replace(SB, "<SB>")
    for pat, rep in SUBS:
        body = pat.sub(rep, body)
    body = "\n".join(repad(l) for l in body.split("\n"))
    # A capture is compared as lines with no trailing blank run: tmux pads the
    # pane to its full height and the height is the route's business, not the
    # frame's.
    return body.rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    for path in argv:
        with open(path) as fh:
            text = fh.read()
        with open(path, "w") as fh:
            fh.write(normalise(text))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
