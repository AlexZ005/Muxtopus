#!/usr/bin/env bash
# A RUN STOPPED BEFORE IT FINISHED: mux-done's .run file, the watchdog's lost
# run (WATCHDOG_LOST_RUN_NUDGE) -- the one line to the lane, the second after
# 30 minutes and no third, the parent told when a label is lost twice or the
# second line went unanswered, --health, the `lost` tag -- a run that
# finished, one still running and a recycled pid, which are not lost -- and
# `run --detach`, which the shell's kill does not reach, and `stop`.
#
#   bash tests/test_lost_run.sh
#
# WHY. MEASURED 2026-10-24: Claude Code's low-memory reaper stopped a lane's
# queued e2e rerun (`mux-done run ... -- e2e-slot ...` in a background shell);
# its notice tells the agent not to start it again until asked, nothing was
# written, and a green release sat 13 h. Here the reaper is a kill of the
# run's process group, which is what it does (SIGTERM to -pgid).
#
# The sandbox and the faked windows are test_pipeline_tools.sh's.
#
# COUNTERFACTUAL: against origin/main (LOST_WATCHDOG=..., LOST_MUXDONE=...)
# no .run file is written, nothing is lost and the lane hears nothing.
SB_SOCKET="mxlost$$"
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="${LOST_WATCHDOG:-$REPO/claude-watchdog.sh}"
MD="${LOST_MUXDONE:-$REPO/mux-done}"
ST="$XDG_STATE_HOME/claude-watchdog"; HO="$HOME/.code/handovers"
WK="$SB/work"; mkdir -p "$ST" "$WK" "$HOME/.claude/projects/p"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
export MUX_SEND_DELAY=0.3

cat > "$SB/lane.sh" <<EOF
#!/bin/bash
printf '{"pid":%s,"sessionId":"sid-%s","cwd":"%s","version":"0","status":"idle","kind":"interactive","tmux":"x:@0.%s"}\\n' \\
  \$\$ "\$1" "\$2" "\$TMUX_PANE" > "\$HOME/.claude/sessions/\$\$.json"
cd "\$2"
printf '● ready\\\\n❯ \\\\n'
exec cat >> "\$HOME/heard-\$1"
EOF
chmod +x "$SB/lane.sh"
lane() { local d="$WK/$1"; mkdir -p "$d"; tmux new-window -d -t claude: -n "$1" "$SB/lane.sh $1 $d"; }
tree() {
  local wid pane
  wid="$(tmux display-message -p -t "claude:$1" '#{window_id}')"
  pane="$(tmux display-message -p -t "claude:$1" '#{pane_id}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "${2:-}" "$wid" "$pane" "$(date +%s)" "$1.md" >> "$ST/tree.tsv"
}
turn() {  # turn NAME MINUTES-AGO [EXTRA-LINE]
  printf '{"type":"assistant","timestamp":"%s","message":{"model":"x","content":[{"type":"text","text":"waiting for the battery"}],"usage":{"input_tokens":1}}}\n' \
    "$(date -u -d "-$2 minutes" +%FT%T.000Z)" > "$HOME/.claude/projects/p/sid-$1.jsonl"
  [ -n "${3:-}" ] && printf '%s\n' "$3" >> "$HOME/.claude/projects/p/sid-$1.jsonl"
  touch -d "-$2 minutes" "$HOME/.claude/projects/p/sid-$1.jsonl"
}
pass() { "$W" --once >/dev/null 2>&1; sleep 1; }
heard() { cat "$HOME/heard-$1" 2>/dev/null; }
nlost() { heard "$1" | grep -c 'was stopped before it finished'; }
nreport() { heard orch | grep -c 'MUXTOPUS watchdog'; }
D="$ST/done/job"
# The run, in a process group of its own so the "reaper" can kill it whole.
start_run() {  # start_run LABEL -> RUN_PID
  MUXTOPUS_SLUG=job setsid "$MD" run "$1" -- bash -c 'sleep 300; : e2e-slot -- npm run e2e' >/dev/null 2>&1 &
  RUN_PID=$!
  for _ in $(seq 50); do [ -f "$D/$1.run" ] && break; sleep 0.1; done
}
reap() { kill -TERM -- "-$1" 2>/dev/null; for _ in $(seq 50); do kill -0 "$1" 2>/dev/null || break; sleep 0.1; done; }
# The watchdog's clock for the second line: the last nudge, N minutes earlier.
age_nudge() {  # age_nudge LABEL MINUTES
  awk -F'\t' -v OFS='\t' -v t=$(( $(date +%s) - $2 * 60 )) 'NR == 2 {$4 = t} {print}' "$D/$1.lost" > "$D/$1.lost.t" && mv "$D/$1.lost.t" "$D/$1.lost"
}

