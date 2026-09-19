#!/usr/bin/env python3
"""The dashboard's Restore row (docs/restore.md): in the esc menu only while
the watchdog holds a frozen window snapshot, and reading it right.

    python3 tests/test_restore_row.py     (needs rich, like the dashboard)
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="muxrestore-")
os.environ["HOME"] = TMP
os.environ["XDG_STATE_HOME"] = TMP + "/state"
os.environ["XDG_CONFIG_HOME"] = TMP + "/config"
os.environ.pop("CLAUDE_CONFIG_DIR", None)
os.environ.pop("TMUX", None)

from rich.console import Console  # noqa: E402

from dashboard.app import App  # noqa: E402
from dashboard.core import WATCHDOG_DIR  # noqa: E402
from dashboard import data  # noqa: E402
from dashboard.menus import mux  # noqa: E402

FAILS = PASSES = 0


def check(cond, what):
    global FAILS, PASSES
    if cond:
        PASSES += 1
        print("  ok   %s" % what)
    else:
        FAILS += 1
        print("  FAIL %s" % what)


app = App(2.0, Console(width=120, height=40, force_terminal=False))
menu = mux.MuxMenu(app)
labels = lambda: [it.get("label", "") for it in menu.mux_menu_entries()]

check(data.frozen_snapshot() is None, "no state dir: nothing frozen")
check(not any(l.startswith("Restore") for l in labels()), "..and no Restore row")

WATCHDOG_DIR.mkdir(parents=True, exist_ok=True)
snap = WATCHDOG_DIR / "windows.last.tsv"
snap.write_text("#lost\t1789800300\t1789800000\n"
                "@1\t0\tstatus\t/home/x\t%1\t-\t-\t-\t-\t-\t-\t-\n"
                "@2\t1\t➥a\t/home/x/a\t%2\tsid-a\t-\tfable\thigh\tbypassPermissions\ta.md\t1\n"
                "@3\t2\t➥➥b\t/home/x/b\t%3\tsid-b\ta\t-\t-\t-\tb.md\t2\n")
f, rows, seen = data.frozen_snapshot()
check(f == snap and rows == 3 and seen == 1789800000.0, "frozen_snapshot: the file, 3 rows, the last-seen time")
row = [l for l in labels() if l.startswith("Restore")]
check(len(row) == 1 and row[0].startswith("Restore 3 windows from "), "one Restore row, counting the rows: %r" % row)
order = labels()
check(order.index(row[0]) < order.index([l for l in order if l.startswith("Disconnect")][0]),
      "..placed with the switches, above Disconnect")
entry = [it for it in menu.mux_menu_entries() if it.get("label", "").startswith("Restore")][0]
entry["act"]()
check(app.confirm is not None and app.confirm["label"].startswith("Restore 3 windows from "),
      "activating it asks first")

snap.write_text("#seen\t1\n")
check(data.frozen_snapshot() == (snap, 0, 0.0), "a headerless or live-headed file reads as zero rows, unknown time")
snap.unlink()
check(data.frozen_snapshot() is None, "gone: nothing to restore")

print()
if FAILS:
    print("%d FAILED, %d passed" % (FAILS, PASSES))
    sys.exit(1)
print("%d passed" % PASSES)
