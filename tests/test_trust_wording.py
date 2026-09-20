#!/usr/bin/env python3
"""The trust dialog is recognised by two files, and they must agree.

    python3 tests/test_trust_wording.py

WHY THIS TEST EXISTS. Claude Code asks about an untrusted folder before it
will do anything, and two files here have to spot that screen:

    claude-watchdog.sh   PROMPT_QUESTIONS / PROMPT_YES_LABELS -- so a window
                         sitting on it is reported as `waiting` and the phone
                         can answer it
    claude-usage.sh      the probe's `stuck_on trust` dead end -- so a failed
                         reading says "test has not trusted /home/test" rather
                         than something the reader cannot act on

The wording changed. The watchdog's list was updated ("Is this a project you
created or one you trust", "Yes, I trust this folder") and the probe's was
not, so the probe stopped seeing the dialog it was written to see. It then
did the worst available thing: waited out its twenty seconds in front of the
dialog, typed /usage into it, and pressed Enter -- which on that screen is
the highlighted `No, exit`. claude quit, the pane died, the capture came back
EMPTY, and 679 consecutive readings on a real machine failed as "no usage
panel appeared" with nothing in the file the message points at.

So: one file may not know a phrase the other knows. This does not assert any
particular wording -- that is Claude Code's to change -- only that the two
lists stay the same size as each other, which is the thing nobody notices.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = 0


def ok(cond, what):
    global fails
    if cond:
        print("ok   " + what)
    else:
        fails += 1
        print("FAIL " + what)


usage = (ROOT / "claude-usage.sh").read_text()
watchdog = (ROOT / "claude-watchdog.sh").read_text()

# The probe's matcher: the alternation it greps the pane with.
m = re.search(r"grep -qiE '([^']*)'\s*<<<\"\$txt\" && bad=trust", usage)
ok(m is not None, "claude-usage.sh has a trust matcher this test can read")
if m is None:
    sys.exit(1)
probe = [p.strip().lower() for p in m.group(1).split("|") if p.strip()]
ok(len(probe) >= 2, "the probe matches more than one phrasing: %r" % probe)

# What the watchdog knows a trust dialog says. Both lists, because the
# question and the button are separate lines on that screen and either one
# identifies it.
q = re.search(r"^PROMPT_QUESTIONS='([^']*)'", watchdog, re.M)
y = re.search(r"^PROMPT_YES_LABELS='([^']*)'", watchdog, re.M)
ok(q is not None and y is not None, "claude-watchdog.sh has both prompt lists")
if q is None or y is None:
    sys.exit(1)
known = [p.strip() for p in (q.group(1) + "|" + y.group(1)).split("|") if p.strip()]
# Only the ones ABOUT TRUST: the watchdog's list covers every prompt Claude
# Code can show ("Do you want to", "Would you like to proceed"), and the probe
# has no business recognising those -- it never gets far enough to see one.
trust_phrases = [p for p in known if "trust" in p.lower()]
ok(len(trust_phrases) >= 2,
   "the watchdog knows at least two trust phrases: %r" % trust_phrases)

# EVERY trust phrase the watchdog knows must be caught by the probe's matcher.
# Not string equality: the probe matches a SUBSTRING of the line, so the test
# is whether one of its alternatives appears in that phrase.
for phrase in trust_phrases:
    low = phrase.lower()
    hit = [p for p in probe if p in low]
    ok(bool(hit),
       "the probe catches the watchdog's %r (via %s)" % (phrase, hit or "NOTHING"))

# And the phrasing that actually broke it, kept by name so a future rewrite of
# either list cannot quietly drop the case this test was written for.
SEEN_ON_A_REAL_MACHINE = [
    "Quick safety check: Is this a project you created or one you trust?",
    "Yes, I trust this folder",
    "Do you trust the files in this folder?",
]
for line in SEEN_ON_A_REAL_MACHINE:
    low = line.lower()
    ok(any(p in low for p in probe),
       "the probe catches a dialog reading %r" % line[:48])

print("%s" % ("all passed" if not fails else "%d failed" % fails))
sys.exit(1 if fails else 0)
