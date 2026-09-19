#!/usr/bin/env bash
# mux_run_dir (profile.sh): where the no-systemd watchdog's pid file goes.
#
#   bash tests/test_run_dir.sh
#
# `su user` hands the new user root's XDG_RUNTIME_DIR, and writing the pid file
# there was "Permission denied" on every run after the first; unset, it fell
# back to a /tmp shared by every user. The rule: XDG_RUNTIME_DIR when it is
# ours and writable, else a 0700 directory of our own under $TMPDIR, else the
# account's state dir -- and muxtopus must start its watchdog without an error
# under the `su` environment.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
FAILS=0; PASSES=0
ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/mxrun-XXXXXX")"
export HOME="$SB/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_STATE_HOME="$HOME/.local/state"
export XDG_DATA_HOME="$HOME/.local/share" TMPDIR="$SB/tmp"
unset CLAUDE_CONFIG_DIR MUXTOPUS_CONFIG MUXTOPUS_HOME TMUX
mkdir -p "$HOME" "$TMPDIR"

# THE SANDBOX'S OWN TMUX SERVER, NAMED BY ITS SOCKET. Inside a tmux pane tmux
# takes its socket from $TMUX and ignores TMUX_TMPDIR, so a bare `tmux ...`
# here would reach the REAL server. $TMUX is unset above, every muxtopus run
# below goes through `env -u TMUX` as well, and every tmux this file runs
# itself carries -S. Cleanup kills only a watchdog whose HOME is this sandbox.
export TMUX_TMPDIR="$SB/tmuxsock"; mkdir -p "$TMUX_TMPDIR"
SOCK="$TMUX_TMPDIR/tmux-$(id -u)/default"
WDPID=""
cleanup() {
  if [ -n "$WDPID" ] && tr '\0' '\n' < "/proc/$WDPID/environ" 2>/dev/null | grep -qxF "HOME=$HOME"; then
    kill "$WDPID" 2>/dev/null
  fi
  [ -S "$SOCK" ] && tmux -S "$SOCK" kill-server 2>/dev/null
  chmod -R u+rwx "$SB" 2>/dev/null
  [ -n "${KEEP_SANDBOX:-}" ] || rm -rf "$SB"
}
trap cleanup EXIT

run_dir() { ( . "$REPO/profile.sh"; mux_run_dir ); }

echo "== XDG_RUNTIME_DIR that is ours"
mkdir -p "$SB/run"
check "is used as it is" test "$(XDG_RUNTIME_DIR="$SB/run" run_dir)" = "$SB/run"

echo "== XDG_RUNTIME_DIR we cannot write (root's, after su)"
mkdir -p "$SB/run-ro"; chmod 500 "$SB/run-ro"
d="$(XDG_RUNTIME_DIR="$SB/run-ro" run_dir)"
check "falls back to \$TMPDIR/muxtopus-<uid>" test "$d" = "$TMPDIR/muxtopus-$(id -u)"
check "which exists" test -d "$d"
check "and is 0700" test "$(stat -c %a "$d")" = 700
chmod 700 "$SB/run-ro"

echo "== XDG_RUNTIME_DIR unset"
check "the same per-uid directory, not /tmp itself" test "$(env -u XDG_RUNTIME_DIR bash -c "$(declare -f run_dir); REPO='$REPO' run_dir")" = "$TMPDIR/muxtopus-$(id -u)"

echo "== XDG_RUNTIME_DIR names a file, not a directory"
: > "$SB/notadir"
check "falls back" test "$(XDG_RUNTIME_DIR="$SB/notadir" run_dir)" = "$TMPDIR/muxtopus-$(id -u)"

echo "== muxtopus under the su environment starts its watchdog without an error"
# root's runtime dir, as `su test` hands it over: there, and not ours to write.
# No systemd --user: a systemctl stub that fails sits first on PATH, and
# no real claude either. The
# account is created rather than asked about (--create); -d does not attach.
mkdir -p "$SB/run-root" "$SB/bin"; chmod 500 "$SB/run-root"
printf '#!/bin/sh\nexit 1\n' > "$SB/bin/systemctl"; chmod +x "$SB/bin/systemctl"
# The session's second window runs `claude`: a stub, never the real CLI.
printf '#!/bin/sh\nexit 0\n' > "$SB/bin/claude"; chmod +x "$SB/bin/claude"
mx() {
  env -u TMUX XDG_RUNTIME_DIR="$SB/run-root" PATH="$SB/bin:$PATH" \
      MUXTOPUS_HOME="$HOME/muxhome" "$REPO/muxtopus" "$@"
}
out="$(mx --create -d mxrun "$SB" 2>&1)"
check "no 'Permission denied'" bash -c '! grep -q "Permission denied" <<<"$1"' _ "$out"
check "watchdog started in the background" grep -q 'watchdog started in the background' <<<"$out"
check "the session is on the sandbox server" tmux -S "$SOCK" has-session -t =mxrun
pidf="$TMPDIR/muxtopus-$(id -u)/muxtopus-wd.pid"
check "pid file in our directory" test -s "$pidf"
WDPID="$(cat "$pidf" 2>/dev/null)"
check "and it names a watchdog" bash -c 'ps -o args= -p "$1" | grep -q claude-watchdog' _ "${WDPID:-0}"
check "which did not inherit a \$TMUX" bash -c '! tr "\0" "\n" < "/proc/$1/environ" | grep -q "^TMUX="' _ "${WDPID:-0}"
out2="$(mx -d mxrun "$SB" 2>&1)"
check "a second run starts no second watchdog" bash -c '! grep -q "watchdog started" <<<"$1"' _ "$out2"
check "the pid is the same" test "$(cat "$pidf" 2>/dev/null)" = "$WDPID"
out3="$(mx -l 2>&1)"
check "-l reports it running (no systemd)" grep -q 'running (no systemd)' <<<"$out3"

echo
echo "$PASSES passed, $FAILS failed"
[ "$FAILS" = 0 ]
