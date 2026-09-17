#!/usr/bin/env python3
"""Assert a capture holds a whole, unclipped menu: hint line, closing border
right under it, a cursor row inside, and the capture no taller than the
terminal. Prints one line per capture; exits 1 on the first failure."""
import sys
ok = True
for path in sys.argv[2:]:
    H = int(sys.argv[1])
    lines = open(path).read().split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    hint = [i for i, l in enumerate(lines) if "esc close" in l or "esc back" in l]
    why = ""
    if len(lines) > H:
        why = "taller than the terminal (%d > %d)" % (len(lines), H)
    elif not hint:
        why = "no hint line (menu clipped or absent)"
    else:
        i = hint[-1]
        top = max(j for j, l in enumerate(lines[:i]) if "╭" in l)
        if i + 1 >= len(lines) or "╰" not in lines[i + 1]:
            why = "no closing border under the hint"
        elif not any("▸" in l for l in lines[top:i]):
            why = "no cursor row inside the menu"
    up = any("▲" in l for l in lines); down = any("▼" in l for l in lines)
    print("%-44s %s  markers=%s%s" % (path.rsplit("/", 1)[-1], "FAIL: " + why if why else "ok",
          "▲" if up else "-", "▼" if down else "-"))
    ok = ok and not why
sys.exit(0 if ok else 1)
