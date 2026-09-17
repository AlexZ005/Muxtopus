#!/usr/bin/env python3
"""Where did every pre-split definition go, and was it changed on the way?

    python3 tests/sandbox/moved.py            summary
    python3 tests/sandbox/moved.py --diff     and the diff of each changed one

Reads `git show dash-pre-split:deck_status.py` -- the 3768-line file as it
stood before the split -- collects its top-level functions and classes, and
looks for each one by name across the tree the split has produced.

WHAT IT IS FOR. "Move, do not improve" is a claim about a diff nobody can
read: the phases move thousands of lines between files, and `git diff` shows
them all as deleted and added. This says it in one line instead -- MISSING is
always a bug (a definition dropped on the floor), and CHANGED is a bug in the
early phases and expected in the later ones, where a method's `self.` becomes
`app.` or `view.` and its body genuinely differs by those bytes and no
others. The goldens prove the behaviour; this proves the inventory.
"""
import ast
import difflib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
# Deliberate renames, so MISSING keeps meaning "dropped on the floor" rather
# than "called something else now". Each one is in the commit that made it.
RENAMED = {
    "Dashboard.build": "Dashboard.build_main",     # it returns sections now
}
FILES = ["deck_status.py", "dashboard/core.py", "dashboard/data.py",
         "dashboard/schedules.py", "dashboard/menulayout.py", "dashboard/app.py",
         "dashboard/views/main.py", "dashboard/views/schedules.py",
         "dashboard/views/newsession.py", "dashboard/menus/mux.py"]


def defs(src, methods_too=False):
    """name -> source text, for top-level defs and (optionally) methods."""
    out = {}
    lines = src.split("\n")
    def take(name, node):
        out.setdefault(name, "\n".join(lines[node.lineno - 1:node.end_lineno]))
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            take(node.name, node)
            if methods_too and isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        # QUALIFIED: four classes here have an __init__, and
                        # matching on the bare name makes three of them vanish
                        # into the first one and reports a change that is only
                        # a collision.
                        take(node.name + "." + sub.name, sub)
    return out


def main(argv):
    old_src = subprocess.run(
        ["git", "-C", str(ROOT), "show", "dash-pre-split:deck_status.py"],
        capture_output=True, text=True).stdout
    if not old_src:
        print("no dash-pre-split tag in this checkout"); return 2
    old = defs(old_src, methods_too=True)

    new = {}
    for f in FILES:
        p = ROOT / f
        if p.exists():
            for k, v in defs(p.read_text(), methods_too=True).items():
                new.setdefault(k, (v, f))

    def found(name):
        """Where a pre-split definition is now: under its own qualified name,
        under the name it was deliberately renamed to, or -- for a method that
        moved to another class, which is most of what the split does -- under
        the same method name on whatever class now has it."""
        for cand in (name, RENAMED.get(name)):
            if cand and cand in new:
                return new[cand]
        if "." in name:
            bare = name.split(".", 1)[1]
            for k, v in new.items():
                if k.endswith("." + bare):
                    return v
        return None

    missing = sorted(n for n in old if found(n) is None)
    changed = sorted(n for n in old
                     if found(n) is not None and found(n)[0] != old[n])
    same = len(old) - len(missing) - len(changed)
    print("pre-split definitions: %d   identical: %d   changed: %d   MISSING: %d"
          % (len(old), same, len(changed), len(missing)))
    for n in missing:
        print("  MISSING  %s" % n)
    for n in changed:
        print("  changed  %-28s -> %s" % (n, found(n)[1]))
        if "--diff" in argv:
            for line in difflib.unified_diff(
                    old[n].split("\n"), found(n)[0].split("\n"),
                    "pre-split", found(n)[1], lineterm="", n=1):
                print("    " + line)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
