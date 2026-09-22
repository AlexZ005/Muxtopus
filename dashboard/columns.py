"""dashboard.columns -- which columns and which panels the main view draws.

Three settings keys, their parsing, and the cached readers the view and the
menu both call. A PURE MODULE at package level, like dashboard.tabstrip: the
VIEW must never import a menu (a menu imports its view, and a cycle is how
one broken menu takes the main screen down with it), so the shared answer
lives here and both sides ask it.

  DASHBOARD_COLUMNS_HIDDEN   "<table>:<COLUMN>", comma-separated
  DASHBOARD_COLUMNS_PINNED   the same shape; UNSET means DEFAULT_PINNED
  DASHBOARD_PANELS_HIDDEN    of deck,lanes,uncommitted,system

BY NAME, WITH THE TABLE IN FRONT, never by index. Three separate reasons,
and any one of them is enough: STATE and DIRTY are columns of BOTH tables,
so a bare name is ambiguous; ACCOUNT is in the lanes table only while `f`
shows every account, so the list a number indexes changes under the user's
hand; and the claude table's CONTEXT is a different width above and below
100 columns. An index would name a different column on the next frame.

A COLUMN NAME FOR A COLUMN THAT IS NOT THERE RIGHT NOW IS KEPT, not refused
-- that is ACCOUNT, which is legitimately absent nine frames in ten, and a
validator that dropped it would silently unhide it the next time the user
touched any other row. Only the SHAPE is checked: a table name that is not
one of ours, or an item with no colon in it, is a typo in a hand-edited
file and is refused with its own text so the user can see which one.

HIDDEN WINS OVER PINNED, the same rule Settings ▸ Tabs has for hidden over
locked, and for the same reason: a column that is pinned and invisible is a
heading with no cell under it. menulayout.column_window enforces it too --
this module just never writes a config that needs the rescue.

UNSET IS NOT EMPTY for the pinned key. Unset is a user who has never opened
the menu, and they get DEFAULT_PINNED: the column that NAMES each row in
each table. A table scrolled sideways with its name column gone is a grid
of numbers about nothing -- which is exactly what the first wiring of this
did at 80 columns, and it is also what make_table's marker column needs (it
draws "▼ N more" in a wide column that is always present). An EXPLICIT
empty value is the user saying they want nothing pinned, and it is kept.
"""
from __future__ import annotations

import re
import time

import muxsettings
from dashboard.core import knob

HIDDEN_KEY = "DASHBOARD_COLUMNS_HIDDEN"
PINNED_KEY = "DASHBOARD_COLUMNS_PINNED"
PANELS_KEY = "DASHBOARD_PANELS_HIDDEN"

# The two tables of the main view that scroll sideways. The schedules table
# keeps fit_columns and its ranks, so it is not here.
TABLES = ("lanes", "claude")

# The panels fit_height's `assemble` names, less `claude`: the sessions
# table IS the main view, and a screen that can hide its own subject is a
# blank frame with a footer. The parser refuses it by name so a hand-edited
# config says so rather than quietly doing nothing.
PANELS = ("deck", "lanes", "uncommitted", "system")

# Unset pinned means these: the flexible, row-naming column of each table.
DEFAULT_PINNED = "lanes:LANE,claude:WINDOW"

# A column header as this dashboard writes them -- upper-case words, and
# CONTEXT/RESUMED/ACCOUNT are the longest. Permissive on purpose: a column
# this release does not have is KEPT (see the module docstring), so this
# only has to reject the things that cannot be a header at all.
NAME_OK = re.compile(r"^[A-Za-z0-9 _/-]+$")

_cache: dict[str, tuple[float, object]] = {}


def parse(value: str) -> dict[str, set[str]]:
    """"lanes:RAM,claude:RESUMED" -> {"lanes": {"RAM"}, "claude": {"RESUMED"}}.

    Every table in TABLES gets a set, empty or not, so a caller never has
    to guard the lookup. An item this parser cannot read is DROPPED rather
    than raised on: this runs inside a frame, and a hand-edited config with
    one bad line must not take the dashboard down -- validate_columns is
    what tells the user, at the moment they write it.
    """
    out: dict[str, set[str]] = {t: set() for t in TABLES}
    for item in value.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        table, _, name = item.partition(":")
        table, name = table.strip(), name.strip()
        if table in out and name:
            out[table].add(name)
    return out


