#!/usr/bin/env python3
"""Every global name the dashboard's code mentions is one it can reach.

Run it:  python3 tests/test_names.py      (no dependency beyond python3)

THE ONE FAILURE A PICTURE CANNOT CATCH. The goldens prove what the dashboard
draws, and they walk a long route -- but a route is what somebody thought to
press. A method that moved into a module whose import list forgot one
constant is a NameError the first time a hand reaches the row that calls it,
and every such row in this dashboard does something: closes a window, writes
a schedule entry, kills a session.

The split found two of them with this check and nothing else:

    views/schedules.py  act_schedule_resume   HANDOVERS_DIR
    views/schedules.py  options_panel         options_paths   (the "no
                        options at all" branch, which no fixture has)

It resolves every loaded Name against the module's own globals, its imports,
its locals and the builtins. Crude, and deliberately so: it has no opinion
about style, it answers one question, and it answers it without importing
anything -- so it also runs where rich is not installed.
"""
import ast
import builtins
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = ["deck_status.py", "muxsettings.py", "muxconfig.py"] + \
    sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py"))
BUILTIN = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__"}


def module_names(tree):
    """What the module binds at its top level, imports included."""
    out = set()
    stack = list(tree.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                for nm in ([t] if isinstance(t, ast.Name) else getattr(t, "elts", [])):
                    if isinstance(nm, ast.Name):
                        out.add(nm.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.Try, ast.If, ast.For, ast.While, ast.With)):
            # A guarded import (dashboard.core's rich) binds at top level too.
            stack += list(getattr(n, "body", [])) + list(getattr(n, "orelse", [])) \
                + list(getattr(n, "finalbody", [])) \
                + [h for x in getattr(n, "handlers", []) for h in x.body]
    return out


def bound_anywhere(tree):
    """Every name bound anywhere in the file: arguments, assignments,
    comprehension targets, with, for, except. This check is about names that
    resolve to NOTHING, not about scope."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = n.args
            for arg in (a.args + a.posonlyargs + a.kwonlyargs
                        + ([a.vararg] if a.vararg else [])
                        + ([a.kwarg] if a.kwarg else [])):
                out.add(arg.arg)
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        if isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        if isinstance(n, ast.alias):
            out.add((n.asname or n.name).split(".")[0])
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
    return out


def main():
    bad = 0
    for rel in FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        known = module_names(tree) | bound_anywhere(tree) | BUILTIN
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) \
                    and n.id not in known:
                print("  FAIL %s:%d  %r is not defined, imported or bound"
                      % (rel, n.lineno, n.id))
                bad += 1
        print("  ok   %s" % rel)
    print()
    print("no unreachable names in %d files" % len(FILES) if not bad
          else "%d unreachable name(s)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
