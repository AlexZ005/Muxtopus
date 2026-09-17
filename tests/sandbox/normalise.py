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
     `8 hidden`, `1.1 GB`) -- the titles themselves are not.
  3. Everywhere else, only genuinely moving things:
       the watchdog scan age       scan 3s ago   -> scan <age> ago
       the usage read clock        read 08:40    -> read <time>
       a "N minutes ago" age       (12m ago)     -> (<age> ago)
       a written timestamp         2026-09-17 23:41 -> <stamp>
       the sandbox root            /tmp/muxsplit-sandbox -> <SB>
     An IDLE column age is NOT masked: it comes from the fixture's own
     integer, so it is fixed, and masking it would hide a real change.

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
                out.append(NUM.sub("<n>", line))
            continue
        if "╭" in line and _title_of(line) in MACHINE_PANELS:
            out.append(NUM.sub("<n>", line))
            out.append("│ <machine: %s>" % _title_of(line))
            skipping = True
            continue
        out.append(line)

    body = "\n".join(out)
    if SB:
        body = body.replace(SB, "<SB>")
    for pat, rep in SUBS:
        body = pat.sub(rep, body)
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
