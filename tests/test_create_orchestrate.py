#!/usr/bin/env python3
"""`c ▸ orchestrate ▸ wave / sweep` in the schedules view.

Run it:  .venv/bin/python tests/test_create_orchestrate.py   (needs rich)

Driven through App.route_key with the keys a hand would press, against a
scratch HOME seeded the way a real account is: setup-schedules.py writes the
templates, seeds/options.md is the options table. What is asserted is the FILE
the form writes, because the file is what the executor reads:

  - `type: work` (the executor knows plan and work only -- no third type),
    an informational `kind: wave|sweep`, the template's text as the body and
    the `## Options` section from the orchestrate kind's options;
  - dashboard/schedules.py validate_schedule accepts it, and
    `claude-watchdog.sh --check <file>` warns about nothing -- `kind:` is inert
    to both;

The picture of the pickers is tests/sandbox/goldens.sh's job; this is what
enter DOES.
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import difflib

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOME = tempfile.mkdtemp(prefix="muxcreateorch-")
ENV = dict(os.environ, HOME=HOME,
           XDG_CONFIG_HOME=HOME + "/.config",
           XDG_STATE_HOME=HOME + "/.local/state",
           XDG_DATA_HOME=HOME + "/.local/share")
# MUXTOPUS_DIR and friends leak in from a lane window (profile.sh exports
# them, pointing at the MAIN checkout), and TMUX would aim anything that
# shells out at the real server.
for _k in list(ENV):
    if _k.startswith(("MUX_", "MUXTOPUS_")) or _k in ("CLAUDE_CONFIG_DIR", "TMUX"):
        del ENV[_k]
os.environ.clear()
os.environ.update(ENV)
sys.path.insert(0, str(ROOT))

SCHEDULES = pathlib.Path(HOME) / ".local/share/muxtopus/schedules"
TEMPLATES = SCHEDULES / "templates"
HANDOVERS = pathlib.Path(HOME) / ".local/share/muxtopus/handovers"

# The account, seeded for real: the same script a user runs, the same file
# install.sh copies.
subprocess.run([sys.executable, str(ROOT / "setup-schedules.py")], env=ENV,
               check=True, stdout=subprocess.DEVNULL)
CFG = pathlib.Path(HOME) / ".config/muxtopus"
CFG.mkdir(parents=True, exist_ok=True)
shutil.copy(ROOT / "seeds" / "options.md", CFG / "options.md")

import deck_status                                      # noqa: E402
from dashboard.app import App                           # noqa: E402
from dashboard.core import ORCH_TEMPLATES               # noqa: E402
from dashboard.schedules import (parse_options_line,    # noqa: E402
                                 read_schedules)

n = 0
fails = 0


def ok(cond, what):
    global n, fails
    n += 1
    if cond:
        print("ok   " + what)
    else:
        fails += 1
        print("FAIL " + what)


# ONE App, as test_newsession.py explains: the key registries are
# module-level and a second load_modules() would re-register them.
APP = App(2.0)
deck_status.load_modules(APP)
ok(not APP.load_errors, "every module loads: %s" % (APP.load_errors or "none"))
APP.say = lambda msg: SAID.append(msg)
SAID: list = []
V = APP.view_of("sched")


def pick(label):
    """Move the open picker onto the option starting `label`, press enter."""
    pk = APP.picker
    assert pk is not None, "no picker open (said: %r)" % SAID[-1:]
    names = [o.split()[0] for o in pk["options"]]
    while names[pk["i"]] != label:
        APP.route_key("DOWN")
    APP.route_key("\r")


def table_keys():
    """The option keys the open table shows, and the group headings."""
    rows = V.option_rows()
    return ([r["opt"]["key"] for r in rows if "opt" in r],
            [r["head"] for r in rows if "head" in r])


def cont():
    """Walk to the `continue` row and press enter: writes the entry."""
    rows = V.option_rows()
    target = next(i for i, r in enumerate(rows) if r.get("act") == "continue")
    while APP.modal["i"] != target:
        APP.route_key("DOWN")
    APP.route_key("\r")


def new_files(before):
    return sorted(set(SCHEDULES.glob("*.md")) - before)


def head_body(f):
    h, _, b = f.read_text().partition("\n---\n")
    fields = {}
    for l in h.split("\n"):
        k, sep, v = l.partition(":")
        if sep:
            fields[k.strip()] = v.strip()
    return fields, b


def check_cmd(f):
    """claude-watchdog.sh --check on the file: its exit code and output."""
    p = subprocess.run(["bash", str(ROOT / "claude-watchdog.sh"), "--check", str(f)],
                       env=ENV, capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout + p.stderr


# The ONE warning an orchestrator's body may raise here: {{HANDOVERS}} and
# {{STATE}} are the executor's words from the orch-executor lane, and on a
# base without that lane --check reports them unresolved (exit 2). Nothing
# else is tolerated; with that lane merged the list is empty and --check
# exits 0.
def unexpected_warnings(out):
    return [l for l in out.splitlines() if "WARN" in l.upper()
            and not ("{{HANDOVERS}}" in l or "{{STATE}}" in l)]


def kind_is_inert(f):
    """--check on the entry, then on the SAME file with its kind: line taken
    out, say the same thing byte for byte. That is "ignored by the executor"
    as a measurement rather than a reading of the code. The same file, not a
    copy: a copy's name would change the derived slug and every path built
    from it."""
    text = f.read_text()
    a = check_cmd(f)
    try:
        f.write_text("\n".join(l for l in text.split("\n")
                                if not l.startswith("kind:")))
        b = check_cmd(f)
    finally:
        f.write_text(text)
    if a != b and "-v" in sys.argv:
        print("\n".join(difflib.unified_diff(a[1].splitlines(), b[1].splitlines(),
                                             lineterm="")))
    return a == b, a, b


# ------------------------------------------------------------------ the pick
print("== c: the first picker")
V.start_create()
ok(APP.picker["options"] == ["plan", "work", "orchestrate"],
   "c offers plan / work / orchestrate (got %r)" % APP.picker["options"])
pick("plan")
ok(APP.picker and APP.picker["title"] == "from which template?",
   "plan still opens the template picker")
listed = set(APP.picker["options"])
seeded = {t.stem for t in TEMPLATES.glob("*.md")}
ok(set(ORCH_TEMPLATES) <= seeded,
   "setup-schedules.py seeds every orchestrator template ORCH_TEMPLATES names "
   "(missing: %s)" % (sorted(set(ORCH_TEMPLATES) - seeded) or "none"))
ok(not listed & set(ORCH_TEMPLATES),
   "the plan picker lists none of the four orchestrator templates (got %s)"
   % sorted(listed & set(ORCH_TEMPLATES)))
ok(listed == seeded - set(ORCH_TEMPLATES),
   "…and every other template it seeds (%s)" % sorted(listed))
APP.route_key("\x1b")

V.start_create()
pick("orchestrate")
ok(APP.picker and APP.picker["title"] == "orchestrate what?"
   and APP.picker["options"] == ["wave", "sweep"],
   "orchestrate opens wave / sweep (got %r)" % (APP.picker and APP.picker["options"]))

# ------------------------------------------------------------------ a sweep
print("== orchestrate ▸ sweep")
before = set(SCHEDULES.glob("*.md"))
pick("sweep")
st = APP.modal
ok(st is not None and st["typ"] == "orchestrate",
   "the options table opens with the orchestrate kind (got %r)" % (st and st["typ"]))
keys, heads = table_keys()
ok("ORCHESTRATE" in heads and {"automate", "cadence", "credits"} <= set(keys),
   "…and shows the orchestrate group (%s)" % heads)
ok({"phases", "nopush"} <= set(keys) and "tp-base" in keys,
   "…and the work blocks too (phases, nopush, tp-base)")
on = set(st["on"])
ok({"questions", "phases", "lowpri", "verify", "automate"} <= on,
   "a sweep keeps questions, phases, lowpri, verify and automate ticked (%s)" % sorted(on))
ok(not on & {"nopush", "subwindows", "preview-gate", "rules-file", "orchestrate"},
   "a sweep has nopush, subwindows, preview-gate, rules-file, orchestrate off (%s)"
   % sorted(on & {"nopush", "subwindows", "preview-gate", "rules-file", "orchestrate"}))
day = time.strftime("%m%d")
ok(st["title"] == "sweep-" + day, "the table names the entry sweep-<MMDD> (%s)" % st["title"])
cont()
made = new_files(before)
ok(len(made) == 1 and made[0].name == "sweep-%s.md" % day,
   "one file written, sweep-<MMDD>.md (%s)" % [f.name for f in made])
sweep = made[0]
h, body = head_body(sweep)
ok(h.get("type") == "work", "type: work, not a third type (%r)" % h.get("type"))
ok(h.get("kind") == "sweep", "kind: sweep (%r)" % h.get("kind"))
ok(h.get("slug") == "sweep-" + day, "slug: pinned to the file's name (%r)" % h.get("slug"))
tpl = (TEMPLATES / "sweep.md").read_text()
ok(body.startswith(tpl.rstrip()), "the body IS templates/sweep.md, copied")
sec = body[len(tpl.rstrip()):]
ok("## Options" in sec and "Full automation, end to end" in sec,
   "…followed by the ## Options section with the orchestrate lines")
ok("Do not push" not in sec and "Before anything irreversible" not in sec,
   "…and without the nopush or preview-gate sentence")
on_line = parse_options_line(h.get("options", ""))
ok("automate" in on_line and "nopush" not in on_line,
   "options: records what was ticked (%s)" % h.get("options"))
ok(SAID and "sweep" in SAID[-1] and "sweep.md" in SAID[-1],
   "the notice names the shape and the template (%r)" % SAID[-1:])

row = next(r for r in read_schedules() if r["file"] == sweep)
ok(row["bad"] == "", "validate_schedule accepts it (bad=%r)" % row["bad"])
ok(row["warn"] == "", "…with no slug warning (%r)" % row["warn"])
rc, out = check_cmd(sweep)
ok(rc in (0, 2) and not unexpected_warnings(out),
   "claude-watchdog.sh --check <file>: no warning but the known placeholder one "
   "(rc=%d, %s)" % (rc, unexpected_warnings(out)))
ok("kind" not in out.lower(), "--check never mentions kind:")
ok(re.search(r"type\s+work", out) is not None, "--check reads it as a work entry")
same, a, b = kind_is_inert(sweep)
ok(same, "--check says exactly the same with the kind: line removed")

# A second sweep the same day is -b: the first one's slug is taken.
V.start_create()
pick("orchestrate")
pick("sweep")
ok(APP.modal["title"] == "sweep-%s-b" % day,
   "a second sweep the same day is sweep-<MMDD>-b (%s)" % APP.modal["title"])
APP.route_key("\x1b")
ok(new_files(before) == [sweep], "esc on the table writes nothing")

# ------------------------------------------------------------------ a wave
print("== orchestrate ▸ wave")
before = set(SCHEDULES.glob("*.md"))
V.start_create()
pick("orchestrate")
pick("wave")
on = set(APP.modal["on"])
ok({"orchestrate", "automate", "preview-gate", "rules-file", "subwindows"} <= on,
   "a wave has orchestrate, automate, preview-gate, rules-file, subwindows on (%s)"
   % sorted(on))
ok("nopush" not in on, "…and nopush off: automate pushes, so both would contradict")
cont()
made = new_files(before)
ok(len(made) == 1 and made[0].name.startswith("wave-"),
   "one file written, wave-<stamp>.md (%s)" % [f.name for f in made])
wave = made[0]
h, body = head_body(wave)
ok(h.get("type") == "work" and h.get("kind") == "wave",
   "type: work, kind: wave (%r, %r)" % (h.get("type"), h.get("kind")))
ok("slug" not in h, "a wave pins no slug: its title names it")
ok(body.startswith((TEMPLATES / "orchestrate.md").read_text().rstrip()),
   "the body IS templates/orchestrate.md, copied")
ok("You are the orchestrator" in body and "Before anything irreversible" in body,
   "…with the orchestrate and preview-gate sentences")
row = next(r for r in read_schedules() if r["file"] == wave)
ok(row["bad"] == "", "validate_schedule accepts it (bad=%r)" % row["bad"])
rc, out = check_cmd(wave)
ok(rc in (0, 2) and not unexpected_warnings(out) and "kind" not in out.lower(),
   "--check: no warning but the known one, nothing about kind: (rc=%d)" % rc)
ok(kind_is_inert(wave)[0], "--check says exactly the same with the kind: line removed")

# ------------------------------------------------------------------ plain work
print("== work, as before")
before = set(SCHEDULES.glob("*.md"))
V.start_create()
pick("work")
keys, heads = table_keys()
ok(APP.modal["typ"] == "work" and "ORCHESTRATE" not in heads
   and not {"automate", "cadence"} & set(keys),
   "a plain work entry is offered no orchestrate row (%s)" % heads)
ok("nopush" in APP.modal["on"], "…and nopush stays ticked for it")
cont()
work = new_files(before)[0]
h, _ = head_body(work)
ok(h.get("type") == "work" and "kind" not in h, "a plain work entry has no kind: line")

# ------------------------------------------------------------------ missing
print("== a template setup-schedules.py never wrote")
(TEMPLATES / "sweep.md").rename(TEMPLATES / "sweep.md.away")
before = set(SCHEDULES.glob("*.md"))
V.start_create()
pick("orchestrate")
lbl = [o for o in APP.picker["options"] if o.startswith("sweep")][0]
ok("missing" in lbl and "setup-schedules.py" in lbl,
   "the picker says so on the sweep row (%r)" % lbl)
ok(APP.picker["options"][0] == "wave", "…and the wave row is untouched")
SAID.clear()
pick("sweep")
ok(APP.modal is None, "choosing it opens no table")
ok(SAID and "nothing written" in SAID[-1] and "setup-schedules.py" in SAID[-1],
   "…and says what to run (%r)" % SAID[-1:])
ok(new_files(before) == [], "…and writes no empty orchestrator")
(TEMPLATES / "sweep.md.away").rename(TEMPLATES / "sweep.md")

shutil.rmtree(HOME, ignore_errors=True)
print()
print("%d checks, %d failed" % (n, fails))
if fails:
    print("%d FAILED" % fails)
    sys.exit(1)
print("all passed")
