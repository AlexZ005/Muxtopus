#!/usr/bin/env python3
"""Settings ▸ Reports ▸: the knobs of the watchdog's reports to the parent.

    .venv/bin/python tests/test_reports_menu.py

The watchdog half is tests/test_stall_reports.sh. This holds the menu's:

  * every knob is a config key in both halves, and a reports-menu setting;
  * each refuses what the daemon could not use (minutes that are not
    minutes, a WATCHDOG_REPORT that is not on / notify-only / off), writes
    what it can into dashboard.conf, and an empty line removes the key;
  * an unset row SAYS its default -- and the two that default to off read
    off, because an onoff row that read an empty value as on would show the
    nudge as switched on when nothing nudges anybody.
"""
import atexit
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOME = tempfile.mkdtemp(prefix="mux-reports-menu-")
atexit.register(shutil.rmtree, HOME, ignore_errors=True)
os.environ.update(HOME=HOME, XDG_CONFIG_HOME=HOME + "/.config",
                  XDG_STATE_HOME=HOME + "/.local/state", XDG_DATA_HOME=HOME + "/.local/share")
for _k in ("MUXTOPUS_CONFIG", "MUXTOPUS_HOME", "MUXTOPUS_DIR", "CLAUDE_CONFIG_DIR", "TMUX"):
    os.environ.pop(_k, None)
for _k in [k for k in os.environ if k.startswith(("WATCHDOG_", "DASHBOARD_", "MUXTOPUS_"))]:
    os.environ.pop(_k, None)
sys.path.insert(0, str(ROOT))

import muxconfig  # noqa: E402
import muxsettings  # noqa: E402
from dashboard.menus import reports as rm  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails += 1


print("== the keys")
muxsettings.register(rm.REPORT_KEYS, menu="reports")
ok(list(muxsettings.keys_of("reports")) == list(rm.REPORT_KEYS), "every knob is a reports-menu setting")
for k, meta in rm.REPORT_KEYS.items():
    ok(muxconfig.KEYS.get(k) == meta["default"],
       "%s: the menu's default is muxconfig's (%r)" % (k, meta["default"]))
sh = (ROOT / "profile.sh").read_text()
ok(all(("\n%s=%s\n" % (k, m["default"])) in sh for k, m in rm.REPORT_KEYS.items()),
   "..and profile.sh's, which is what the daemon reads")
keys = list(muxconfig.KEYS)
ok(keys[keys.index("WATCHDOG_STALL_MIN"):keys.index("WATCHDOG_STALL_MIN") + len(rm.REPORT_KEYS)]
   == list(rm.REPORT_KEYS), "in muxconfig.KEYS' order")

print("== what each refuses and writes")
ok(muxsettings.put("WATCHDOG_STALL_MIN", "soon") != "", "a stall time that is not minutes is refused")
ok(muxsettings.put("WATCHDOG_REPORT", "loud") != "", "a WATCHDOG_REPORT that is not a choice is refused")
ok(muxsettings.put("WATCHDOG_CLOSE_FINISHED", "never") != "", "close-finished takes off or minutes")
ok(muxsettings.put("WATCHDOG_CLOSE_FINISHED", "30") == "", "..30 is written")
ok(muxsettings.put("WATCHDOG_CLOSE_FINISHED", "off") == "", "..and so is off")
ok(muxsettings.put("WATCHDOG_STALL_MIN", "10") == "", "a stall time of 10 is written")
conf = muxsettings.dashboard_conf_path("").read_text()
ok('WATCHDOG_STALL_MIN="10"' in conf, "..into dashboard.conf, where profile.sh reads it")
m = rm.ReportsMenu(app=None)
said = m._put("WATCHDOG_STALL_MIN", "")
ok(said.startswith("A lane is stalled after (minutes) = 15 "), "an empty line in the menu writes the default: %r" % said)
ok(muxsettings.get("WATCHDOG_STALL_MIN") == "15", "..which reads back as 15")

print("== what an unset row says")
ok(m.shown("WATCHDOG_STALL_MIN", "") == "(default: 15)", "stall: the default, said")
ok(m.shown("WATCHDOG_NUDGE_STALLED", "") == "off", "the nudge is off by default, and reads off")
ok(m.shown("WATCHDOG_NUDGE_STALLED", "on") == "ON", "..and ON when switched on")
ok(m.shown("WATCHDOG_CLOSE_FINISHED", "") == "(default: off)", "close-finished: off by default")
ok(m.shown("WATCHDOG_REPORT", "notify-only") == "notify-only", "a set value shows itself")

print()
print("%d FAILED" % fails if fails else "all passed")
sys.exit(1 if fails else 0)
