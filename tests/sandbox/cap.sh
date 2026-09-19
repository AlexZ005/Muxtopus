#!/usr/bin/env bash
# capture the sandbox dashboard pane; any argument keeps colours
. "$(dirname "$0")/env.sh"
mux_tmux capture-pane -p ${1:+-e} -t "${SANDBOX_SESSION:?}:dash" | sed 's/[[:space:]]*$//'
