#!/usr/bin/env python3
"""assert_fit.py -- a capture FITS its terminal. The mux-responsive proof.

    assert_fit.py <capture> <rows> <cols> <footer substring> [<must contain>...]

Exit 0 and one line when it holds; exit 1 and the reasons when it does not.

What "fits" means, each one a thing the 80x24 bug broke:

  * no more lines than rows, and no line wider than cols (display width,
    so ▸ and █ count as the one cell they take);
  * THE FOOTER IS THERE: Live crops a frame that is too tall from the
    BOTTOM, so the footer being on screen is what proves the frame was not
    too tall. The footer substring is the one piece of the key line that
    starts it, so it survives the line wrapping on a narrow terminal;
  * every box that opens closes: as many ╭ as ╰, in order, none left open.
    A table cut off by the terminal loses its bottom border, and that is
    visible here even when the footer happens to be drawn inside a menu;
  * whatever else the caller names is on the screen (the tab the route
    thinks it is on, the "N more" marker it expects).
"""
import sys
import unicodedata


def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def main() -> int:
    path, rows, cols, footer, *musts = sys.argv[1:]
    rows, cols = int(rows), int(cols)
    lines = open(path, encoding="utf-8").read().rstrip("\n").split("\n")
    why = []
    if len(lines) > rows:
        why.append("%d lines on a %d-row terminal" % (len(lines), rows))
    for n, line in enumerate(lines, 1):
        if width(line) > cols:
            why.append("line %d is %d wide on %d columns" % (n, width(line), cols))
    # Compared with the whitespace squeezed: the key line WRAPS on a narrow
    # terminal, and "q quit" may break between the key and its word.
    flat = " ".join("\n".join(lines).split())
    if " ".join(footer.split()) not in flat:
        why.append("no footer (%r): the frame was taller than the terminal" % footer)
    depth = 0
    for n, line in enumerate(lines, 1):
        depth += line.count("╭") - line.count("╰")
        if depth < 0:
            why.append("line %d closes a box that never opened" % n)
            depth = 0
    if depth:
        why.append("%d box(es) never closed: cut off at the bottom" % depth)
    for m in musts:
        if " ".join(m.split()) not in flat:
            why.append("missing %r" % m)
    name = path.rsplit("/", 1)[-1]
    if why:
        print("  FAIL %s: %s" % (name, "; ".join(why)))
        return 1
    print("  ok   %s (%d lines, footer, boxes closed)" % (name, len(lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
