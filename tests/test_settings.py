#!/usr/bin/env python3
"""The dashboard's settings store and the one settings.json write.

Run it:  python3 tests/test_settings.py     (no dependency beyond python3)

THREE THINGS ARE PROVEN HERE. The key lists mirrored between the shell and
the python halves are identical (knob() asserts on an unknown key, so a key
in one list only is a crash, not a silent miss). A value put by the menu
reads back through BOTH halves -- muxconfig.settings() and the shell's
mux_load_config -- with the documented precedence. And set_default_mode
merges into an existing settings.json, backs it up, refuses garbage, and
writes the NESTED key Claude Code actually reads.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = pathlib.Path(tempfile.mkdtemp(prefix="muxsettings-"))
CFG = TMP / "config" / "muxtopus"
CFG.mkdir(parents=True)
os.environ["MUXTOPUS_CONFIG"] = str(CFG / "config")
os.environ["HOME"] = str(TMP / "home")
(TMP / "home").mkdir()
for k in list(os.environ):
    if k.startswith(("DASHBOARD_", "WATCHDOG_", "MUXTOPUS_HOME", "MUXTOPUS_PROFILES")):
        del os.environ[k]

import muxconfig                       # noqa: E402
import muxsettings                     # noqa: E402

n = 0


def ok(cond, what):
    global n
    n += 1
    if not cond:
        print("FAIL %d: %s" % (n, what))
        sys.exit(1)


def shell_val(key, profile=""):
    """What profile.sh reads for the same key -- the other half."""
    out = subprocess.run(
        ["bash", "-c", '. "%s/profile.sh"; mux_load_config "%s"; printf "%%s" "${%s:-}"'
         % (ROOT, profile, key)],
        capture_output=True, text=True, env=dict(os.environ)).stdout
    return out


# ---- 1. the mirrors -------------------------------------------------------
sh = re.search(r'MUX_CONFIG_KEYS="\n(.*?)"', (ROOT / "profile.sh").read_text(), re.S).group(1)
sh_keys = [kv.split("=")[0] for kv in sh.split()]
ok(sh_keys == list(muxconfig.KEYS), "MUX_CONFIG_KEYS and muxconfig.KEYS, same names same order")
sh_defaults = {kv.split("=")[0]: kv.split("=", 1)[1] for kv in sh.split()}
for k, d in muxconfig.KEYS.items():
    ok(sh_defaults[k] == ("-" if d is None else d), "default of %s agrees" % k)
wd = (ROOT / "claude-watchdog.sh").read_text()
modes = re.search(r'^SCHED_PERM_MODES="([^"]*)"', wd, re.M).group(1).split()
ok(tuple(modes) == muxsettings.PERM_MODES, "PERM_MODES mirrors SCHED_PERM_MODES")
efforts = re.search(r'^SCHED_EFFORTS="([^"]*)"', wd, re.M).group(1).split()
ok(tuple(efforts) == muxsettings.EFFORTS, "EFFORTS mirrors SCHED_EFFORTS")
for k in muxsettings.DASHBOARD_KEYS:
    ok(k in muxconfig.KEYS, "%s is a config key" % k)

# ---- 2. the store, round-tripped through both halves ---------------------
ok(muxsettings.get("DASHBOARD_MENU_LAYOUT") == "table", "built-in default")
ok(muxsettings.put("DASHBOARD_MENU_LAYOUT", "modal") == "", "put modal")
ok(muxsettings.get("DASHBOARD_MENU_LAYOUT") == "modal", "python reads modal back")
ok(shell_val("DASHBOARD_MENU_LAYOUT") == "modal", "shell reads modal back")
path = muxsettings.dashboard_conf_path("")
ok(path == CFG / "dashboard.conf", "shared file beside config")
ok(not path.with_name("dashboard.conf.tmp").exists(), "no temp file left behind")
ok(path.read_text().startswith("# Written by the muxtopus dashboard"), "header says who writes it")

bad = muxsettings.put("DASHBOARD_MENU_LAYOUT", "sideways")
ok(bad.startswith("one of table, modal, bottom"), "bad choice refused: %r" % bad)
ok(muxsettings.get("DASHBOARD_MENU_LAYOUT") == "modal", "refused value did not land")
ok(muxsettings.put("DASHBOARD_NEW_WATCHDOG", "maybe") != "", "onoff refused")
ok(muxsettings.put("DASHBOARD_NEW_MODEL", 'opus"; rm') != "", "quote refused")
ok(muxsettings.put("DASHBOARD_NEW_MODEL", "opus[1m]") == "", "model alias accepted")
ok(muxsettings.put("DASHBOARD_NEW_CWD", str(TMP / "nope")) != "", "missing dir refused")
ok(muxsettings.put("DASHBOARD_NEW_CWD", str(TMP)) == "", "existing dir accepted")
ok(shell_val("DASHBOARD_NEW_CWD") == str(TMP), "shell reads the path")
ok(muxsettings.put("DASHBOARD_NEW_MODEL", "") == "", "empty unsets")
ok("DASHBOARD_NEW_MODEL" not in path.read_text(), "unset key is not written")
ok(muxsettings.get("DASHBOARD_NEW_MODEL") == "", "unset reads as empty")

# precedence: config < dashboard.conf < profile.conf < profile.dashboard.conf
(CFG / "config").write_text('DASHBOARD_MENU_LAYOUT="bottom"\nDASHBOARD_NEW_EFFORT="low"\n')
ok(muxsettings.get("DASHBOARD_MENU_LAYOUT") == "modal", "dashboard.conf beats config")
ok(muxsettings.get("DASHBOARD_NEW_EFFORT") == "low", "config still sets what the menu did not")
(CFG / "profiles").mkdir()
(CFG / "profiles" / "work.conf").write_text('DASHBOARD_MENU_LAYOUT="bottom"\n')
ok(muxsettings.get("DASHBOARD_MENU_LAYOUT", "work") == "bottom",
   "the account's hand-written file beats the shared dashboard file")
ok(shell_val("DASHBOARD_MENU_LAYOUT", "work") == "bottom", "shell agrees")
ok(muxsettings.put("DASHBOARD_MENU_LAYOUT", "table", "work") == "", "put for work")
ok(muxsettings.dashboard_conf_path("work") == CFG / "profiles" / "work.dashboard.conf",
   "per-account dashboard file beside the profile file")
ok(muxsettings.get("DASHBOARD_MENU_LAYOUT", "work") == "table", "profile dashboard file is the top")
ok(shell_val("DASHBOARD_MENU_LAYOUT", "work") == "table", "shell reads the top layer")
ok(muxsettings.get("DASHBOARD_MENU_LAYOUT") == "modal", "the default account is untouched")
# a layer the writer cannot beat is REPORTED, not hidden
os.environ["MUXTOPUS_PROFILES_DIR"] = str(CFG / "profiles")
(CFG / "profiles" / "work.dashboard.conf").chmod(0o444)
try:
    err = muxsettings.put("DASHBOARD_MENU_LAYOUT", "modal", "work")
    ok(err == "" or "could not write" in err, "unwritable file is reported: %r" % err)
finally:
    (CFG / "profiles" / "work.dashboard.conf").chmod(0o644)

# ---- 3. the one settings.json write ----------------------------------------
sj = TMP / "proj" / ".claude" / "settings.json"
msg, err = muxsettings.set_default_mode(sj, "bypassPermissions")
ok(err == "" and msg.startswith("created"), "created: %r %r" % (msg, err))
data = json.loads(sj.read_text())
ok(data == {"permissions": {"defaultMode": "bypassPermissions"}}, "nested key written")
ok(sj.read_text().endswith("\n"), "trailing newline")

sj.write_text('{\n  "model": "opus",\n  "permissions": {"allow": ["Bash"]},\n  "theme": "dark"\n}\n')
msg, err = muxsettings.set_default_mode(sj, "bypassPermissions")
ok(err == "", "merge ok: %r" % err)
data = json.loads(sj.read_text())
ok(list(data) == ["model", "permissions", "theme"], "key order preserved")
ok(data["permissions"] == {"allow": ["Bash"], "defaultMode": "bypassPermissions"},
   "other permissions kept, defaultMode added")
baks = list(sj.parent.glob("settings.json.bak-*"))
ok(len(baks) == 1 and json.loads(baks[0].read_text())["permissions"] == {"allow": ["Bash"]},
   "the old file is backed up beside it")
ok("(unset) -> bypassPermissions" in msg, "message says what changed: %r" % msg)
msg, err = muxsettings.set_default_mode(sj, "bypassPermissions")
ok(err == "" and "already had" in msg, "idempotent, says so")

sj.write_text("{not json")
msg, err = muxsettings.set_default_mode(sj, "bypassPermissions")
ok(err.startswith("not valid JSON, not touched"), "garbage refused: %r" % err)
ok(sj.read_text() == "{not json", "and untouched")
ok(not sj.with_name("settings.json.tmp").exists(), "no temp left")
msg, err = muxsettings.set_default_mode(sj, "yolo")
ok(err.startswith("not a permission mode"), "unknown mode refused")
sj.write_text("[1, 2]")
msg, err = muxsettings.set_default_mode(sj, "plan")
ok(err.startswith("not a JSON object"), "a list is refused")
ok(muxsettings.settings_json_path("project", "/x/y", "/h/.claude")
   == pathlib.Path("/x/y/.claude/settings.json"), "project path")
ok(muxsettings.settings_json_path("account", "/x/y", "/h/.claude-work")
   == pathlib.Path("/h/.claude-work/settings.json"), "account path uses the config dir")

print("%d assertions passed (%s)" % (n, TMP))
