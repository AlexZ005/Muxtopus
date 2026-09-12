"""muxconfig -- the python half of profile.sh.

Reads the SAME files the shell reads, so the two halves can never disagree
about where an account's data lives or what a knob is set to. The format is
plain shell (KEY="value") and this is a READER, not an interpreter: only the
keys in KEYS are honoured, and anything cleverer in a file is ignored rather
than half-executed.

Two layers, both optional:

    ~/.config/muxtopus/config                 every account
    ~/.config/muxtopus/profiles/<name>.conf   one named account's overrides

Precedence, lowest first: built-in default, environment, config, profile
file -- the same order profile.sh applies.

    from muxconfig import settings, knob, mux_home, mux_dir, profile_of
    settings("work")               -> dict            everything, effective
    knob("WATCHDOG_SOFT_PCT", "work")  -> "65"
    mux_home("work")               -> Path            that account's home
    mux_dir("schedules", "work")   -> Path            one account's folder
    profile_of()                   -> "" | "work"     (from CLAUDE_CONFIG_DIR)
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
    "CLAUDE_USAGE_MAX_AGE": "20",
    "CLAUDE_USAGE_MODEL": None,
    "CLAUDE_CONTEXT_WINDOW": "1000000",
}
KINDS = ("schedules", "backups", "handovers")


def config_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get(
        "MUXTOPUS_CONFIG",
        os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config")) + "/muxtopus/config"))


def profile_conf_path(profile: str) -> pathlib.Path:
    d = os.environ.get("MUXTOPUS_PROFILES_DIR") or str(config_path().parent / "profiles")
    return pathlib.Path(d) / (profile + ".conf")


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
    if profile:
        out.update(_read(profile_conf_path(profile)))
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
