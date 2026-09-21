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
  the sub-windows  the two rows under Create: the child they write, and
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
    """The form as `c` leaves it. `name` is typed INTO the Create row, which
    is where the name lives now; nothing takes the offer already there."""
    APP.newsession.start_new_session()
    assert APP.menu is not None, "c should open the form"
    assert APP.prompt is None, "c should not open a prompt over it"
    for ch in name:
        APP.route_key(ch)
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


# ---- 0. c opens the FORM, with the name already in the Create row --------
# No modal any more. The name is a field ON the Create row, so `c enter` is
# the whole gesture and nothing is drawn over the form while it is answered.
APP.newsession.start_new_session()
ok(APP.prompt is None and APP.menu is not None and APP.menu["kind"] == "newsession",
   "c opens the form directly -- no name prompt over the top of it")
offer = APP.ns["slug"]
ok("-" in offer and offer.split("-")[-1] in naming.NOUNS,
   "the Create row already holds the folder and one word: %r" % offer)
ok(offer not in APP.newsession._taken_slugs(), "the offer is a free name")
ok(APP.menu["i"] == 0, "the cursor is on Create, so c enter creates")

create = APP.menu_entries()[0]
ok("edit" in create, "the Create row is a FIELD as well as an action")
ok("[%s]" % offer.ljust(naming.MAX_SLUG) in create["label"],
   "the name is drawn in the brackets, padded to MAX_SLUG: %r"
   % create["label"])

# FIXED WIDTH: the row must be the same length at every keystroke, or the
# whole form twitches sideways while a name is typed.
width_before = len(APP.menu_entries()[0]["label"])
APP.route_key("x")
ok(APP.ns["slug"] == "x",
   "the first character typed REPLACES the offer, not appends to it")
APP.route_key("y")
ok(APP.ns["slug"] == "xy", "and the next one appends: %r" % APP.ns["slug"])
ok(len(APP.menu_entries()[0]["label"]) == width_before,
   "the Create row is exactly as wide with a short name as with a long one")
APP.route_key("\x7f")
ok(APP.ns["slug"] == "x", "backspace deletes one character")

# q AND SPACE ARE CHARACTERS while a name is being typed, not "close the menu".
APP.route_key("q")
ok(APP.menu is not None and APP.ns["slug"] == "xq",
   "q is typed into the name rather than closing the form")
ok(len(APP.ns["slug"]) <= naming.MAX_SLUG, "the field is bounded by MAX_SLUG")
for _ in range(40):
    APP.route_key("z")
ok(len(APP.ns["slug"]) == naming.MAX_SLUG,
   "...and typing past it stops rather than growing the row: %d"
   % len(APP.ns["slug"]))

# The arrows still belong to the MENU, so a field never becomes a mode.
APP.route_key("DOWN")
ok(APP.menu["i"] != 0, "DOWN still moves the cursor off the field")
APP.route_key("\x1b")
ok(APP.ns is None, "esc on the form abandons the whole thing")

# A TYPED NAME IS SANITISED ONCE, ON CREATE -- never per keystroke.
APP.newsession.start_new_session()
for ch in "typed one":
    APP.route_key(ch)
ok(APP.ns["slug"] == "typed-one",
   "a typed space becomes the hyphen a slug would have had: %r" % APP.ns["slug"])
ok(APP.menu is not None,
   "...and it does NOT fall through to the menu, where space closes the form")
press(APP, "Create")
ok(any(fields(p).get("slug") == "typed-one" for p in entries()),
   "and Create writes it")

# A NAME THAT IS TAKEN is refused BY CREATE, and the form stays open.
APP.newsession.start_new_session()
for ch in "typed one":
    APP.route_key(ch)
msg = APP.menu_entries()[0]["act"]()
ok("taken" in msg, "a name a pending entry already has is refused: %r" % msg)
ok(APP.ns is not None and APP.menu is not None,
   "and the form is still open, with the name still in the row")
ok(APP.ns["slug"] == "typed-one", "nothing was cleared")

# AN EMPTY NAME is refused the same way.
for _ in range(30):
    APP.route_key("\x7f")
msg = APP.menu_entries()[0]["act"]()
ok("empty" in msg, "an empty name is refused: %r" % msg)
APP.route_key("\x1b")

# ---- 0b. asking again offers a DIFFERENT name ----------------------------
# `c`, read it, `c` again used to suggest the same word: the offer advanced
# only when a name was TAKEN, and a name you just declined is not taken.
seen = []
for _ in range(4):
    APP.newsession.start_new_session()
    seen.append(APP.ns["slug"])
    APP.route_key("\x1b")
ok(len(set(seen)) == len(seen),
   "four presses of c offer four different names: %r" % seen)
ok(all(n not in APP.newsession._taken_slugs() for n in seen),
   "and every one of them is free")

# ---- 1. the form itself ---------------------------------------------------
app = fresh()
items = app.menu_entries()
ok(items[0]["label"].startswith("Create "), "Create is the first row: %r"
   % items[0]["label"][:40])
ok(app.menu["i"] == 0, "and the cursor opens on it, so c enter creates")
ok(not items[0].get("stay"), "Create closes the form")
for want in ("Folder:", "Model:", "Effort:", "Permission mode:",
             "Where:", "First prompt:"):
    ok(any(r.get("label", "").startswith(want) for r in items),
       "the form has a %s row" % want.rstrip(":"))
ok(all(app.menu_entries()[row(app, w)].get("stay")
       for w in ("Folder:", "Model:", "Effort:")),
   "a parameter row keeps the form open")

