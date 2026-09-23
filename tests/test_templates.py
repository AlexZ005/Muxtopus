#!/usr/bin/env python3
"""setup-schedules.py -- the templates it seeds, run for real into a temp HOME.

Run it:  .venv/bin/python tests/test_templates.py     (no pytest, no dependency)

WHY RUN THE SCRIPT rather than import TEMPLATES: the script does its work at
import time, into whatever HOME it finds, and the rules this checks are about
what lands on disk -- that a template the user edited survives a re-run, and
that the text a window is pasted is the text in the folder. A dict compared
with itself proves neither.
"""
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent

ALL = ("blank-plan.md", "hardening-audit.md", "resume-status.md", "roadmap-plan.md",
       "orchestrate.md", "lane.md", "integrate.md", "sweep.md")
ORCH = ("orchestrate.md", "lane.md", "integrate.md", "sweep.md")

# The names sched_subst resolves at paste time. HANDOVERS and STATE come from
# the orch-executor lane, which lands beside these templates: until it does,
# they are the two names below that claude-watchdog.sh's SCHED_PLACEHOLDERS
# does not list yet, and the check at the bottom says so rather than failing.
# Anything ELSE in the four texts would be pasted as literal text -- above all
# {{STATUS_FILE}}, which only the Python writers fill, and {{VALUE}}, which
# only an option line gets.
EXECUTOR = {"SLUG", "WINDOW", "HANDOVER", "QUESTIONS", "SCHEDULES", "CWD",
            "PARENT", "HANDOVERS", "STATE"}
PENDING = {"HANDOVERS", "STATE"}
# The executor's own pattern (sched_placeholders), so a name this misses is
# one the executor would miss too.
PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")

fails = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


def run(home: pathlib.Path) -> str:
    # EVERY MUX*/XDG*/CLAUDE_CONFIG_DIR variable goes: a lane window exports
    # MUXTOPUS_DIR and friends pointing at the real checkout, and a stray
    # MUXTOPUS_HOME would seed the user's real schedules folder.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MUX", "XDG_", "CLAUDE_CONFIG_DIR"))}
    env["HOME"] = str(home)
    p = subprocess.run([sys.executable, str(ROOT / "setup-schedules.py")],
                       env=env, cwd=str(home), capture_output=True, text=True)
    check(p.returncode == 0, "setup-schedules.py exits 0 (%s)" % p.stderr.strip()[-200:])
    return p.stdout


def main() -> int:
    home = pathlib.Path(tempfile.mkdtemp(prefix="muxtpl-"))
    try:
        out = run(home)
        base = home / ".local" / "share" / "muxtopus" / "schedules"
        tpl = base / "templates"
        check(("schedules dir: %s" % base) in out,
              "it seeds the temp HOME, not a real one (%s)" % out.splitlines()[:1])

        # (a) all eight are written.
        for name in ALL:
            check((tpl / name).is_file() and (tpl / name).stat().st_size > 0,
                  "templates/%s is written" % name)
        check(sorted(p.name for p in tpl.glob("*.md")) == sorted(ALL),
              "and nothing else (got %s)" % sorted(p.name for p in tpl.glob("*.md")))

        # (b) a template the user edited survives a re-run -- the one rule
        # that makes this script safe to run twice.
        mine = "my own sweep, edited by hand\n"
        (tpl / "sweep.md").write_text(mine)
        out2 = run(home)
        check((tpl / "sweep.md").read_text() == mine,
              "an existing sweep.md with different text is NOT overwritten")
        check("(nothing - all files already present)" not in out2
              and "created: README.md" in out2,
              "a second run creates only the README (said: %r)" % out2.splitlines()[-1:])
        (tpl / "lane.md").unlink()
        run(home)
        check((tpl / "lane.md").is_file() and (tpl / "sweep.md").read_text() == mine,
              "a deleted template comes back; the edited one still does not move")
        shutil.rmtree(tpl)
        run(home)

        # (c) every placeholder in the four new texts is one the executor
        # resolves.
        for name in ORCH:
            text = (tpl / name).read_text()
            names = set(PLACEHOLDER.findall(text))
            check(names and names <= EXECUTOR,
                  "%-15s uses executor placeholders only (%s)"
                  % (name, " ".join(sorted(names - EXECUTOR)) or "ok"))
            # The withdrawn rule (plan section 10): an orchestrator works on
            # the account it started from. No text may tell it to cross over.
            check(not re.search(r"personal|work account", text, re.I),
                  "%-15s says nothing about another account" % name)
            check(not re.search(r"^(type|at|slug):", text, re.M),
                  "%-15s is a template, not an entry (no header)" % name)

        sweep = (tpl / "sweep.md").read_text()
        check("`reset` when none does" in sweep and "NEVER\n   sooner" in sweep,
              "the sweep's own default cadence is at: reset, never sooner")
        check("sweep-<MMDD>" in sweep and "-b" in sweep,
              "...its next slug is date-stamped, with a same-day suffix")
        check("write NO next entry" in sweep,
              "...and it has a stop condition")
        # Folded to one line: the sentences are wrapped at 78 columns.
        orch = " ".join((tpl / "orchestrate.md").read_text().split())
        check("Read this brief and execute it end to end." in orch
              and "Facts measured by the planner" in orch and "Finish" in orch,
              "orchestrate.md: identity line, measured facts, a Finish line")
        check("NEW WAVE, NOT A RESUME" in orch, "...and round 2 is a new wave")
        check("the brief wins" in (tpl / "lane.md").read_text(),
              "lane.md: no push by default, and the brief can say otherwise")

        readme = (base / "README.md").read_text()
        for name in ALL:
            check(name in readme, "the README lists %s" % name)
        check("THE LAST FOUR ARE `type: work` TEMPLATES" in readme,
              "...and says the four orchestrator ones are type: work")

        # Which of the names above does THIS checkout's executor resolve?
        # Everything but PENDING must already be there; PENDING arrives with
        # the orch-executor lane, after which this set is empty.
        m = re.search(r'^SCHED_PLACEHOLDERS="([^"]*)"',
                      (ROOT / "claude-watchdog.sh").read_text(), re.M)
        have = set(m.group(1).split()) if m else set()
        check(bool(m) and EXECUTOR - have <= PENDING,
              "the executor resolves every name but %s (missing: %s)"
              % ("/".join(sorted(PENDING)), " ".join(sorted(EXECUTOR - have)) or "none"))
    finally:
        shutil.rmtree(home, ignore_errors=True)

    print()
    if fails:
        print("%d FAILED" % len(fails))
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
