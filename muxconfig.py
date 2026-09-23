"""muxconfig -- the python half of profile.sh.

Reads the SAME files the shell reads, so the two halves can never disagree
about where an account's data lives or what a knob is set to. The format is
plain shell (KEY="value") and this is a READER, not an interpreter: only the
keys in KEYS are honoured, and anything cleverer in a file is ignored rather
than half-executed.

Four layers, all optional -- two hand-written, two the dashboard writes
(muxsettings.py; the DASHBOARD_* keys):

    ~/.config/muxtopus/config                           every account
    ~/.config/muxtopus/dashboard.conf                   every account, dashboard-written
    ~/.config/muxtopus/profiles/<name>.conf             one named account's overrides
    ~/.config/muxtopus/profiles/<name>.dashboard.conf   one account, dashboard-written

Precedence, lowest first: built-in default, environment, config,
dashboard.conf, profile file, profile dashboard file -- the same order
profile.sh applies. The dashboard-written file sits above the hand-written
one at the same scope, so a value set in the menu reads back as set; the
account's own files still beat the shared ones.

    from muxconfig import settings, knob, mux_home, mux_dir, profile_of
    settings("work")               -> dict            everything, effective
    knob("WATCHDOG_SOFT_PCT", "work")  -> "65"
    mux_home("work")               -> Path            that account's home
    mux_dir("schedules", "work")   -> Path            one account's folder
    profile_of()                   -> "" | "work"     (from CLAUDE_CONFIG_DIR)

It also reads the one file that is NOT shell -- options.md, the checkbox table
the dashboard offers when a schedule entry is created. Same two layers, same
precedence, a different syntax (see "schedule options" below):

    options("work")                -> list[dict]      every checkbox, in order
    python3 muxconfig.py --options [profile]          the same, as a table
"""
import os
import pathlib

HOME = pathlib.Path.home()

