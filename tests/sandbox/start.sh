#!/usr/bin/env bash
# Start the sandbox tmux server and the dashboard in it. $1 = rows (58);
# COLS = columns (160).
# Leaves the heartbeat faker running; stop.sh takes both down.
. "$(dirname "$0")/env.sh"
"$(dirname "$0")/stop.sh" >/dev/null 2>&1 || true
"$(dirname "$0")/heartbeat.sh" & echo $! > "${SB:?}/heartbeat.pid"
tmux new-session -d -s "${SANDBOX_SESSION:?}" -n dash -x "${COLS:-160}" -y "${1:-58}" \
  "bash -c '. \"$(dirname "$(readlink -f "$0")")/env.sh\"; cd \"${SCRIPTS:?}\"; exec ./deck-status.sh'"
sleep "${BOOT:-2.0}"
