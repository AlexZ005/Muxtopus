# The sandbox: sourced by every helper. SB is the fake machine's root and
# every path below is built from "${SB:?}", so an unset variable aborts the
# command instead of resolving to / -- the accident a bare `rm $VAR/...` is.
#
# SCRIPTS is the CHECKOUT this harness lives in, found from this file rather
# than hard-coded, so the same harness drives a worktree and the main tree.
SANDBOX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPTS="$(cd "${SANDBOX_DIR}/../.." && pwd)"
export SB="${SB:-${TMPDIR:-/tmp}/muxsplit-sandbox}"

export HOME="${SB:?}/home"
export XDG_CONFIG_HOME="${SB:?}/config"
export XDG_STATE_HOME="${SB:?}/state"
export MUXTOPUS_CONFIG="${SB:?}/config/muxtopus/config"
export PATH="${SANDBOX_DIR}/bin:${SB:?}/home/.local/bin:$PATH"
export EDITOR=/usr/bin/true
# A SANDBOX-ONLY ACCOUNT. Not decoration: the profile suffixes the watchdog
# state dir and the tmux session, and it makes the lanes table -- which reads
# the real /proc and cannot be faked -- find nothing, because every real dev
# server on this machine belongs to some other account. A reproducible frame
# on a working machine is what this one line buys.
export CLAUDE_CONFIG_DIR="${SB:?}/home/.claude-mxsplit"
# Forks are read from here in the schedules view; point it at the fake machine
# or the view lists the user's real, unanswered questions.
export MUXTOPUS_QUESTIONS_DIR="${SB:?}/muxhome/questions"
# The tmux session the dashboard's own helpers address.
export SANDBOX_SESSION="mxsplit"
