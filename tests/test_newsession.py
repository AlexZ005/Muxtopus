#!/usr/bin/env python3
"""`c` is a form, and the form writes the entry the launcher expects.

    python3 tests/test_newsession.py

WHAT IS UNDER TEST, and why each part is worth a test rather than a read:

  c enter enter    the whole reason it stopped being seven pickers. `c` asks
                   for the name with an offer in the brackets; enter takes
                   the offer and enter again writes a complete, launchable
                   entry from the defaults. The offer must be free, because
                   the second c of the day must work as well as the first.
  the brackets     enter on an empty line takes the placeholder, and typing
                   replaces it -- on `c` and on the Name row alike.
  the sub-windows  the two rows under Create: the ➥➥ child they write, and
                   the handover row being refused, with the reason, until
                   the parent lane has written one.
  a row edits      each row opens a picker or a prompt, and the value comes
                   back into the form rather than into the next screen.
  esc on a row     leaves the row alone and the FORM OPEN. This is the whole
                   point of App's `on_cancel`, and it is the thing that used
                   to be impossible: every submode's esc threw the flow away.
  the entry        the headers the executor reads, and the one that must be
                   ABSENT when the mode is the account's own default -- an
                   empty `permission-mode:` would be passed to the CLI as a
                   flag with no value.

A TEMPORARY HOME, so it writes into a scratch schedules folder and reads a
scratch config: no dashboard, no tmux, no watchdog.
"""
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOME = tempfile.mkdtemp(prefix="muxnewsession-")
os.environ.update(HOME=HOME,
                  XDG_CONFIG_HOME=HOME + "/.config",
                  XDG_STATE_HOME=HOME + "/.local/state",
                  XDG_DATA_HOME=HOME + "/.local/share")
for _k in ("MUXTOPUS_CONFIG", "MUXTOPUS_HOME", "MUXTOPUS_DIR",
           "CLAUDE_CONFIG_DIR", "TMUX"):
    os.environ.pop(_k, None)
sys.path.insert(0, str(ROOT))

import deck_status                                          # noqa: E402
from dashboard import naming                                # noqa: E402
from dashboard.app import App                               # noqa: E402

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


SCHEDULES = pathlib.Path(HOME) / ".local/share/muxtopus/schedules"


# ONE App FOR THE WHOLE FILE. The registries muxsettings and App keep are
# module-level -- a second load_modules() re-registers every key and raises --
# and a dashboard only ever builds one, so this models the real thing rather
# than working around it. `fresh` reopens the FORM, which is what `c` does.
APP = App(2.0)
deck_status.load_modules(APP)
ok(not APP.load_errors, "every module loads: %s" % (APP.load_errors or "none"))


def fresh(name=""):
    """The form as `c` leaves it, the NAME PROMPT ANSWERED: type `name`, or
    nothing to take what is in the brackets. That prompt is what `c` opens
    now, and answering it is what opens the form."""
    APP.newsession.start_new_session()
    assert APP.prompt is not None, "c should open the name prompt"
    for ch in name:
        APP.prompt_key(ch)
    APP.prompt_key("\r")
    assert APP.menu is not None, "an answered name should open the form"
    return APP


def row(app, prefix):
    for i, r in enumerate(app.menu_entries()):
        if r.get("label", "").startswith(prefix):
            return i
    raise AssertionError("no row starting %r" % prefix)


def label(app, prefix):
    return app.menu_entries()[row(app, prefix)]["label"]


def press(app, prefix):
    app.menu["i"] = row(app, prefix)
    app.menu_activate()


def entries():
    return set(SCHEDULES.glob("*.md"))


def written(before):
    """The entry that appeared since `before`. Not sorted()[-1]: these are
    named after their slug, so alphabetical order is not the order they were
    written in and the newest is whichever one is new."""
    new = entries() - before
    assert len(new) == 1, "expected one new entry, got %r" % sorted(new)
    return new.pop()


def fields(path):
    head = path.read_text().split("\n---\n", 1)[0]
    out = {}
    for line in head.splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def body(path):
    parts = path.read_text().split("\n---\n", 1)
    return parts[1] if len(parts) > 1 else ""


# ---- 0. c asks for the name, with the offer in the brackets ---------------
APP.newsession.start_new_session()
ok(APP.prompt is not None and APP.menu is None,
   "c opens the name prompt, not the form")
offer = APP.prompt.get("placeholder", "")
ok(APP.prompt["buf"] == "",
   "the line starts EMPTY, so typing a name is not backspacing one first")
ok("-" in offer and offer.split("-")[-1] in naming.NOUNS,
   "and the offer is the folder and one word: %r" % offer)
ok(offer not in APP.newsession._taken_slugs(), "the offer is a free name")
APP.prompt_key("\r")
ok(APP.ns["slug"] == offer, "enter on the empty line takes what is in brackets")
ok(APP.menu is not None and APP.menu["kind"] == "newsession",
   "and the form opens on it")

APP.newsession.start_new_session()
for ch in "typed one":
    APP.prompt_key(ch)
