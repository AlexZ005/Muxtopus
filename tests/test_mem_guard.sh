#!/usr/bin/env bash
# THE MEMORY GUARD (claude-watchdog.sh mem_check / mem_stop_dev), as a test.
#
#   bash tests/test_mem_guard.sh
#
# WHY IT EXISTS. Round 33 on the Deck (29 GB): twelve lanes each left a vite
# dev server running, swap filled, and the scheduler kept opening windows into
# it -- every launch one more claude (~450 MB) on a machine that had none to
# give. A due entry is now HELD while memory is low and launches by itself
# once it recovers.
#
# THE MACHINE IS FAKED, THE DAEMON IS NOT: MUX_MEMINFO points the guard at a
# file this test writes, so a 29 GB box at 3 GB free is one printf. Every
# case runs the real `--once` pass against the real launcher in the sandbox
# of tests/notify_sandbox.sh (its own HOME and XDG dirs, a tmux pinned to a
# private -L socket, a fake claude), so nothing here can reach a real pane,
# a real schedule or a real dev server.
#
# COUNTERFACTUAL: on the watchdog before the guard, the "held" cases launch
# the entry at 3 GB free and the directive cases write nothing -- run this
# file against origin/main's claude-watchdog.sh to see them fail.
SB_SOCKET="mxmem$$"
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="${MEM_GUARD_WATCHDOG:-$REPO/claude-watchdog.sh}"
SC="$HOME/.code/schedules"; ST="$XDG_STATE_HOME/claude-watchdog"
export MUX_MEMINFO="$SB/meminfo"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
# mem AVAIL_GB SWAP_USED_PCT: a 29 GB machine with 16 GB of swap
mem() {
  local a=$(( $1 * 1048576 )) t=16777216
  printf 'MemTotal:       30408704 kB\nMemFree:        %d kB\nMemAvailable:   %d kB\nSwapTotal:      %d kB\nSwapFree:       %d kB\n' \
    "$a" "$a" "$t" $(( t - t * $2 / 100 )) > "$MUX_MEMINFO"
}
memkb() { sed -i "s/^MemAvailable: .*/MemAvailable:   $1 kB/" "$MUX_MEMINFO"; }
entry() {  # entry NAME [at]
  printf 'type: work\nat: %s\nslug: %s\ncwd: %s\nstatus: pending\n---\ncarry on\n' \
    "${2:-2020-01-01 00:00}" "$1" "$HOME" > "$SC/$1.md"
}
launched() { grep -q '^status: launched' "$SC/$1.md"; }
pending() { grep -q '^status: pending' "$SC/$1.md"; }
verdict() { awk -F'\t' -v b="$1.md" '$1==b{print $2}' "$ST/sched-why.tsv"; }
why() { awk -F'\t' -v b="$1.md" '$1==b{print $3}' "$ST/sched-why.tsv"; }
state() { cut -f4 "$ST/memory"; }
pass() { "$W" --once >/dev/null 2>&1; }
printf '● ready\n❯ \n' > "$HOME/fake-screen"
tmux new-session -d -s claude -n home -x 120 -y 40 "sleep 600"
"$W" --on >/dev/null

echo "== plenty of memory: a due entry launches, and the reading is published"
mem 20 10; entry roomy; pass
check "launched" launched roomy
check "memory reads ok" [ "$(state)" = ok ]
check "..with the figures" grep -q $'\t20.0 GB available, swap 10%$' "$ST/memory"

echo "== 3 GB available: the due entry is HELD, not launched"
mem 3 10; entry tight; entry later "2099-01-01 00:00"; pass
check "not launched" pending tight
check "its verdict is held" [ "$(verdict tight)" = held ]
check "..naming the figure and the key" grep -q "3.0 GB available, under WATCHDOG_MEM_MIN_GB=4" <<<"$(why tight)"
check "..and saying it resumes by itself" grep -q "launches by itself once memory recovers" <<<"$(why tight)"
check "an entry not yet due says waiting, not held" [ "$(verdict later)" = waiting ]
check "memory reads low" [ "$(state)" = low ]
check "one log line when it trips" [ "$(grep -c 'memory low: holding new launches' "$ST/log")" = 1 ]
check "the heartbeat counts it pending" [ "$(cut -f3 "$ST/heartbeat")" -ge 2 ]
check "--check says HELD" grep -q "verdict *HELD -- due" <<<"$("$W" --check tight 2>/dev/null)"
pass
check "a second pass: still held" pending tight
check "..and no second log line" [ "$(grep -c 'memory low: holding new launches' "$ST/log")" = 1 ]
since1="$(cut -f5 "$ST/memory")"

echo "== back over the line but inside the margin: still held"
memkb $(( 4 * 1048576 + 200000 )); pass
check "4.2 GB: not launched" pending tight
check "..saying it is recovering, and to what" grep -q "recovering: 4.2 GB available, swap 10% -- waiting for 4.5 GB" <<<"$(why tight)"
check "..the same episode" [ "$(cut -f5 "$ST/memory")" = "$since1" ]

