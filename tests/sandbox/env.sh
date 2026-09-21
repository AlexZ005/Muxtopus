# The sandbox: sourced by every helper. SB is the fake machine's root and
# every path below is built from "${SB:?}", so an unset variable aborts the
# command instead of resolving to / -- the accident a bare `rm $VAR/...` is.
#
# SCRIPTS is the CHECKOUT this harness lives in, found from this file rather
# than hard-coded, so the same harness drives a worktree and the main tree.
SANDBOX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# SCRIPTS defaults to the checkout this harness lives in -- so the same
# harness drives a worktree and the main tree -- and a caller may point it
# somewhere else, which is how onefile.sh drives a COPY of the checkout with
# one extra file in it.
export SCRIPTS="${SCRIPTS:-$(cd "${SANDBOX_DIR}/../.." && pwd)}"
# A LANE THAT SETS ITS OWN SB MUST GIVE IT THE SAME LENGTH as this default
# (21 characters). normalise.py masks the sandbox root to <SB>, which hides
# the TEXT of the path but not its WIDTH: a panel pads its content to a fixed
# width, so a root one character shorter moves the closing border on every
# line that names it, and the goldens then differ for a reason that has
# nothing to do with the dashboard. Measured, not guessed -- it cost six
# spurious diffs on the settings screens to find. `/tmp/muxhandover-sbox` and
# `/tmp/muxsplit-sandbox` are both 21.
export SB="${SB:-${TMPDIR:-/tmp}/muxsplit-sandbox}"

export HOME="${SB:?}/home"
export XDG_CONFIG_HOME="${SB:?}/config"
export XDG_STATE_HOME="${SB:?}/state"
export MUXTOPUS_CONFIG="${SB:?}/config/muxtopus/config"
export PATH="${SANDBOX_DIR}/bin:${SB:?}/home/.local/bin:$PATH"
# The editor the dashboard suspends into. /usr/bin/true by default -- a real
# $EDITOR leaking in here would open nano inside a golden run and hang it --
# and a test that wants to see WHICH FILE was opened sets SANDBOX_EDITOR to a
# stub that records its argv. Opt-in, so nothing leaks.
export EDITOR="${SANDBOX_EDITOR:-/usr/bin/true}"
# A SANDBOX-ONLY ACCOUNT. Not decoration: the profile suffixes the watchdog
# state dir and the tmux session, and it makes the lanes table -- which reads
# the real /proc and cannot be faked -- find nothing, because every real dev
# server on this machine belongs to some other account. A reproducible frame
# on a working machine is what this one line buys.
# The account's NAME, so that a caller with a different story to tell -- the
# screenshot, with a fixture set of its own -- can name its account something
# a reader would see on a real machine. Every path that carries the suffix
# is built from it; the default is the one the goldens were taken under.
export SANDBOX_ACCOUNT="${SANDBOX_ACCOUNT:-mxsplit}"
export CLAUDE_CONFIG_DIR="${SB:?}/home/.claude-${SANDBOX_ACCOUNT:?}"
# Which fixture set setup.sh builds the fake machine from.
export SANDBOX_FIXTURES="${SANDBOX_FIXTURES:-${SCRIPTS:?}/tests/fixtures/dashboard}"
# Forks are read from here in the schedules view; point it at the fake machine
# or the view lists the user's real, unanswered questions.
export MUXTOPUS_QUESTIONS_DIR="${SB:?}/muxhome/questions"
# The tmux session the dashboard's own helpers address, and the SOCKET
# bin/tmux pins itself to. Both are overridable because three lanes now run
# side by side out of their own worktrees, and stop.sh kills a whole server:
# set SANDBOX_SOCKET and SANDBOX_SESSION (and SB) per lane and nobody can
# take down anybody else's dashboard halfway through a capture.
export SANDBOX_SOCKET="${SANDBOX_SOCKET:-mxsplit}"
# The notify conf holds a TOKEN and is the one file the dashboard must never
# read outside a sandbox. HOME is already fake, so the default path is fake
# too; this says so out loud, and a Settings ▸ Notifications row that shells
# out to claude-notify.sh --status cannot reach the real one even if HOME
# were ever to leak.
export CLAUDE_NOTIFY_CONF="${SB:?}/notify.conf"
export SANDBOX_SESSION="${SANDBOX_SESSION:-mxsplit}"
# THE SAME SOCKET, NAMED ON EVERY CALL. profile.sh's mux_tmux passes
# MUXTOPUS_TMUX_SOCKET as -L on every tmux the scripts run, so a watchdog or
# a muxtopus started from here talks to this sandbox's server and no other --
# and the helpers of this harness use the same name through the function
# below, never a bare tmux that would follow the $TMUX of the pane a test is
# typed in (docs/restore.md). bin/tmux stays for the dashboard's own
# forks, which are not this harness's to rewrite.
export MUXTOPUS_TMUX_SOCKET="${SANDBOX_SOCKET:?}"
mux_tmux() { command tmux -L "${SANDBOX_SOCKET:?}" "$@"; }
