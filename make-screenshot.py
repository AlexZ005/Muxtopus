#!/usr/bin/env python3
"""Render the live dashboard to an SVG for the README.

Captures a REAL pane, so the layout, colours and column widths are the ones
the tool actually produces -- a hand-drawn mock drifts from the code the first
time a column moves -- then substitutes window names, repo names and paths for
neutral ones, because a screenshot in a public README should not be a tour of
whatever the author happened to be working on that afternoon.

EVERY SUBSTITUTION IS WIDTH-PRESERVING. The dashboard is drawn with box
characters and space-padded columns, so a replacement one character shorter
than the original drags that row's right-hand border in by one and the panel
visibly frays. Replacements are padded (or truncated) to the exact width of
what they replace, and the script then ASSERTS that every line is the width it
started as -- a check that costs nothing and is the only thing standing between
"looks fine to me" and a crooked screenshot at the top of the README.

    make-screenshot.py [target] [out.svg]
    make-screenshot.py '=claude:0' docs/dashboard.svg
"""
import re
import subprocess
import sys
import pathlib

TARGET = sys.argv[1] if len(sys.argv) > 1 else "=claude:0"
OUT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "docs/dashboard.svg")

ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Longest first: a short key that is a prefix of a longer one would otherwise
# corrupt the longer one half way through. Every replacement is chosen to be
# no LONGER than what it replaces, so padding can do the rest.
SUBS = [
    ("theprototype-app/theprototype-lane-towers", "acme/checkout-service-lane-search"),
    ("theprototype-app/core-lane-review", "acme/checkout-service-lane-review"),
    ("theprototype-app/core-lane-bin", "acme/checkout-service-lane-bin"),
    ("theprototype-app/core-lane-a2", "acme/checkout-svc-lane-auth"),
    ("theprototype-app/core", "acme/checkout-service"),
    ("plan1-fixes", "api-cleanup"),
    ("plan2-stars", "cache-layer"),
    ("plan3-community", "flaky-test-hunt"),
    ("Plan4", "Login"),
    ("~/.code/scripts", "~/src/muxtopus"),
]


def fit(new: str, old: str) -> str:
    """Same display width as what it replaces -- see the module docstring."""
    return new[:len(old)].ljust(len(old))


def main() -> int:
    try:
        from rich.console import Console
        from rich.text import Text
    except ImportError:
        print("needs rich: run this with the dashboard venv's python", file=sys.stderr)
        return 1

    cap = subprocess.run(["tmux", "capture-pane", "-e", "-p", "-t", TARGET],
                         capture_output=True, text=True)
    if cap.returncode != 0:
        print("capture-pane failed: %s" % cap.stderr.strip(), file=sys.stderr)
        return 1

    lines = cap.stdout.rstrip("\n").split("\n")
    while lines and not ANSI.sub("", lines[-1]).strip():
        lines.pop()
    if not lines:
        print("nothing captured from %s" % TARGET, file=sys.stderr)
        return 1

    widths = [len(ANSI.sub("", ln)) for ln in lines]

    out = []
    for ln in lines:
        for old, new in SUBS:
            ln = ln.replace(old, fit(new, old))
        # Any home path left is somebody's actual machine.
        ln = re.sub(r"/home/[a-z0-9_-]+", lambda m: fit("~", m.group(0)), ln)
        out.append(ln)

    bad = [(i + 1, w, len(ANSI.sub("", ln)))
           for i, (w, ln) in enumerate(zip(widths, out))
           if w != len(ANSI.sub("", ln))]
    if bad:
        for i, was, now in bad[:10]:
            print("line %d changed width %d -> %d" % (i, was, now), file=sys.stderr)
        print("refusing to write a frayed screenshot", file=sys.stderr)
        return 1

    body = "\n".join(out)
    width = max(widths)

    console = Console(record=True, width=width, force_terminal=True,
                      color_system="truecolor", legacy_windows=False)
    console.print(Text.from_ansi(body), overflow="ignore", crop=False, no_wrap=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(OUT), title="muxtopus · ctrl-b 0")
    print("wrote %s  (%d cols x %d rows, all widths preserved)"
          % (OUT, width, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