# EVERY KEY A CONFIG FILE MAY SET, with its built-in default. ONE LIST,
# mirrored in profile.sh (MUX_CONFIG_KEYS); keep the two identical. None means
# the reader computes it.
KEYS = {
    "MUXTOPUS_HOME": None,
    "MUXTOPUS_DIR": None,
    "MUXTOPUS_PYTHON": None,
    "MUXTOPUS_SESSION_PREFIX": "claude",
    "MUXTOPUS_QUESTIONS_DIR": None,
    "WATCHDOG_INTERVAL": "30",
    "WATCHDOG_SOFT_PCT": "65",
    "WATCHDOG_HARD_PCT": "85",
    "WATCHDOG_FRESH_CTX": "150000",
    "WATCHDOG_LOWPRI_WEEK": "40",
    "WATCHDOG_USAGE_EVERY": "60",
    "WATCHDOG_USAGE_STALE": "180",
    "WATCHDOG_HEARTBEAT_LOG": "60",
    "WATCHDOG_STRANDED": "120",
    "WATCHDOG_WOUND_RESUME": "on",
    "CLAUDE_USAGE_MAX_AGE": "20",
    "CLAUDE_USAGE_MODEL": None,
    "CLAUDE_CONTEXT_WINDOW": "1000000",
    # THE DASHBOARD'S OWN, written by its Settings menu into dashboard.conf
    # (muxsettings.py has the labels, choices and the writer). None here is
    # "unset": no flag, no header field, the account default.
    "DASHBOARD_MENU_LAYOUT": "modal",
    "DASHBOARD_NEW_PERMISSION_MODE": "ask",
    "DASHBOARD_PERMANENT_MODE_SCOPE": "project",
    "DASHBOARD_NEW_WATCHDOG": "on",
    "DASHBOARD_NEW_MONITOR": "on",
    "DASHBOARD_NEW_MODEL": None,
    "DASHBOARD_NEW_EFFORT": None,
    "DASHBOARD_NEW_CWD": None,
    # WHAT REACHES THE PHONE (claude-notify.sh; docs/notifications.md
    # §1): the four events, how long a block is ordinary, whether the buttons
    # may answer, and whether pane text may leave the machine.
    "MUXTOPUS_NOTIFY_WAITING": "on",
    "MUXTOPUS_NOTIFY_QUESTIONS": "on",
    "MUXTOPUS_NOTIFY_TROUBLE": "on",
    "MUXTOPUS_NOTIFY_BLOCKED_AFTER": "120",
    "MUXTOPUS_NOTIFY_DONE": "on",
    "MUXTOPUS_NOTIFY_INBOUND": "on",
    "MUXTOPUS_NOTIFY_PANE_TEXT": "on",
    # THE HANDOVERS TAB'S TWO FILTERS (dashboard/views/handovers.py;
    # docs/handovers.md). They persist because R re-execs
    # the dashboard and is pressed a lot, and a done list that came back on
    # every R would be switched off for good.
    "DASHBOARD_HANDOVERS_DONE": "off",
    "DASHBOARD_HANDOVERS_QUESTIONS": "on",
    # THE ALERTS (docs/notifications.md): a session that stopped,
    # an account that logged out, a budget at its limit (or, chattier, past a
    # band), and the scheduler's stalled / stranded verdicts -- each on its own
    # switch, each told once and "cleared" once.
    "MUXTOPUS_NOTIFY_SESSION": "on",
    "MUXTOPUS_NOTIFY_AUTH": "on",
    "MUXTOPUS_NOTIFY_LIMIT": "on",
    "MUXTOPUS_NOTIFY_LIMIT_BANDS": "off",
    "MUXTOPUS_NOTIFY_STALLED": "on",
    "MUXTOPUS_NOTIFY_STRANDED": "on",
    # `rc:` for an entry that does not say: send /rc to every new window.
    "DASHBOARD_NEW_RC": "off",
    # WHICH TABS THE STRIP SHOWS (dashboard/menus/tabs.py): view names,
    # comma-separated, hidden from the strip and from ←→. Unset: all shown.
    "DASHBOARD_TABS_HIDDEN": None,
    # WHICH COLUMNS THE MAIN VIEW'S TWO TABLES SHOW (dashboard/columns.py):
    # items are "<table>:<COLUMN>", comma-separated, tables `lanes` and
    # `claude`. BY NAME WITH THE TABLE IN FRONT, never by index: STATE and
    # DIRTY exist in both tables, ACCOUNT exists only while f shows every
    # account, and the lists change shape with the terminal's width, so an
    # index means a different column tomorrow. Unset: nothing hidden.
    "DASHBOARD_COLUMNS_HIDDEN": None,
    # The columns that are never scrolled off and never squeezed, same
    # shape. UNSET IS NOT EMPTY here: unset means the default below -- the
    # column that names each row -- because a table scrolled sideways with
    # its name column gone is a grid of numbers about nothing. An explicit
    # empty value is the user saying they want nothing pinned, and is kept.
    "DASHBOARD_COLUMNS_PINNED": None,
    # The columns that are HIDDEN UNTIL ASKED FOR (SAID, the last thing each
    # session said) and that the user has asked for, same shape. A key of
    # its own rather than a default for the hidden key, because every config
    # that already names a hidden column would otherwise show SAID the day
    # it appeared. Unset: none of them shown.
    "DASHBOARD_COLUMNS_SHOWN": None,
    # Whole sections of the main view the user does not want drawn, of
    # deck,lanes,uncommitted,system. `claude` is deliberately absent: it is
    # the screen. Unset: all shown. The degrade rule (a short terminal) is
    # separate and its note never names one of these.
    "DASHBOARD_PANELS_HIDDEN": None,
    "WATCHDOG_RESTORE": "ask",
    "WATCHDOG_RESTORE_MAX_AGE": "24",
    "MUXTOPUS_TMUX_SOCKET": "default",
    # NEW RELEASES (mux-update.sh, docs/updates.md). These govern ONE tree of
    # code that every account runs, so the Settings menu writes them to the
    # SHARED dashboard.conf whichever account is on screen -- see
    # muxsettings.scope_of. A profile file may still narrow them by hand, the
    # way it may narrow any key.
    "MUXTOPUS_UPDATE_MODE": "notify",
    "MUXTOPUS_UPDATE_EVERY": "24",
    "MUXTOPUS_UPDATE_CHANNEL": "stable",
    "MUXTOPUS_NOTIFY_UPDATE": "off",
    # WHAT THE DASHBOARD EXPLAINS ON SCREEN (Settings ▸ Hints, and
    # dashboard/menus/hints.py). All four default ON: the dashboard a
    # user already has is the one that keeps drawing until they ask
    # otherwise. "HINTS_" is the group; the older `hint` names in the
    # code mean narrower things, which that module's docstring lists.
    "DASHBOARD_HINTS_ROW_DESC": "on",
    "DASHBOARD_HINTS_MENU_LINE": "on",
    "DASHBOARD_HINTS_FOOTER_KEYS": "on",
    "DASHBOARD_HINTS_TABLE_NOTES": "on",
}
KINDS = ("schedules", "backups", "handovers")


