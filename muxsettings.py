"""muxsettings -- the dashboard's WRITER for the settings it owns.

muxconfig is a reader by its own charter and stays one. This module is the
other half: it writes the one config file the dashboard owns, and it makes
the one edit to a Claude settings.json that the dashboard is allowed to make.

    ~/.config/muxtopus/dashboard.conf                    every account
    ~/.config/muxtopus/profiles/<name>.dashboard.conf    one named account

WHY A SECOND FILE. `config` is hand-written and full of the user's own
comments, and a program that rewrites it will eventually eat them. So the
dashboard writes a file of its own, in the same KEY="value" shell syntax,
which muxconfig and profile.sh read as two further layers:

    default < environment < config < dashboard.conf
            < profiles/<name>.conf < profiles/<name>.dashboard.conf

The dashboard-written file sits ABOVE the hand-written one at the same scope
-- the menu is where a value was set most recently and most explicitly, and
"set in the menu, read back from disk, same value" can only hold if the file
this writes is the top layer for that account -- and BELOW the account's own
hand-written file, which is the existing rule (a profile file narrows the
scope) and would be the surprise to break.

    register(specs, menu="")                     a module declares its keys
    get(key, profile)            -> str          the effective value ("" = unset)
    put(key, value, profile)     -> str          "" or the complaint; written and REREAD
    dashboard_conf_path(profile) -> Path
    settings_json_path(scope, cwd, config_dir) -> Path
    set_default_mode(path, mode) -> (message, error)   the ONE settings.json write
"""
from __future__ import annotations

import json
import os
import pathlib
import time

from muxconfig import (KEYS, dashboard_conf_path, knob, settings, _read)