echo "== recovered: the held entry launches by itself"
mem 6 10; pass
check "launched" launched tight
check "memory reads ok" [ "$(state)" = ok ]
check "one log line when it recovers" [ "$(grep -c 'memory recovered:' "$ST/log")" = 1 ]
rm -f "$SC"/*.md

echo "== swap over 80 % with plenty available: held; WATCHDOG_SWAP_MAX_PCT=100 turns that half off"
mem 20 85; entry swappy; pass
check "held" [ "$(verdict swappy)" = held ]
check "..naming swap and its key" grep -q "swap 85% used, over WATCHDOG_SWAP_MAX_PCT=80" <<<"$(why swappy)"
setkey WATCHDOG_SWAP_MAX_PCT 100; pass
check "launched with the swap half off" launched swappy
setkey WATCHDOG_SWAP_MAX_PCT 80
rm -f "$SC"/*.md

echo "== WATCHDOG_MEM_GUARD=off: nothing is held"
mem 1 99; setkey WATCHDOG_MEM_GUARD off; entry unguarded; pass
check "launched at 1 GB" launched unguarded
check "memory reads off" [ "$(state)" = off ]
setkey WATCHDOG_MEM_GUARD on
rm -f "$SC"/*.md

echo "== an unreadable meminfo holds nothing, and says it is blind"
printf 'nothing useful\n' > "$MUX_MEMINFO"; entry blind; pass
check "launched" launched blind
check "memory reads unknown" [ "$(state)" = unknown ]
check "the log says the guard is blind" grep -q "memory guard blind" "$ST/log"
rm -f "$SC"/*.md

echo "== WATCHDOG_MEM_STOP_DEV: the NEWEST lane that owns a dev server is told, once"
# Three claude sessions, oldest first: lane-a and lane-b each run a vite in
# their own worktree; `plan` sits in the parent folder (and is the newest of
# all) -- it must never take a server from the lane that owns it.
W1="$SB/work"; mkdir -p "$W1/lane-a" "$W1/lane-b"
fake_session() {  # fake_session NAME CWD -> a live pid with a session file
  ( cd "$2" && exec sleep 600 ) & local p=$!; SB_PIDS+=("$p")
  printf '{"pid":%s,"sessionId":"sid-%s-0000-0000-0000-000000000000","cwd":"%s","version":"0","status":"idle","kind":"interactive"}\n' \
    "$p" "$1" "$2" > "$HOME/.claude/sessions/$p.json"
  sleep 0.2   # distinct start ticks: newest is decided by them
}
fake_vite() { ( cd "$1" && exec -a "node $1/node_modules/.bin/vite" sleep 600 ) & SB_PIDS+=($!); }
fake_session a "$W1/lane-a"; fake_session b "$W1/lane-b"; fake_session plan "$W1"
fake_vite "$W1/lane-a"; fake_vite "$W1/lane-b"
sleep 0.3
setkey WATCHDOG_MEM_STOP_DEV 1
mem 20 10; pass          # one pass while ok: status.tsv now lists the sessions
mem 3 10; pass
D="$ST/directives"
check "lane-b (the newest owner) is told" [ -s "$D/sid-b-0000-0000-0000-000000000000" ]
check "..to stop the server in its own worktree" grep -q "Stop the dev server you left running in $W1/lane-b now" "$D/sid-b-0000-0000-0000-000000000000"
check "lane-a is not (N=1)" [ ! -e "$D/sid-a-0000-0000-0000-000000000000" ]
check "the planning window in the parent folder is not" [ ! -e "$D/sid-plan-0000-0000-0000-000000000000" ]
check "the log says who was told" grep -q "memory low: told .*(sid-b-00) to stop its dev server in $W1/lane-b" "$ST/log"
pass
check "told once per episode, not every pass" [ "$(grep -c '' "$D/sid-b-0000-0000-0000-000000000000")" = 1 ]
setkey WATCHDOG_MEM_STOP_DEV 2; pass
check "N=2: lane-a is told as well" [ -s "$D/sid-a-0000-0000-0000-000000000000" ]
check "..and still nobody in the parent folder" [ ! -e "$D/sid-plan-0000-0000-0000-000000000000" ]
rm -f "$D"/*
mem 20 10; pass; mem 3 10
"$W" --monitor-optout sid-b-0000-0000-0000-000000000000 >/dev/null
setkey WATCHDOG_MEM_STOP_DEV 1; pass
check "a new episode, lane-b opted out of monitoring: never told" [ ! -e "$D/sid-b-0000-0000-0000-000000000000" ]
check "..so the next-newest owner, lane-a, is" [ -s "$D/sid-a-0000-0000-0000-000000000000" ]
rm -f "$D"/*
setkey WATCHDOG_MEM_STOP_DEV 0; mem 20 10; pass; mem 3 10; pass
check "WATCHDOG_MEM_STOP_DEV=0 (the default): nobody is told" [ -z "$(ls -A "$D" 2>/dev/null)" ]

sb_done