def update_dir() -> pathlib.Path:
    """Where mux-update.sh keeps what it last learned from GitHub.

    NO ACCOUNT SUFFIX, and that is the point: there is one installed tree, so
    the newest release is a fact about the machine. profile.sh computes the
    same path as MUX_UPDATE_DIR; this is the Python half, so a reader that
    was not started by the shell (a test, `muxstats`) finds the same file.
    """
    env = os.environ.get("MUX_UPDATE_DIR")
    if env:
        return pathlib.Path(env)
    state = os.environ.get("XDG_STATE_HOME") or str(HOME / ".local" / "state")
    return pathlib.Path(state) / "muxtopus-update"


def config_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get(
        "MUXTOPUS_CONFIG",
        os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config")) + "/muxtopus/config"))


def profile_conf_path(profile: str) -> pathlib.Path:
    d = os.environ.get("MUXTOPUS_PROFILES_DIR") or str(config_path().parent / "profiles")
    return pathlib.Path(d) / (profile + ".conf")


def dashboard_conf_path(profile: str = "") -> pathlib.Path:
    """The file the dashboard writes: beside config for the default account,
    beside the profile file for a named one -- the shape options.md uses."""
    if not profile:
        return config_path().parent / "dashboard.conf"
    return profile_conf_path(profile).with_name(profile + ".dashboard.conf")


def _read(f: pathlib.Path) -> dict:
    out = {}
    try:
        for line in f.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k not in KEYS:
                continue
            v = v.split("#", 1)[0].strip() if not v.strip().startswith(("'", '"')) else v.strip()
            v = v.strip().strip('"').strip("'")
            v = v.replace("${HOME}", str(HOME)).replace("$HOME", str(HOME))
            out[k] = os.path.expanduser(v)
    except OSError:
        pass
    return out


def read_config() -> dict:
    """The shared file alone, keys whitelisted. Kept for callers that only
    want to know what is written down there."""
    return _read(config_path())


def settings(profile: str = "") -> dict:
    """The effective configuration of one account: defaults, then the
    environment, then the shared file, then the account's own file."""
    out = {k: d for k, d in KEYS.items() if d is not None}
    for k in KEYS:
        if k in os.environ:
            out[k] = os.environ[k]
    out.update(read_config())
    out.update(_read(dashboard_conf_path("")))
    if profile:
        out.update(_read(profile_conf_path(profile)))
        out.update(_read(dashboard_conf_path(profile)))
    return out


def knob(key: str, profile: str = "", default: str | None = None) -> str | None:
    assert key in KEYS, key
    return settings(profile).get(key, default)


def _xdg_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("XDG_DATA_HOME",
                                       str(HOME / ".local" / "share"))) / "muxtopus"


def shared_home() -> pathlib.Path:
    """Where the default account's folders live, and the -suffixed folders of
    any named account that has no home of its own."""
    return pathlib.Path(settings("").get("MUXTOPUS_HOME") or _xdg_home())


def mux_home(profile: str = "") -> pathlib.Path:
    """One account's home: MUXTOPUS_HOME from its profile file if that sets
    one, else the shared home."""
    return pathlib.Path(settings(profile).get("MUXTOPUS_HOME") or _xdg_home())


