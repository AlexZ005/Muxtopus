#!/usr/bin/env python3
"""A window asked for with `c` actually gets opened, and quickly.

    python3 tests/test_schedule_launch.py

THE BUG THIS GUARDS. `c` does not open a window. It writes a schedule entry
with `at:` already past, and the WATCHDOG opens it on its next pass. Two
things can silently break that, and on a fresh Ubuntu box both did:

  1. check_schedules returns at its first line when the watchdog is
     disarmed -- and the no-systemd start path never armed it, because
     `: > "$ENABLED"` lived only in the systemd --install branch. The daemon
     had been up 39 minutes, an entry had been `pending` for 19 of them, and
     the log said "0 pending schedule(s)".
  2. Nothing told the dashboard, which reported "scheduled" either way.

SOURCE INVARIANTS, not behaviour: the daemon is a 3000-line bash loop that
needs a tmux server, a real claude and half a minute to show any of this, so
what is checked here is that the pieces are still wired to each other. The
behaviour itself is tests/test_restore.sh's and the sandbox's business.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
fails = 0


def ok(cond, what):
    global fails
    if cond:
        print("ok   " + what)
    else:
        fails += 1
        print("FAIL " + what)


wd = (ROOT / "claude-watchdog.sh").read_text()
ns = (ROOT / "dashboard" / "views" / "newsession.py").read_text()

# ---------------------------------------------------------------- the gate
# Not a complaint about the gate -- it is right that a disarmed watchdog does
# nothing. It is the REASON the two checks below have to exist.
ok(re.search(r"check_schedules\(\)\s*\{\s*\n\s*\[ -f \"\$ENABLED\" \] \|\| return 0", wd)
   is not None,
   "check_schedules is still gated on $ENABLED (so the rest of this matters)")

# ------------------------------------------------------- armed on first run
ok('ARMED_ONCE="$STATE_DIR/armed.once"' in wd,
   "the arm/disarm decision has a record (armed.once)")
ok(re.search(r'--on\)\s+: > "\$ENABLED"; : > "\$ARMED_ONCE"', wd) is not None,
   "--on records that the decision was made")
ok(re.search(r'--off\)\s+rm -f "\$ENABLED"; : > "\$ARMED_ONCE"', wd) is not None,
   "--off records it too, so disarming STICKS across restarts")
first_start = re.search(r'if \[ ! -f "\$ARMED_ONCE" \]; then(.{0,600}?)\n  fi', wd, re.S)
ok(first_start is not None, "the daemon has a first-start arming block")
if first_start:
    body = first_start.group(1)
    ok(': > "$ARMED_ONCE"' in body, "...which records the decision it just made")
    ok(': > "$ENABLED"' in body, "...and arms when nothing was ever decided")
    ok("log " in body, "...and says so in the log rather than doing it silently")

# ----------------------------------------------------------- the fast path
ok("--nudge)" in wd, "the watchdog takes --nudge")

# THE SIGNAL MUST BE HARMLESS TO A DAEMON THAT DOES NOT TRAP IT.
# An earlier release sent SIGUSR1, whose default action is TERMINATE, so the
# first `c`
# after an upgrade killed any daemon still running the older script -- which
# is every daemon that had not been restarted. Measured on a real box: the
# personal watchdog died on the first nudge and survived only because systemd
# restarted it. On a machine with no systemd it would have stayed dead.
#
# SIGCONT's default action is to continue an already-running process, i.e.
# nothing, and bash can still trap it.
ok("kill -USR1" not in wd,
   "--nudge does NOT send SIGUSR1: its default action is to KILL an old daemon")
ok("kill -CONT" in wd,
   "it sends SIGCONT, which an untrapping daemon safely ignores")
ok("trap 'nudge' CONT" in wd, "and the daemon traps SIGCONT")
ok(re.search(r"nudge\(\) \{ _NUDGED=1; \[ -n \"\$_SLEEP\" \] && kill \"\$_SLEEP\"", wd)
   is not None,
   "a nudge kills the sleep in flight")
ok(re.search(r'\[ -n "\$_NUDGED" \] && continue', wd) is not None,
   "a nudge that lands DURING a pass is not swallowed")
ok(re.search(r"while :; do\n\s*#.*\n\s*#.*\n\s*_NUDGED=\"\"", wd) is not None
   or re.search(r"_NUDGED=\"\"\n\s*pass", wd) is not None,
   "the flag is cleared before the pass, not after it")
ok("daemon_pid()" in wd, "there is one place that finds the running daemon")
ok(re.search(r'--nudge\).{0,200}daemon\.pid', wd, re.S) is not None,
   "a nudge is only sent to a daemon whose pid file says it will CATCH it")
# The pid file is the proof the trap exists, so it must be published AFTER
# the trap and not before.
trap_at = wd.index("trap 'nudge' CONT")
pid_at = wd.index('"$$" > "$STATE_DIR/daemon.pid"')
ok(pid_at > trap_at,
   "the daemon publishes its pid AFTER installing the trap, never before")
code = "\n".join(l for l in wd.splitlines() if not l.lstrip().startswith("#"))
ok("pgrep" not in code,
   "and it is not pgrep -- two accounts run two daemons from one script path")

# --------------------------------------------------- what the dashboard does
ok("_nudge_watchdog" in ns, "the form nudges the watchdog after writing")
ok('"--nudge"' in ns, "...with --nudge")
ok("WATCHDOG_ENABLED.exists()" in ns,
   "the form knows whether the watchdog can act at all")
ok(ns.count("WATCHDOG_ENABLED.exists()") >= 2,
   "...and says so in BOTH places: the form's rows and the message after Create")
ok("DISARMED" in ns, "the words the user reads name the actual problem")

print("%s" % ("all passed" if not fails else "%d failed" % fails))
sys.exit(1 if fails else 0)