tmux new-session -d -s claude -n home -x 220 -y 40 "sleep 900"
"$W" --on >/dev/null
lane orch; lane job
for l in orch job; do printf '# %s\nnext: wait for the battery\n' "$l" > "$HO/STATUS-$l.md"; done
# The reaper's notice, as the lane's transcript records it: a queued
# task-notification, with the time it was written.
notice() {
  printf '{"type":"user","timestamp":"%s","message":{"role":"user","content":"<task-notification><status>killed</status><summary>Background command \\"e2e rerun\\" was stopped because the system is running low on memory</summary></task-notification>"}}\n' \
    "$(date -u +%FT%T.000Z)" >> "$HOME/.claude/projects/p/sid-job.jsonl"
}
turn job 2; turn orch 1
sleep 2; tree orch; tree job orch

echo "== mux-done: a run in flight"
start_run bat
check "a .run file while it runs" [ -f "$D/bat.run" ]
check "..naming its pid" [ "$(cut -f1 "$D/bat.run")" = "$RUN_PID" ]
check "list says running" bash -c "MUXTOPUS_SLUG=job '$MD' list | grep -q '^bat running, pid $RUN_PID'"
pass
check "a live run is not lost" [ -f "$D/bat.run" ] && [ ! -f "$D/bat.lost" ]
check "..and the lane hears nothing" [ "$(nlost job)" = 0 ]

echo "== the reaper stops it"
reap "$RUN_PID"; notice
check "the run is gone and left no marker" bash -c "! kill -0 $RUN_PID 2>/dev/null && [ ! -f '$D/bat.done' ] && [ -f '$D/bat.run' ]"
check "list already says LOST" bash -c "MUXTOPUS_SLUG=job '$MD' list | grep -q '^bat LOST'"
out="$("$W" --health 2>&1)"
check "--health lists it before any pass: e2e job lost: job bat" grep -q 'e2e job lost: job bat' <<<"$out"
pass
check "a pass renames it .lost" [ -f "$D/bat.lost" ] && [ ! -f "$D/bat.run" ]
check "..and logs it, with the reaper named from the transcript" grep -q 'run lost: job bat (low-memory reaper)' "$ST/log"
check "the lane is typed ONE line" [ "$(nlost job)" = 1 ]
check "..saying what to do" grep -q 'Your run bat was stopped before it finished (low-memory reaper). Requeue the same command now (lane rule); say so in STATUS.' <<<"$(heard job)"
check "..and the command to requeue" grep -q 'mux-done run bat -- bash -c' <<<"$(heard job)"
check "the parent hears nothing of a first loss" [ "$(nreport)" = 0 ]
out="$("$W" --health 2>&1)"
check "--health: kind lost, the lane's" grep -qE "^lost +job +orch .*the lane's .*e2e job lost: job bat \(low-memory reaper\), lost 1 time\(s\), the lane told 1x" <<<"$out"
pass
check "the window's tags say lost" grep -qP '\tjob\t.*\t[^\t]*lost[^\t]*$' "$ST/status.tsv"
check "a second pass types nothing more" [ "$(nlost job)" = 1 ]

echo "== 30 minutes on, not requeued: one more line, then no more"
age_nudge bat 31; pass
check "the second line" [ "$(nlost job)" = 2 ]
check "..says it is the second" grep -q 'Second notice: Your run bat' <<<"$(heard job | tail -1)"
age_nudge bat 31; pass
check "no third line" [ "$(nlost job)" = 2 ]
check "..and now the parent hears it: not requeued" grep -q 'lost-again job (claude:[0-9]*): e2e job lost: job bat .*and it has not requeued it' <<<"$(heard orch)"

echo "== requeued, then lost again: the parent hears at once"
n="$(nreport)"
start_run bat
check "starting the label again clears the .lost" [ ! -f "$D/bat.lost" ] && [ -f "$D/bat.run" ]
check "..and carries the count" [ "$(cut -f4 "$D/bat.run")" = 1 ]
check "..and the tag goes" bash -c "'$W' --once >/dev/null 2>&1; ! grep -qP '\tjob\t.*lost[^\t]*$' '$ST/status.tsv'"
sleep 1; reap "$RUN_PID"; notice; pass
check "the lane is told again" [ "$(nlost job)" = 3 ]
check "the parent hears it at once: lost twice" bash -c "[ \$(grep -c 'MUXTOPUS watchdog' '$HOME/heard-orch') -gt $n ] && grep -q 'e2e job lost: job bat (low-memory reaper), lost 2 time(s), the lane told 1x' <<<\"\$(tail -1 '$HOME/heard-orch')\""
MUXTOPUS_SLUG=job "$MD" ack bat
check "ack clears it" [ ! -f "$D/bat.lost" ]