def mux_dir(kind: str, profile: str = "") -> pathlib.Path:
    """One account's schedules/, backups/ or handovers/ folder.

    Inside a home that belongs to one account the folder is UNSUFFIXED: the
    suffix only ever existed to keep two accounts' siblings apart in a shared
    home. This is the same rule profile.sh applies, and must stay so.
    """
    assert kind in KINDS, kind
    home = mux_home(profile)
    if profile and home != shared_home():
        return home / kind
    return home / (kind + suffix_of(profile))


def profile_of(config_dir: str | None = None) -> str:
    """The account name: ~/.claude -> "", ~/.claude-work -> "work"."""
    d = config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or str(HOME / ".claude")
    name = pathlib.Path(d).name
    if name.startswith(".claude"):
        name = name[len(".claude"):]
    return name.lstrip("-_")


def suffix_of(profile: str) -> str:
    """The path suffix. The default account takes NONE, which is the whole
    reason a single-account machine sees no change at all."""
    return ("-" + profile) if profile else ""


# ------------------------------------------------------- schedule options
# The checkbox table the dashboard shows between picking a template and
# opening the editor. One block per option in
#
#     ~/.config/muxtopus/options.md                  every account
#     ~/.config/muxtopus/profiles/<name>.options.md  one account's overrides
#
# blank-line separated, `key: value` lines, `#` comments anywhere (including
# INSIDE a block -- the `model` option carries a measurement in three comment
# lines and must still parse). The same syntax a schedule file's header uses,
# for the same reason: it is read and written by hand, beside the schedules it
# configures, and its sentences are prose full of colons.
#
# THE SECOND FILE MERGES FIELD BY FIELD, it does not replace the block: the
# common override is one line ("default: off for me"), and re-declaring a
# whole block to change one field is how a `line:` sentence silently gets
# forgotten. Adding a key not in the base file adds an option.
#
# A BROKEN BLOCK IS RETURNED WITH `bad`, NEVER DROPPED. That is the schedule
# view's own rule for a corrupted entry, and for the same reason: an option
# that quietly disappears is indistinguishable from one nobody ever wrote,
# and the table shows it greyed with the reason instead.
OPTION_FIELDS = ("key", "group", "label", "hint", "default",
                 "line", "set", "choices", "ask", "types")
OPTION_KEY_OK = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
OPTION_TYPES = ("plan", "work", "both")
OPTION_ASKS = ("number", "text")
OPTIONS_FILE = "options.md"


def options_paths(profile: str = "") -> list[pathlib.Path]:
    """The files read, in the order they are read. The shared one sits beside
    the config file, so a sandbox with its own MUXTOPUS_CONFIG gets its own
    options.md without any further variable."""
    base = config_path().parent / OPTIONS_FILE
    if not profile:
        return [base]
    d = os.environ.get("MUXTOPUS_PROFILES_DIR") or str(config_path().parent / "profiles")
    return [base, pathlib.Path(d) / (profile + "." + OPTIONS_FILE)]


def _option_blocks(text: str, src: pathlib.Path) -> list[tuple]:
    """(fields, complaints, src) per blank-line separated block.

    Nothing is validated here; a line this cannot make sense of becomes a
    complaint carried on the block rather than a parse error, because the file
    is hand-edited and the useful answer is always "this block, this line"."""
    out: list[tuple] = []
    fields: dict[str, str] = {}
    junk: list[str] = []

    def flush() -> None:
        if fields or junk:
            out.append((dict(fields), list(junk), src))
        fields.clear()
        del junk[:]

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            continue
        k, sep, v = line.partition(":")
        k = k.strip()
        if not sep or k not in OPTION_FIELDS:
            junk.append("not a field: %r" % (line[:40] + ("…" if len(line) > 40 else "")))
        elif k in fields:
            junk.append("%s: given twice" % k)
        else:
            fields[k] = v.strip()
    flush()
    return out