# ---- 2. c, enter, enter ---------------------------------------------------
before = entries()
press(app, "Create")
ok(len(entries()) == len(before) + 1, "c enter writes exactly one entry")
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
ok(app2.ns["slug"] != f["slug"],
   "the next form offers a name that is not the one just taken: %r"
   % app2.ns["slug"])
prev2 = entries()
press(app2, "Create")
ok(len(entries()) == len(prev2) + 1, "so c enter works a second time")
ok(fields(written(prev2))["slug"] != f["slug"], "with a different slug")

# A NAME TYPED INTO THE ROW is what gets written, sanitised once at the end.
app2b = fresh("kept name")
ok(app2b.ns["slug"] == "kept-name",
   "the Create row holds what was typed: %r" % app2b.ns["slug"])
prev2b = entries()
press(app2b, "Create")
ok(fields(written(prev2b))["slug"] == "kept-name",
   "and that is the slug in the entry")

# ---- 4. a row edits, and the form stays -----------------------------------
app3 = fresh()
press(app3, "Effort:")
ok(app3.picker is not None, "the effort row opens a picker")
ok(app3.menu is not None, "and the form is still open behind it")
app3.picker_key("DOWN")
app3.picker_key("\r")
ok(app3.picker is None, "enter closes the picker")
ok("(account default)" not in label(app3, "Effort:"),
   "and the row shows what was chosen: %r" % label(app3, "Effort:"))

# THE NAME IS EDITED IN PLACE, on the Create row, with the form never leaving
# the screen -- there is no Name row and no prompt to answer any more.
app3.menu["i"] = row(app3, "Create")
for _ in range(40):
    app3.route_key("\x7f")
for ch in "a lane":
    app3.route_key(ch)
ok(app3.menu is not None and app3.prompt is None,
   "typing a name never leaves the form")
ok("a-lane" in label(app3, "Create"),
   "and the Create row shows it: %r" % label(app3, "Create"))

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

press(app3, "First prompt:")
app3.prompt_key("\x1b")
ok(app3.ns is not None, "esc in a row's prompt does not abandon it either")
ok("a-lane" in label(app3, "Create"), "and the name it had is still there")

before3 = entries()
press(app3, "Create")
e = written(before3)
ok(fields(e)["type"] == "work", "a first prompt makes it a work entry")
ok(body(e).strip() == "go", "and the prompt is the body")
ok(fields(e)["slug"] == "a-lane", "the entry carries the typed slug")
ok(fields(e)["effort"] in ("low", "medium", "high", "xhigh", "max"),
   "and the effort chosen on the form")

# ---- 5a. a default row says WHAT YOU GET, not "(account default)" ---------
# The row used to name the mechanism -- no flag is passed -- and never the
# outcome, which is the only part worth reading before pressing Create.
import json as _json
app4 = fresh()
cwd4 = app4.ns["cwd"]
for what in ("Model:", "Effort:", "Permission mode:"):
    ok("(account default)" not in label(app4, what),
       "%s no longer says (account default): %r" % (what, label(app4, what)))
ok("unset" in label(app4, "Model:"),
   "with nothing set anywhere it says unset, not a guess: %r"
   % label(app4, "Model:"))

proj = pathlib.Path(cwd4) / ".claude"
proj.mkdir(parents=True, exist_ok=True)
(proj / "settings.json").write_text(_json.dumps(
    {"model": "fable", "effortLevel": "high",
     "permissions": {"defaultMode": "acceptEdits"}}))
app4b = fresh()
ok("fable" in label(app4b, "Model:"),
   "a model in settings.json is named: %r" % label(app4b, "Model:"))
ok("high" in label(app4b, "Effort:"),
   "effortLevel too: %r" % label(app4b, "Effort:"))
ok("acceptEdits" in label(app4b, "Permission mode:"),
   "and permissions.defaultMode: %r" % label(app4b, "Permission mode:"))
ok("settings.json" in label(app4b, "Model:"),
   "the row says which file it read")
# settings.local.json wins, as it does for Claude Code itself.
(proj / "settings.local.json").write_text(_json.dumps({"model": "haiku"}))
app4c = fresh()
ok("haiku" in label(app4c, "Model:"),
   "settings.local.json wins over settings.json: %r" % label(app4c, "Model:"))
(proj / "settings.local.json").unlink()
(proj / "settings.json").unlink()
app4c.menu_esc()

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
# DELIBERATELY AN OLD-STYLE NAME. Lanes are named for their slug alone now,
# but a window an older release opened is still on screen with its markers,
# and every path built from it has to keep coming out the same. So the parent
# here keeps its ➥ and the assertions below check both halves: the label
# shows the window as tmux reports it, and `parent:` is the bare slug.
main.windows = {"sid-parent": "➥parent"}
main.panes = {"sid-parent": "%1"}
main.cwds = {"sid-parent": str(ROOT)}
main.sids = ["sid-parent"]

app7 = fresh("fork one")
rows7 = [r for r in app7.menu_entries() if r.get("label", "").startswith(SUB)]
ok(len(rows7) == 2, "a cursor session puts both sub-window rows on the form")
ok(all("fork-one under ➥parent" in r["label"] for r in rows7),
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
ok(str(app5.newsession.follow_hint(app5)).strip() == "· opening nope",
   "while it waits, the key line says which window")
app5.newsession.follow = {"slug": "nope", "until": time.time() - 1}
ok(app5.newsession.follow_hint(app5) is None
   and app5.newsession.follow is None, "past its deadline it stops looking")
ok(app5.newsession.follow_hint(app5) is None, "and costs nothing when idle")

print()
print("%d assertions, %s (%s)" % (n, "all passed" if not fails else "%d FAILED" % fails, HOME))
sys.exit(1 if fails else 0)