APP.prompt_key("\r")
ok(APP.ns["slug"] == "typed-one",
   "a typed name wins over the offer, sanitised: %r" % APP.ns["slug"])
press(APP, "Create")           # so the name is now really taken

# A NAME THAT IS TAKEN is refused and asked again, with the offer unchanged.
APP.newsession.start_new_session()
was_offer = APP.prompt["placeholder"]
for ch in "typed one":
    APP.prompt_key(ch)
APP.prompt_key("\r")
ok(APP.prompt is not None and APP.menu is None,
   "a name a pending entry already has is refused")
ok("taken" in APP.prompt["title"], "and the prompt says why: %r" % APP.prompt["title"])
ok(APP.prompt["placeholder"] == was_offer,
   "with the same offer still in the brackets")
APP.prompt_key("\x1b")
ok(APP.ns is None, "esc at the first prompt abandons the whole thing")

# ---- 1. the form itself ---------------------------------------------------
app = fresh()
items = app.menu_entries()
ok(items[0]["label"].startswith("Create "), "Create is the first row: %r"
   % items[0]["label"][:40])
ok(app.menu["i"] == 0, "and the cursor opens on it, so c enter creates")
ok(not items[0].get("stay"), "Create closes the form")
for want in ("Name:", "Folder:", "Model:", "Effort:", "Permission mode:",
             "Where:", "First prompt:"):
    ok(any(r.get("label", "").startswith(want) for r in items),
       "the form has a %s row" % want.rstrip(":"))
ok(all(app.menu_entries()[row(app, w)].get("stay")
       for w in ("Name:", "Folder:", "Model:", "Effort:")),
   "a parameter row keeps the form open")

# ---- 2. c, enter, enter ---------------------------------------------------
before = entries()
press(app, "Create")
ok(len(entries()) == len(before) + 1, "c enter enter writes exactly one entry")
ok(app.menu is None, "and closes the form")
first = written(before)
f = fields(first)
ok(f.get("status") == "pending", "the entry is pending")
ok(f.get("type") == "plan", "no first prompt makes it a plan entry")
ok(bool(f.get("slug")), "it has a slug: %r" % f.get("slug"))
ok(bool(f.get("cwd")) and os.path.isdir(f["cwd"]), "and a cwd that exists")
ok(f.get("at", "") <= time.strftime("%Y-%m-%d %H:%M"),
   "at: is already past, so the next pass launches it")
# THE ONE THAT MUST BE ABSENT: an empty permission-mode would reach the CLI
# as `--permission-mode ''` and the window would die on it.
ok("permission-mode" not in f,
   "an account-default mode writes no permission-mode: header")
ok(app.newsession.follow and app.newsession.follow["slug"] == f["slug"],
   "and the form is now following that slug to its window")

# ---- 3. the second c of the day -------------------------------------------
app2 = fresh()
ok(label(app2, "Name:").split()[1] != f["slug"],
   "the next form offers a name that is not the one just taken: %r"
   % label(app2, "Name:").split()[1])
prev2 = entries()
press(app2, "Create")
ok(len(entries()) == len(prev2) + 1, "so c enter enter works a second time")
ok(fields(written(prev2))["slug"] != f["slug"], "with a different slug")

# THE NAME ROW holds the current name in its brackets, so enter keeps it.
app2b = fresh("kept name")
press(app2b, "Name:")
ok(app2b.prompt["placeholder"] == "kept-name" and app2b.prompt["buf"] == "",
   "the Name row offers the name it has: %r" % app2b.prompt.get("placeholder"))
app2b.prompt_key("\r")
ok(app2b.ns["slug"] == "kept-name", "and enter on the empty line keeps it")
app2b.menu_esc()

# ---- 4. a row edits, and the form stays -----------------------------------
app3 = fresh()
press(app3, "Effort:")
ok(app3.picker is not None, "the effort row opens a picker")
ok(app3.menu is not None, "and the form is still open behind it")
app3.picker_key("DOWN")
app3.picker_key("\r")
ok(app3.picker is None, "enter closes the picker")
ok("Effort: (account default)" not in label(app3, "Effort:"),
   "and the row shows what was chosen: %r" % label(app3, "Effort:"))

press(app3, "Name:")
ok(app3.prompt is not None, "the name row opens a prompt")
for _ in range(40):
    app3.prompt_key("\x7f")
for ch in "a lane":
    app3.prompt_key(ch)
app3.prompt_key("\r")
ok(app3.menu is not None, "a prompt answered from the form keeps the form")
ok("a-lane" in label(app3, "Name:"), "the typed name is sanitised into the slug")

press(app3, "First prompt:")
for ch in "go":
    app3.prompt_key(ch)
app3.prompt_key("\r")
ok('"go"' in label(app3, "First prompt:"), "the first prompt is shown on its row")

# ---- 5. esc on a row leaves the row, not the form -------------------------
was = label(app3, "Model:")
press(app3, "Model:")
app3.picker_key("\x1b")
ok(app3.ns is not None, "esc in a row's picker does NOT abandon the form")
ok(app3.menu is not None, "and the form is still on screen")
ok(label(app3, "Model:") == was, "and the row is unchanged")

