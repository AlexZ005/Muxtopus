#!/usr/bin/env bash
# `c` lands you in the new window at once.
#
#   bash tests/test_create_latency.sh
#
# The sandbox of tests/notify_sandbox.sh (-L mxnotify, a fake claude that
# records every key typed into it and shows whatever $HOME/fake-screen holds);
# nothing here reaches a real pane or schedule. Run it on its own: the notify
# sandboxes share a socket name and fake each other's failures when two run at
# once.
#
# WHAT WAS SLOW, measured on the author's box with 19 sessions open: `c`
# wrote its entry and nudged the watchdog, and the nudge only cut the SLEEP
# short -- the pass it woke scanned every session (5.5-9.5 s) before it
# reached the schedules; the launcher then wrote the window's tree row only
# after claude was ready and the brief pasted; and the dashboard follows that
# row. So the user waited on the dashboard for all of it. Now:
#
#   1. the tree row is written the moment the window opens, while claude is
#      still starting -- and the paste still arrives once it is ready;
#   2. a nudge that lands while a pass is scanning is answered at the next
#      session boundary, before the scan finishes;
#   3. a nudge that wakes the sleep launches BEFORE the woken pass scans.
#
# THE SLOW PASS IS MADE, NOT HOPED FOR: twelve live session files and a jq
# that takes 0.15 s a call, so a scan is ~13 s here on any machine -- long
# enough that "before the scan finished" is a fact about ORDER (status.tsv is
# written when the scan ends) and not a race against a fast box.
set -uo pipefail
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"
SC="$HOME/.code/schedules"; ST="$XDG_STATE_HOME/claude-watchdog"
entry() {  # entry NAME TYPE [body]
  { printf 'type: %s\nat: 2020-01-01 00:00\nslug: %s\ncwd: %s\nstatus: pending\n---\n' "$2" "$1" "$HOME"
    [ -n "${3:-}" ] && printf '%s\n' "$3"; } > "$SC/$1.md"
}
keys() { cat "$HOME/fake-claude.keys" 2>/dev/null | tr -d '\n\\'; }
row_of() { awk -F'\t' -v s="$1" '$1==s{print $3}' "$ST/tree.tsv" 2>/dev/null; }
now() { date +%s.%N; }
since() { awk -v a="$1" -v b="$(now)" 'BEGIN{printf "%.1f", b-a}'; }
# wait_for SECONDS CMD...: poll every 50 ms; 0 once CMD succeeds
wait_for() { local n=$(( $1 * 20 )); shift; while [ "$n" -gt 0 ]; do "$@" && return 0; sleep 0.05; n=$((n-1)); done; return 1; }
has_row() { [ -n "$(row_of "$1")" ]; }
keys_have() { keys | grep -q "$1"; }

tmux new-session -d -s claude -n home -x 120 -y 40 "sleep 600"
"$W" --on >/dev/null

echo "== 1. the window is in the tree while claude is still starting"
printf 'starting\n' > "$HOME/fake-screen"          # no prompt yet
rm -f "$HOME/fake-claude.keys"
entry early work "carry on early"
"$W" --once >/dev/null 2>&1 & once=$!; SB_PIDS+=("$once")
wait_for 10 has_row early
wid="$(row_of early)"
check "a tree row for the window before claude reached a prompt" test -n "$wid"
check "..naming a window that exists" bash -c 'tmux list-windows -a -F "#{window_id}" | grep -qxF "$1"' _ "$wid"
check "..with nothing pasted into it yet" bash -c '! grep -q carry <<<"$1"' _ "$(keys)"
check "..and the entry not yet marked launched" grep -q '^status: pending' "$SC/early.md"
printf '● ready\n❯ \n' > "$HOME/fake-screen"       # claude is ready now
wait_for 15 grep -q '^status: launched' "$SC/early.md"
wait_for 5 keys_have carry
check "the paste still arrives once claude is ready" grep -q carry <<<"$(keys)"
check "..and the entry is marked launched" grep -q '^status: launched' "$SC/early.md"
check "..with the same window in the tree" test "$(row_of early)" = "$wid"
wait "$once" 2>/dev/null

# THE SLOW PASS. Real jq behind a 0.15 s delay, first on PATH for the daemon
# only (mux_json calls `command jq`), and twelve sessions whose pids are live.
realjq="$(command -v jq)"
printf '#!/bin/sh\nsleep 0.15\nexec %s "$@"\n' "$realjq" > "$SB/bin/jq"; chmod +x "$SB/bin/jq"
for i in $(seq 12); do
  sleep 600 & p=$!; SB_PIDS+=("$p")
  printf '{"pid":%s,"sessionId":"busy-%s","cwd":"%s","version":"0","status":"idle","kind":"interactive","tmux":""}\n' \
    "$p" "$i" "$HOME" > "$HOME/.claude/sessions/$p.json"
done
rm -f "$ST/status.tsv" "$ST/heartbeat"
"$W" --daemon >/dev/null 2>&1 & dpid=$!; SB_PIDS+=("$dpid")
# Where --nudge finds a daemon with no systemd unit: the pid file muxtopus
# writes when it nohups one (the sandbox's XDG_RUNTIME_DIR is its run dir).
printf '%s\n' "$dpid" > "$SB/run/muxtopus-wd.pid"
wait_for 10 test -s "$ST/daemon.pid"

echo "== 2. a nudge during the scan is answered before the scan ends"
sleep 1.5
check "the first pass is still scanning (no status.tsv yet)" test ! -f "$ST/status.tsv"
entry midpass plan
t0="$(now)"; "$W" --nudge; rc=$?
check "--nudge reached the daemon" test "$rc" = 0
wait_for 8 has_row midpass
dt="$(since "$t0")"
check "the window opened before the scan finished" bash -c '[ -n "$1" ] && [ ! -f "$2" ]' _ "$(row_of midpass)" "$ST/status.tsv"
check "..within 3 s of the nudge (took ${dt}s)" awk -v d="$dt" 'BEGIN{exit !(d < 3)}'

echo "== 3. a nudge that wakes the sleep launches before the woken pass scans"
wait_for 40 test -f "$ST/heartbeat"                   # the first pass is over
check "the first pass finished" test -f "$ST/heartbeat"
sleep 1                                               # ...and the daemon is asleep
before="$(stat -c %Y.%N "$ST/status.tsv" 2>/dev/null)"
entry asleep plan
t0="$(now)"; "$W" --nudge
wait_for 8 has_row asleep
dt="$(since "$t0")"
check "the window opened (took ${dt}s)" has_row asleep
check "..within 3 s of the nudge" awk -v d="$dt" 'BEGIN{exit !(d < 3)}'
check "..before the woken pass rewrote status.tsv" bash -c '[ -n "$1" ] && [ "$2" = "$3" ]' _ "$(row_of asleep)" "$(stat -c %Y.%N "$ST/status.tsv")" "$before"
wait_for 10 grep -q 'schedule asleep.md: launched' "$ST/log"
check "the log says it launched, once claude was ready" grep -q 'schedule asleep.md: launched' "$ST/log"

sb_done