def unparse(sets: dict[str, set[str]]) -> str:
    """The inverse, sorted so the file is stable: rewriting dashboard.conf
    after a toggle must not reorder the line and read as a change."""
    return ",".join("%s:%s" % (t, n)
                    for t in TABLES for n in sorted(sets.get(t, ())))


def validate_columns(value: str) -> str:
    """Why this value cannot be written, or "". The `check` of both column
    specs; the complaint carries THE ITEM'S OWN TEXT, because "not a
    column" about a list of nine tells the user nothing they can act on."""
    bad = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            bad.append("%s (needs <table>:<COLUMN>)" % item)
            continue
        table, _, name = item.partition(":")
        table, name = table.strip(), name.strip()
        if table not in TABLES:
            bad.append("%s (no table %r -- %s)" % (item, table, " or ".join(TABLES)))
        elif not name or not NAME_OK.match(name):
            bad.append("%s (not a column name)" % item)
    return "not a column: %s" % ", ".join(bad) if bad else ""


def validate_panels(value: str) -> str:
    """Same, for the panel list. `claude` gets its own sentence: it is the
    one name a reader would expect to work, so the refusal says why."""
    bad = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if item == "claude":
            return "the claude table is the main view and cannot be hidden"
        if item not in PANELS:
            bad.append(item)
    return "not a panel: %s (of %s)" % (", ".join(bad), ",".join(PANELS)) \
        if bad else ""


def _cached(key: str, fn, profile: str):
    """The 1-second read cache App.hidden_tabs uses, one slot per key.

    A frame asks for these several times -- once per table, once per panel
    the degrade rule considers, once more if a menu is open over it -- and
    the answer lives in a file three layers deep. One read a second is
    what the tab strip settled on and nothing here is different.
    """
    now = time.time()
    got = _cache.get(key)
    if got is None or now - got[0] > 1.0:
        _cache[key] = (now, fn(knob(key, profile) or ""))
    return _cache[key][1]


def hidden_columns(profile: str = "") -> dict[str, set[str]]:
    return _cached(HIDDEN_KEY, parse, profile)


def pinned_columns(profile: str = "") -> dict[str, set[str]]:
    """UNSET means DEFAULT_PINNED; an explicit "" means nothing pinned.

    knob returns "" for both, so the raw layers are asked directly: the
    key being ABSENT from every file is the untouched case, and the menu
    writes an empty value when the user unpins the last column."""
    def read(_raw: str) -> dict[str, set[str]]:
        have = muxsettings.settings(profile)
        raw = have.get(PINNED_KEY)
        if raw is None:
            raw = DEFAULT_PINNED
        return parse(raw)
    return _cached(PINNED_KEY, read, profile)


def hidden_panels(profile: str = "") -> set[str]:
    def read(raw: str) -> set[str]:
        return {x.strip() for x in raw.split(",")
                if x.strip() and x.strip() in PANELS}
    return _cached(PANELS_KEY, read, profile)


def forget() -> None:
    """Drop the cache. The menu calls this after a put, so the next frame
    shows what was just written instead of the second the cache has left."""
    _cache.clear()


def for_table(table: str, profile: str = "") -> tuple[set[str], set[str]]:
    """(pinned, hidden) for one table, as column_window wants them: bare
    header names, the `<table>:` prefix already stripped, and HIDDEN TAKEN
    OUT OF PINNED here rather than left for the window to resolve."""
    hidden = hidden_columns(profile).get(table, set())
    pinned = pinned_columns(profile).get(table, set()) - hidden
    return pinned, hidden


def register_keys() -> None:
    """Declare the three keys, once per process.

    Guarded by spec_of the way tabs.py's is: the settings store is
    module-level and the tests build several Apps in one process, so a
    second register must not raise over a key the first one declared.
    """
    if muxsettings.spec_of(HIDDEN_KEY) is not None:
        return
    muxsettings.register({
        HIDDEN_KEY: {
            "label": "Hidden columns", "kind": "text",
            "check": validate_columns,
            "hint": "<table>:<COLUMN>, comma-separated (Settings ▸ Columns)"},
        PINNED_KEY: {
            "label": "Pinned columns", "kind": "text",
            "check": validate_columns,
            "hint": "never scrolled off; unset means " + DEFAULT_PINNED},
        PANELS_KEY: {
            "label": "Hidden panels", "kind": "text",
            "check": validate_panels,
            "hint": "of %s (Settings ▸ Panels)" % ",".join(PANELS)},
    }, menu="columns")