press(app3, "Name:")
app3.prompt_key("\x1b")
ok(app3.ns is not None, "esc in a row's prompt does not abandon it either")
ok("a-lane" in label(app3, "Name:"), "and the name it had is still there")

before3 = entries()
press(app3, "Create")
e = written(before3)
ok(fields(e)["type"] == "work", "a first prompt makes it a work entry")
ok(body(e).strip() == "go", "and the prompt is the body")
ok(fields(e)["slug"] == "a-lane", "the entry carries the typed slug")
ok(fields(e)["effort"] in ("low", "medium", "high", "xhigh", "max"),
   "and the effort chosen on the form")

# ---- 5b. esc on the FORM abandons it, and says so -------------------------
app3b = fresh()
app3b.menu_esc()
ok(app3b.menu is None, "esc on the form closes it")
ok(app3b.ns is None, "and drops the answers -- a half-filled form is not state")

# ---- 6. Cancel ------------------------------------------------------------
app4 = fresh()
had = entries()
press(app4, "Cancel")
ok(app4.ns is None, "Cancel drops the form's answers")
ok(app4.menu is None, "and closes it")
ok(entries() == had, "and writes nothing")

# ---- 6b. the two sub-window rows ------------------------------------------
# A QUICK SUB-WINDOW IS A FORK OF THE LANE THE CURSOR IS ON, so the rows are
# there only when the cursor is on one. The main view's accessors are what
# they read, and this drives those directly: a tmux server is not needed to
# answer "which window is the cursor on".
SUB = "Sub-window"
app6 = fresh()
ok(not any(r.get("label", "").startswith(SUB) for r in app6.menu_entries()),
   "no cursor session, no sub-window rows")
app6.menu_esc()

main = APP.view_of("main")
main.cursor = "sid-parent"
main.windows = {"sid-parent": "➥parent"}
main.panes = {"sid-parent": "%1"}
main.cwds = {"sid-parent": str(ROOT)}
main.sids = ["sid-parent"]

app7 = fresh("fork one")
rows7 = [r for r in app7.menu_entries() if r.get("label", "").startswith(SUB)]
ok(len(rows7) == 2, "a cursor session puts both sub-window rows on the form")
ok(all("➥➥fork-one under ➥parent" in r["label"] for r in rows7),
   "and they name the child and its parent: %r" % rows7[0]["label"][:52])
ok("has not written STATUS-parent.md" in (rows7[1].get("disabled") or ""),
   "the handover row is refused with its reason while there is no handover")

before7 = entries()
press(app7, SUB)                      # the empty one: the first of the two
sub = written(before7)
fs = fields(sub)
ok(fs.get("window") == "➥parent" and fs.get("parent") == "parent",
   "the empty sub-window goes under that window: %r" % fs.get("window"))
ok(fs.get("type") == "plan" and not body(sub).strip(),
   "and carries no prompt at all")
ok(app7.menu is None, "and the form closes on it, like Create")

# WITH A HANDOVER the second row is live, and what it pastes is the resume
# brief pointed at that lane's STATUS file.
HANDOVERS = pathlib.Path(HOME) / ".local/share/muxtopus/handovers"
HANDOVERS.mkdir(parents=True, exist_ok=True)
(HANDOVERS / "STATUS-parent.md").write_text("# parent\n\n## How to resume\n- go\n")
app8 = fresh("fork two")
rows8 = [r for r in app8.menu_entries() if r.get("label", "").startswith(SUB)]
ok(not rows8[1].get("disabled"), "a written handover makes the second row live")
before8 = entries()
app8.menu["i"] = row(app8, SUB) + 1   # the handover one
app8.menu_activate()
sub2 = written(before8)
ok(fields(sub2).get("parent") == "parent", "it is a child of that lane too")
ok(fields(sub2).get("type") == "work", "with a prompt, so a work entry")
ok("STATUS-parent.md" in body(sub2),
   "and the brief names the parent's handover: %r" % body(sub2).strip()[:60])

main.cursor = ""                      # back to a cursor on nothing
main.windows, main.panes, main.cwds, main.sids = {}, {}, {}, []

# ---- 7. the follow gives up rather than waiting for ever ------------------
app5 = fresh()
app5.newsession.follow = {"slug": "nope", "until": time.time() + 60}
ok(str(app5.newsession.follow_hint(app5)).strip() == "· opening ➥nope",
   "while it waits, the key line says which window")
app5.newsession.follow = {"slug": "nope", "until": time.time() - 1}
ok(app5.newsession.follow_hint(app5) is None
   and app5.newsession.follow is None, "past its deadline it stops looking")
ok(app5.newsession.follow_hint(app5) is None, "and costs nothing when idle")

print()
print("%d assertions, %s (%s)" % (n, "all passed" if not fails else "%d FAILED" % fails, HOME))
sys.exit(1 if fails else 0)
