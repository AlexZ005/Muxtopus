"""muxconfig -- the python half of profile.sh.

Reads the SAME config file the shell reads, so the two halves can never
disagree about where an account's data lives. The format is plain shell
(KEY="value") and this is a READER, not an interpreter: only the keys we
understand are honoured, and anything cleverer in the file is ignored rather
than half-executed.

    from muxconfig import mux_home, profile_of, suffix_of
    mux_home()                     -> Path
    profile_of()                   -> "" | "work"     (from CLAUDE_CONFIG_DIR)
    suffix_of("work")              -> "-work"
"""
import os
import pathlib

HOME = pathlib.Path.home()
KEYS = ("MUXTOPUS_HOME", "MUXTOPUS_DIR")


def read_config() -> dict:
    f = pathlib.Path(os.environ.get(
        "MUXTOPUS_CONFIG",
        os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config")) + "/muxtopus/config"))
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
            v = v.strip().strip('"').strip("'")
            v = v.replace("${HOME}", str(HOME)).replace("$HOME", str(HOME))
            out[k] = v
    except OSError:
        pass
    return out


def mux_home() -> pathlib.Path:
    """Where schedules/, backups/ and handovers/ live.

    Config file, then environment, then the XDG default -- so an install that
    predates this project keeps its paths by having them written down, and a
    fresh one is well behaved with no config file at all.
    """
    cfg = read_config()
    return pathlib.Path(cfg.get("MUXTOPUS_HOME")
                        or os.environ.get("MUXTOPUS_HOME")
                        or (os.environ.get("XDG_DATA_HOME",
                                           str(HOME / ".local" / "share")) + "/muxtopus"))


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