# THE PERMISSION MODES, mirrored from SCHED_PERM_MODES in claude-watchdog.sh
# (read from `claude --help` there, not guessed). tests/test_settings.py
# compares the two, so a change to one list without the other fails a test
# rather than launching a window with a flag the CLI refuses.
PERM_MODES = ("acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# What the launcher accepts as a model value; anything else it drops with a
# log line, so this refuses the same set out loud instead.
MODEL_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._[]-")

# EVERY SETTING THE MENU OFFERS, in menu order. `choices` None means the menu
# computes them (the model aliases come from options.md); "" in a choices
# list is the "account default" -- no header field, no flag.
DASHBOARD_KEYS: dict[str, dict] = {
    "DASHBOARD_MENU_LAYOUT": {
        "label": "Menu layout", "kind": "choice",
        "choices": ("table", "modal", "bottom"),
        "hint": "table: under the panel · modal: centred · bottom: the footer"},
    "DASHBOARD_NEW_PERMISSION_MODE": {
        "label": "Default permission mode for a new window", "kind": "choice",
        "choices": ("ask",) + PERM_MODES,
        "hint": "ask: c stops on the mode picker with nothing preselected"},
    "DASHBOARD_PERMANENT_MODE_SCOPE": {
        "label": "Where \"make it permanent\" writes", "kind": "choice",
        "choices": ("project", "account"),
        "hint": "project: <cwd>/.claude/settings.json · account: ~/.claude/settings.json"},
    "DASHBOARD_NEW_WATCHDOG": {
        "label": "Watch a new window", "kind": "onoff",
        "hint": "restart it after a limit; off writes watchdog: off in the entry"},
    "DASHBOARD_NEW_MONITOR": {
        "label": "Monitor a new window", "kind": "onoff",
        "hint": "wind it down near the limit; off writes monitor: off in the entry"},
    "DASHBOARD_NEW_MODEL": {
        "label": "Default model for a new window", "kind": "choice",
        "choices": None, "hint": "a CLI alias (opus, fable…), or the account default"},
    "DASHBOARD_NEW_EFFORT": {
        "label": "Default effort for a new window", "kind": "choice",
        "choices": ("",) + EFFORTS, "hint": "passed as claude --effort"},
    "DASHBOARD_NEW_CWD": {
        "label": "Default working folder", "kind": "text",
        "hint": "offered first by c and used by the schedule create flow"},
    "DASHBOARD_NEW_RC": {
        "label": "Send /rc to a new window", "kind": "onoff",
        "hint": "every scheduled window, unless its entry says rc: off"},
}

# KEYS A MODULE DECLARED AS BELONGING TO ITS OWN MENU (register(..., menu=...)).
# A setting in every other way -- get, put and validate treat it exactly like
# one of the core nine -- but the Settings menu does not draw it, because the
# module that registered it draws it itself. Without this, Settings ▸
# Notifications ▸ would list its seven rows AND the Settings list above it
# would list the same seven, because that list iterates DASHBOARD_KEYS and
# must go on doing so without knowing this module exists.
SUBMENU_KEYS: dict[str, dict] = {}


def spec_of(key: str) -> dict | None:
    """The declaration of one key, whichever half it was registered into."""
    return DASHBOARD_KEYS.get(key) or SUBMENU_KEYS.get(key)


def keys_of(menu: str) -> dict[str, dict]:
    """Every key declared for one submenu, in registration order -- what that
    menu's module draws its rows from."""
    return {k: v for k, v in SUBMENU_KEYS.items() if v.get("menu") == menu}


def register(specs: dict[str, dict], menu: str = "") -> None:
    """A dashboard module declares the settings keys it owns.

    DASHBOARD_KEYS above is the CORE NINE -- the ones the shell and the main
    screens need. A module that adds a setting (notify's seven, handover's
    two) calls this from its register(app) instead of editing that dict, and
    its rows then appear in the Settings menu in registration order after the
    core ones.

    `menu` names a SUBMENU that draws the rows itself (notify passes
    "notify"): the key is a full setting, but the Settings list leaves it to
    that module. A module with one or two settings passes nothing and gets a
    row in Settings for free; a module with seven gives them a menu.

    A KEY MUST ALREADY BE IN muxconfig.KEYS. That list and profile.sh's
    MUX_CONFIG_KEYS are the shell half and the python half of the same
    contract, and tests/test_settings.py compares them name for name and
    order for order; a key that is only in one of them is a value the
    dashboard writes and the shell silently never reads. So the two lists
    stay shared files and a new setting is a three-line change to each --
    which is a conflict two lanes resolve, not a queue they wait in.
    """
    for key, spec in specs.items():
        if spec_of(key) is not None:
            raise ValueError("%s is already a dashboard setting" % key)
        if key not in KEYS:
            raise ValueError(
                "%s is not in muxconfig.KEYS -- add it there and in "
                "profile.sh's MUX_CONFIG_KEYS first, or the shell half will "
                "never read what the menu writes" % key)
        for field in ("label", "kind", "hint"):
            if field not in spec:
                raise ValueError("%s needs a %s" % (key, field))
        if spec["kind"] not in ("choice", "onoff", "text"):
            raise ValueError("%s: kind must be choice, onoff or text" % key)
        if spec["kind"] == "choice" and "choices" not in spec:
            raise ValueError("%s: a choice needs choices" % key)
        if spec.get("scope") not in (None, "", "global"):
            raise ValueError("%s: scope is \"global\" or nothing" % key)
        if menu:
            SUBMENU_KEYS[key] = dict(spec, menu=menu)
        else:
            DASHBOARD_KEYS[key] = spec


HEADER = ("# Written by the muxtopus dashboard (esc → Settings). Edit config or\n"
          "# profiles/<name>.conf by hand instead; this file is rewritten whole.\n")


def scope_of(key: str, profile: str = "") -> str:
    """WHICH ACCOUNT'S dashboard.conf this key is written to: "" is shared.

    Almost every setting is a preference about one account and belongs in
    that account's file. A few are facts about the MACHINE -- the update
    keys govern one installed tree that every account runs -- and writing
    those per account would mean an answer that depends on which account
    happened to be on screen. A spec says so with `scope="global"`, and
    only the WRITE moves: get still reads through this account's layers, so
    a profile file that narrows the key by hand is still what the menu
    shows, and put's read-back is what says the narrowing happened.
    """
    meta = spec_of(key) or {}
    return "" if meta.get("scope") == "global" else profile


def get(key: str, profile: str = "") -> str:
    assert spec_of(key), key
    return knob(key, profile, "") or ""


def validate(key: str, value: str) -> str:
    """Why this value cannot be written, or ""."""
    meta = spec_of(key)
    if "\n" in value or '"' in value:
        return "no quotes or newlines in a value"
    if meta["kind"] == "onoff":
        return "" if value in ("on", "off") else "on or off (got %r)" % value
    # A module's own rule for its own key: `check` in the spec it registered,
    # value -> "" or the complaint, so the rule lives beside the key.
    if meta.get("check"):
        why = meta["check"](value)
        if why:
            return why
    if key == "DASHBOARD_NEW_MODEL":
        return "" if set(value) <= MODEL_OK else "not a model alias: %r" % value
    if meta["kind"] == "choice":
        if value not in meta["choices"]:
            return "one of %s (got %r)" % (
                ", ".join(c or "(account default)" for c in meta["choices"]), value)
        return ""
    if key == "DASHBOARD_NEW_CWD":
        if value and not pathlib.Path(os.path.expanduser(value)).is_dir():
            return "not a directory: %s" % value
        return ""
    return ""


def put(key: str, value: str, profile: str = "") -> str:
    """Write one setting and prove it. Returns "" or the complaint.

    The whole file is rewritten from what it holds plus the change -- it is
    the dashboard's file, so a full rewrite loses nothing -- through a temp
    file and os.replace, so a crash mid-write leaves the old file intact.
    Then the layers are read back from disk, and success is only reported if
    the value read is the value written."""
    assert spec_of(key), key
    why = validate(key, value)
    if why:
        return why
    # THE FILE THE VALUE GOES IN (scope_of): this account's, or the shared
    # one for a setting that is about the machine rather than the account.
    path = dashboard_conf_path(scope_of(key, profile))
    have = _read(path)
    if value == "":
        have.pop(key, None)
    else:
        have[key] = value
    body = HEADER + "".join('%s="%s"\n' % (k, v) for k, v in have.items()
                            if k in KEYS)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(body)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        return "could not write %s: %s" % (path, exc)
    back = settings(profile).get(key, "") or ""
    if back != value:
        return ("wrote %s=%r to %s but read back %r -- a higher layer overrides it"
                % (key, value, path.name, back))
    return ""


def settings_json_path(scope: str, cwd: str, config_dir: str | pathlib.Path) -> pathlib.Path:
    """Where "make it permanent" writes: the project's settings.json or the
    account's. The account one is CONFIG_DIR, not ~/.claude, so a named
    account writes its own."""
    if scope == "account":
        return pathlib.Path(config_dir) / "settings.json"
    return pathlib.Path(cwd) / ".claude" / "settings.json"


def set_default_mode(path: pathlib.Path, mode: str) -> tuple[str, str]:
    """THE ONE WRITE to a Claude settings.json: permissions.defaultMode.

    NESTED, because that is where Claude Code reads it (measured in the real
    ~/.claude/settings.json: {"permissions": {"defaultMode": ...}}); a
    top-level key would be written and never read. Every other key is kept in
    the order it was read. An existing file that is not valid JSON is refused
    untouched -- merging into something unparseable would clobber it. The old
    file is backed up beside itself before the atomic replace.

    Returns (message, error); exactly one is non-empty."""
    if mode not in PERM_MODES:
        return "", "not a permission mode: %r" % mode
    path = pathlib.Path(path)
    data: dict = {}
    existed = path.exists()
    if existed:
        try:
            raw = path.read_text()
        except OSError as exc:
            return "", "cannot read %s: %s" % (path, exc)
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError as exc:
            return "", "not valid JSON, not touched: %s: %s" % (path, exc)
        if not isinstance(data, dict):
            return "", "not a JSON object, not touched: %s" % path
    perms = data.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
        data["permissions"] = perms
    old = perms.get("defaultMode")
    perms["defaultMode"] = mode
    body = json.dumps(data, indent=2) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    bak = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            bak = path.with_name(path.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
            bak.write_text(raw)
        tmp.write_text(body)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        return "", "could not write %s: %s" % (path, exc)
    if not existed:
        return "created %s with permissions.defaultMode = %s" % (path, mode), ""
    if old == mode:
        return "%s already had permissions.defaultMode = %s (backup %s)" % (
            path, mode, bak.name), ""
    return "%s: permissions.defaultMode %s -> %s (backup %s)" % (
        path, old or "(unset)", mode, bak.name), ""