echo "== not lost: finished, or a recycled pid"
MUXTOPUS_SLUG=job "$MD" run fin -- bash -c 'echo BATTERY-DONE' >/dev/null
check "a finished run leaves no .run" [ ! -f "$D/fin.run" ] && [ -f "$D/fin.done" ]
# A .run left behind by a run killed after its marker was written.
printf '%s\t1\t%s\t0\t%s\tbash -c x\n' 999999 "$(( $(date +%s) - 60 ))" "$WK" > "$D/fin.run"
pass
check "..a .run beside a newer marker is finished, not lost" [ ! -f "$D/fin.run" ] && [ ! -f "$D/fin.lost" ]
# A live pid that is somebody else now: its start time differs. Started
# after the last notice, so that notice is about some other shell.
sleep 1
printf '%s\t1\t%s\t0\t%s\tbash -c e2e\n' "$$" "$(date +%s)" "$WK" > "$D/rec.run"
pass
check "a recycled pid is lost (the start time differs)" [ -f "$D/rec.lost" ]
check "..without the reaper's notice, nothing is blamed on it" grep -q 'run lost: job rec (no result, process gone)' "$ST/log"
check "..and the line says so" grep -q 'Your run rec was stopped before it finished (its process is gone and it wrote no result' <<<"$(heard job)"

echo "== WATCHDOG_LOST_RUN_NUDGE=off"
MUXTOPUS_SLUG=job "$MD" ack
setkey WATCHDOG_LOST_RUN_NUDGE off
n="$(nlost job)"
start_run quiet; reap "$RUN_PID"; pass
check "off: still marked lost" [ -f "$D/quiet.lost" ]
check "..nothing typed" [ "$(nlost job)" = "$n" ]
check "..--health still lists it" bash -c "'$W' --health 2>&1 | grep -q 'e2e job lost: job quiet'"
setkey WATCHDOG_LOST_RUN_NUDGE on

echo "== mux-done run --detach: out of the shell's reach"
MUXTOPUS_SLUG=job "$MD" ack
out="$(MUXTOPUS_SLUG=job "$MD" run --detach det -- bash -c 'echo one; echo "BATTERY-DONE det"; exit 4' 2>"$SB/det.err")"; rc=$?
check "the output passes through" grep -q '^one$' <<<"$out"
check "..and the exit code" [ "$rc" = 4 ]
check "..it says it detached" grep -q 'det detached as pid' "$SB/det.err"
check "..the marker is written" grep -q '^det rc=4 .*BATTERY-DONE det' "$D/det.done"
# The waiter in a shell's process group, which the "reaper" then kills.
setsid bash -c 'printf %s "$$" > "$1"; shift; exec "$@"' _ "$SB/w.pid" env MUXTOPUS_SLUG=job "$MD" run --detach det2 -- bash -c 'sleep 3; echo DET2-DONE' >/dev/null 2>&1 &
for _ in $(seq 50); do [ -s "$SB/w.pid" ] && [ -f "$D/det2.run" ] && break; sleep 0.1; done
wp="$(cat "$SB/w.pid")"; rp="$(cut -f1 "$D/det2.run")"
check "the run is in a process group of its own, not the shell's" [ "$(ps -o pgid= -p "$rp" | tr -d ' ')" = "$rp" ] && [ "$rp" != "$wp" ]
reap "$wp"
check "..the shell's group killed, the run goes on" bash -c "! kill -0 $wp 2>/dev/null && kill -0 $rp"
pass
check "..and is not lost" [ ! -f "$D/det2.lost" ]
for _ in $(seq 60); do [ -f "$D/det2.done" ] && break; sleep 0.1; done
check "..and writes its marker when it ends" grep -q '^det2 rc=0 .*DET2-DONE' "$D/det2.done"
MUXTOPUS_SLUG=job "$MD" run --detach det3 -- sleep 60 >/dev/null 2>&1 & wp=$!
for _ in $(seq 50); do [ -f "$D/det3.run" ] && break; sleep 0.1; done
rp="$(cut -f1 "$D/det3.run")"
check "mux-done stop stops a detached run" bash -c "MUXTOPUS_SLUG=job '$MD' stop det3 >/dev/null && sleep 0.5 && ! kill -0 $rp 2>/dev/null"
wait "$wp"; rc=$?
check "..its waiter ends, not 0" [ "$rc" != 0 ]
pass
check "..and a stopped run is not lost" [ ! -f "$D/det3.lost" ] && [ ! -f "$D/det3.run" ]
MUXTOPUS_SLUG=job "$MD" run inshell -- sleep 60 >/dev/null 2>&1 & ip=$!
for _ in $(seq 50); do [ -f "$D/inshell.run" ] && break; sleep 0.1; done
MUXTOPUS_SLUG=job "$MD" stop inshell 2>"$SB/stop.err"; rc=$?
check "stop refuses a run in its shell's process group (exit 2)" [ "$rc" = 2 ] && grep -q 'not detached' "$SB/stop.err"
kill "$ip" 2>/dev/null; pkill -P "$ip" 2>/dev/null; wait "$ip" 2>/dev/null

echo "== the config key"
check "WATCHDOG_LOST_RUN_NUDGE is a config key" grep -q '^WATCHDOG_LOST_RUN_NUDGE=on' "$REPO/profile.sh"

sb_done