def _option_bad(o: dict, junk: list[str]) -> str:
    """Why this block will not be offered. The §3 rules, in the order a reader
    would check them: the identity first, then the shape, then the details."""
    if junk:
        return junk[0]
    if not o["key"]:
        return "no key:"
    if not set(o["key"]) <= OPTION_KEY_OK:
        return "key %r is not [a-z0-9-]+" % o["key"]
    if bool(o["line"]) == bool(o["set"]):
        return "needs exactly one of line: or set:"
    if o["set"] and not o["choices"]:
        return "set: %s needs choices:" % o["set"]
    if o["ask"] and o["ask"] not in OPTION_ASKS:
        return "ask: must be %s (got %r)" % (" or ".join(OPTION_ASKS), o["ask"])
    if o["ask"] and "{{VALUE}}" not in o["line"]:
        return "ask: but the line has no {{VALUE}}"
    if o["raw_default"] not in ("on", "off"):
        return "default: must be on or off (got %r)" % o["raw_default"]
    if o["types"] not in OPTION_TYPES:
        return "types: must be %s (got %r)" % ("/".join(OPTION_TYPES), o["types"])
    return ""


def _make_option(fields: dict, junk: list[str], src: pathlib.Path) -> dict:
    key = fields.get("key", "")
    o = {
        "key": key,
        "group": fields.get("group", "") or "other",
        # The key is a usable label and a missing one is nearly always a typo
        # in the field name -- which `junk` has already reported. A blank row
        # would hide both.
        "label": fields.get("label", "") or key or "(no key)",
        "hint": fields.get("hint", ""),
        "raw_default": fields.get("default", "off"),
        "default": fields.get("default", "off") == "on",
        "line": fields.get("line", ""),
        "set": fields.get("set", ""),
        "choices": [c.strip() for c in fields.get("choices", "").split(",") if c.strip()],
        "ask": fields.get("ask", ""),
        "types": fields.get("types", "") or "both",
        "file": str(src),
        "bad": "",
    }
    o["bad"] = _option_bad(o, junk)
    return o


def options(profile: str = "") -> list[dict]:
    """Every schedule option, in file order, broken ones included.

    Each is a dict: key, group, label, hint, default (bool), line, set,
    choices (list), ask, types, file, bad. `bad` non-empty means the table
    shows it greyed with that reason and will not let it be ticked."""
    merged: list[list] = []
    index: dict[str, list] = {}
    for path in options_paths(profile):
        try:
            text = path.read_text()
        except OSError:
            continue
        for fields, junk, src in _option_blocks(text, path):
            key = fields.get("key", "")
            entry = index.get(key) if key else None
            if entry is not None and entry[2] != src:
                entry[0].update(fields)      # a LATER FILE overrides field by field
                entry[1].extend(junk)
                entry[2] = src
                continue
            if entry is not None:
                # A key repeated in ONE file is a mistake, so the SECOND block
                # is the broken one and the index goes on pointing at the
                # first: a profile override must land on the good block, not
                # on the typo that follows it.
                junk = junk + ["duplicate key %r" % key]
            entry = [dict(fields), list(junk), src]
            merged.append(entry)
            if key and key not in index:
                index[key] = entry
    return [_make_option(*e) for e in merged]


def _print_options(profile: str = "") -> int:
    """`muxconfig.py --options [profile]` -- the table, for a reader with no
    dashboard and for the sandbox tests."""
    opts = options(profile)
    for p in options_paths(profile):
        print("# %s%s" % (p, "" if p.exists() else "   (absent)"))
    if not opts:
        print("no options")
        return 1
    print("%-12s %-9s %-5s %-14s %-5s %s"
          % ("KEY", "GROUP", "DEF", "KIND", "TYPES", "LABEL"))
    bad = 0
    for o in opts:
        kind = ("set:" + o["set"]) if o["set"] else ("ask:" + o["ask"]) if o["ask"] else "line"
        if o["bad"]:
            bad += 1
        print("%-12s %-9s %-5s %-14s %-5s %s"
              % (o["key"] or "-", o["group"], "on" if o["default"] else "off",
                 kind, o["types"],
                 ("BAD — " + o["bad"]) if o["bad"] else o["label"]))
    print("\n%d option(s), %d broken" % (len(opts), bad))
    return 2 if bad else 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--options":
        sys.exit(_print_options(sys.argv[2] if len(sys.argv) > 2 else ""))
    print(__doc__.strip())
    sys.exit(2)
