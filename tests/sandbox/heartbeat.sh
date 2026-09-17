#!/usr/bin/env bash
# Keep the watchdog's proof of life fresh while the sandbox runs.
#
# WHY A LOOP and not one stamp: the dashboard calls a heartbeat older than
# STALE_AFTER (75s) "watchdog not running" and draws it red. A route takes
# minutes, so a single stamp would flip the claude panel's title halfway
# through and no two runs would agree on where. This is the daemon's one
# observable behaviour, faked at 5s -- the age itself is masked.
. "$(dirname "$0")/env.sh"
WD="${SB:?}/state/claude-watchdog-mxsplit"
while true; do
  printf '%s\t6\t3\t5\n' "$(date +%s)" > "${WD:?}/heartbeat"
  sleep 5
done
