#!/usr/bin/env bash
# send keys to the sandbox dashboard, then wait a frame
. "$(dirname "$0")/env.sh"
tmux send-keys -t "${SANDBOX_SESSION:?}:dash" "$@"
sleep "${PAUSE:-0.5}"
