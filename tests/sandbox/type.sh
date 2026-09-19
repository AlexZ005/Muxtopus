#!/usr/bin/env bash
# Type a string ONE KEY PER WRITE: read_key takes one key per read, so a whole
# string in a single send-keys lands as its first character only.
. "$(dirname "$0")/env.sh"
s="$1"; for ((i=0;i<${#s};i++)); do
  mux_tmux send-keys -t "${SANDBOX_SESSION:?}:dash" -l -- "${s:i:1}"; sleep 0.05
done; sleep 0.4
