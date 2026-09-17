#!/usr/bin/env bash
# Take the sandbox tmux server and the heartbeat faker down.
. "$(dirname "$0")/env.sh"
tmux kill-server 2>/dev/null || true
if [ -f "${SB:?}/heartbeat.pid" ]; then
  kill "$(cat "${SB:?}/heartbeat.pid")" 2>/dev/null || true
  rm -f -- "${SB:?}/heartbeat.pid"
fi
