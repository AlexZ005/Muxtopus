#!/usr/bin/env python3
"""The dashboard's half of "one state, any number of tags".

    .venv/bin/python tests/test_window_tags_view.py

The watchdog decides (tests/test_window_states.sh fires that against real
processes); this holds what the dashboard and the phone make of the row:

  * the TAGS column is read from status.tsv's 21st field, `-` and an older
    watchdog's 20-field row both meaning none;
  * every new state has a label and a colour, and `limited` reads "limit hit"
    while its NAME stays limited (everything that acts keys on the name);
  * the tags cell: the two that mean "do something" are loud, the rest dim;
  * the phone's /windows words, and the states a "questions answered" line
    may be typed into -- a handed-off lane is exactly the one that asked.
"""
import atexit
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOME = tempfile.mkdtemp(prefix="mux-tags-view-")
atexit.register(shutil.rmtree, HOME, ignore_errors=True)
os.environ.update(HOME=HOME, XDG_CONFIG_HOME=HOME + "/.config",
                  XDG_STATE_HOME=HOME + "/.local/state", XDG_DATA_HOME=HOME + "/.local/share")
for _k in ("MUXTOPUS_CONFIG", "MUXTOPUS_HOME", "MUXTOPUS_DIR", "CLAUDE_CONFIG_DIR", "TMUX"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(ROOT))

from dashboard.core import STATES, WATCHDOG_DIR, YELLOW, DIM  # noqa: E402
from dashboard.data import claude_sessions  # noqa: E402
from dashboard.views.main import tags_text, TAG_LOUD  # noqa: E402
import muxtelegram  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails += 1


WATCHDOG_DIR.mkdir(parents=True, exist_ok=True)


def row(sid, name, state, said="-", tags=None):
    f = [sid, name, "%1", "1", "1000", state, "-", "", "0", "0", "0", "0", "opus",
         "60", "", "/w", "0", "0", "123", said]
    if tags is not None:
        f.append(tags)
    return "\t".join(f) + "\n"


print("== status.tsv's TAGS column")
(WATCHDOG_DIR / "status.tsv").write_text(
    row("a", "lane-a", "background", tags="e2e,serve:5380")
    + row("b", "lane-b", "handed-off", tags="-")
    + row("c", "lane-c", "idle"))                 # an older watchdog: no 21st field
got = {s.sid: s for s in claude_sessions()[0]}
ok(got["a"].tags == ("e2e", "serve:5380"), "two tags, in order: %r" % (got["a"].tags,))
ok(got["b"].tags == (), "`-` is no tags")
ok(got["c"].tags == (), "a twenty-field row (an older watchdog) has no tags")
ok(got["a"].said == "-", "SAID is still read where it was")

print("== the states")
for st in ("queued", "paused", "error", "background", "orchestrating", "handed-off", "done"):
    ok(st in STATES, "%s has a label and a colour" % st)
ok(STATES["limited"][0] == "limit hit", "limited reads 'limit hit'")
ok(STATES["limited"][2] is True, "..and still carries its reset time")
ok(STATES["handed-off"][0] == "handed off", "handed-off reads 'handed off'")

print("== the tags cell")
t = tags_text(("e2e-wait", "serve:5380", "asking"))
ok(t.plain == "e2e-wait,serve:5380,asking", "comma separated: %r" % t.plain)
loud = {t.plain[s.start:s.end] for s in t.spans if s.style == YELLOW}
ok(loud == {"e2e-wait", "asking"}, "e2e-wait and asking are loud, nothing else: %r" % loud)
ok(set(TAG_LOUD) == {"e2e-wait", "asking"}, "TAG_LOUD is those two")
ok(tags_text(()).plain == "—", "no tags: a dash, like every unknown cell")

print("== the phone")
words = dict(muxtelegram.STATE_WORDS)
ok(words["limited"] == "limit hit" and words["handed-off"] == "handed off", "/windows says the new words")
ok(all(st in words for st in ("paused", "queued", "error", "background", "orchestrating", "done")),
   "/windows knows every new state")
ok(set(muxtelegram.AT_PROMPT) == {"idle", "handed-off", "orchestrating", "done"},
   "a 'questions answered' line may go to a window at its prompt -- never a background one")
ok("tags" in muxtelegram.STATUS_COLS and muxtelegram.STATUS_COLS.index("tags") == 20,
   "the phone reads TAGS at index 20")

print()
print("%d FAILED" % fails if fails else "all passed")
sys.exit(1 if fails else 0)
