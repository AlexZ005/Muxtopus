#!/usr/bin/env bash
# THE PRE-FLIGHT AND WAKE-ON-FINISH TOOLS: mux-lint (schedule front matter,
# profile.sh), the watchdog's leading-`---` fix, mux-done's marker and the
# watchdog's re-nudge when a run's notification was lost (WATCHDOG_DONE_NUDGE),
# mux-send's text-then-Enter-then-look, and e2e-slot --pc-first's option.
#
#   bash tests/test_pipeline_tools.sh
#
# WHY. MEASURED on this project's box: schedule entries written with a YAML
# `---` first line never launched and nothing said so; a `# note` on a KEY=
# line in profile.sh crash-looped the watchdog (2026-10-23); three lanes sat
# 20-30 minutes at an empty prompt after their background job's notification
# was lost (2026-10-22); and every orchestrator has typed text + Enter in one
# send-keys once and found it unsent.
#
# The sandbox and the faked windows are test_stall_reports.sh's.
#
# COUNTERFACTUAL: against origin/main's watchdog (PIPE_WATCHDOG=...) the
# idle lane hears nothing and the `---` entry keeps its first line.
SB_SOCKET="mxpipe$$"
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="${PIPE_WATCHDOG:-$REPO/claude-watchdog.sh}"
ST="$XDG_STATE_HOME/claude-watchdog"; HO="$HOME/.code/handovers"; SC="$HOME/.code/schedules"
WK="$SB/work"; mkdir -p "$ST" "$WK" "$SC" "$HOME/.claude/projects/p"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
export E2E_SLOT_LOCK="$SB/e2e.lock" E2E_SLOTS=1

cat > "$SB/lane.sh" <<EOF
#!/bin/bash
printf '{"pid":%s,"sessionId":"sid-%s","cwd":"%s","version":"0","status":"idle","kind":"interactive","tmux":"x:@0.%s"}\\n' \\
  \$\$ "\$1" "\$2" "\$TMUX_PANE" > "\$HOME/.claude/sessions/\$\$.json"
cd "\$2"
case "\$3" in
  # A box that keeps what is typed: the prompt line, then the tty's echo on it.
  stuck) printf '● ready\\n❯ '; exec sleep 900 ;;
  # A window mid-turn: its box holds the queued-messages hint, and the line it queues is drawn as one more "❯ <text>"
  # line -- here after the box, so a reader taking "the last ❯ line" sees the text and calls it unsent (the 5.12.0 bug).
  busy)  printf '● working\\n────\\n❯ Press up to edit queued messages\\n────\\n'; stty -echo; read -r l; printf '❯ %s\\n  ctrl+x ctrl+s to send now\\n' "\$l"; exec sleep 900 ;;
esac
printf '● ready\\\\n❯ \\\\n'
exec cat >> "\$HOME/heard-\$1"
EOF
chmod +x "$SB/lane.sh"
lane() { local d="$WK/$1"; mkdir -p "$d"; tmux new-window -d -t claude: -n "$1" "$SB/lane.sh $1 $d ${2:-listen}"; }
tree() {
  local wid pane
  wid="$(tmux display-message -p -t "claude:$1" '#{window_id}')"
  pane="$(tmux display-message -p -t "claude:$1" '#{pane_id}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "${2:-}" "$wid" "$pane" "$(date +%s)" "$1.md" >> "$ST/tree.tsv"
}
old_turn() {  # old_turn NAME MINUTES
  printf '{"type":"assistant","timestamp":"%s","message":{"model":"x","content":[{"type":"text","text":"waiting for the battery"}],"usage":{"input_tokens":1}}}\n' \
    "$(date -u -d "-$2 minutes" +%FT%T.000Z)" > "$HOME/.claude/projects/p/sid-$1.jsonl"
  touch -d "-$2 minutes" "$HOME/.claude/projects/p/sid-$1.jsonl"
}
pass() { "$W" --once >/dev/null 2>&1; }
heard() { cat "$HOME/heard-$1" 2>/dev/null; }
D="$ST/done"

tmux new-session -d -s claude -n home -x 220 -y 40 "sleep 900"
"$W" --on >/dev/null

echo "== mux-lint: the schedule front matter"
printf -- '---\ntype: work\nat: 2099-01-01 00:00\nstatus: held\ntitle: dashes\ncwd: %s\n---\nbody\n' "$WK" > "$SC/dashes.md"
out="$("$REPO/mux-lint" schedule "$SC/dashes.md")"; rc=$?
check "a leading --- is fixed and said" grep -q "FIXED, the line is dropped" <<<"$out"
check "..the entry now starts with type:" [ "$(head -1 "$SC/dashes.md")" = "type: work" ]
check "..and is otherwise clean (exit 0)" [ "$rc" = 0 ]
printf 'type: lane\nat: now\nstatus: held\ntitle: badtype\ncwd: %s\n---\nbody\n' "$WK" > "$SC/badtype.md"
out="$("$REPO/mux-lint" schedule "$SC/badtype.md")"; rc=$?
check "a type that can never run is said, with --check's reason" grep -q "type must be plan or work" <<<"$out"
check "..exit 1" [ "$rc" = 1 ]
rm -f "$SC/badtype.md"

echo "== mux-lint: profile.sh"
printf 'A=1\nB="has # inside quotes"\nC=2 # a note\n' > "$SB/p.sh"
out="$("$REPO/mux-lint" profile "$SB/p.sh")"; rc=$?
check "a comment on a KEY= line is found, with its line number" grep -q "p.sh:3: a comment on a KEY= line" <<<"$out"
check "..a # inside quotes is not one" bash -c "! grep -q ':2:' <<<\"$out\""
check "..exit 1" [ "$rc" = 1 ]
printf 'A=$(\n' > "$SB/q.sh"
check "a syntax error is found" bash -c "'$REPO/mux-lint' profile '$SB/q.sh' | grep -q 'syntax error'"
check "the repo's own profile.sh is clean" "$REPO/mux-lint" profile "$REPO/profile.sh"

echo "== the hook runs it on a write"
printf -- '---\ntype: work\nat: 2099-01-01 00:00\nstatus: held\ntitle: hooked\ncwd: %s\n---\nbody\n' "$WK" > "$SC/hooked.md"
out="$(printf '{"session_id":"00000000-0000-0000-0000-000000000000","tool_name":"Write","tool_input":{"file_path":"%s"}}' "$SC/hooked.md" | "$REPO/claude-winddown-hook.sh")"
check "a Write of a schedule entry gets the pre-flight line as context" grep -q '"additionalContext":"PRE-FLIGHT (mux-lint)' <<<"$out"
check "..and the file is fixed" [ "$(head -1 "$SC/hooked.md")" = "type: work" ]
out="$(printf '{"session_id":"00000000-0000-0000-0000-000000000000","tool_name":"Read","tool_input":{"file_path":"/etc/hosts"}}' | "$REPO/claude-winddown-hook.sh")"
check "..any other tool call: nothing" [ -z "$out" ]

echo "== the watchdog drops a leading --- from a file nobody linted"
printf -- '---\ntype: work\nat: 2099-01-01 00:00\nstatus: pending\ntitle: raw\ncwd: %s\n---\nbody\n' "$WK" > "$SC/raw.md"
check "--check warns about it first" bash -c "'$W' --check '$SC/raw.md' | grep -q \"starts with a '---' line\""
pass
check "after a pass the entry starts with type:" [ "$(head -1 "$SC/raw.md")" = "type: work" ]
check "..and the log says so" grep -q "raw.md: dropped a leading '---' line" "$ST/log"
rm -f "$SC"/*.md

echo "== mux-done: the marker"
out="$(MUXTOPUS_SLUG=job "$REPO/mux-done" run bat -- bash -c 'echo first; echo "BATTERY-DONE u1A: 3 suites, 1 red"; exit 3')"; rc=$?
check "the command's output passes through" grep -q '^first$' <<<"$out"
check "..and its exit code" [ "$rc" = 3 ]
check "the marker holds one line: label, rc and the last line" grep -Eq '^bat rc=3 [0-9]+m: BATTERY-DONE u1A: 3 suites, 1 red' "$D/job/bat.done"
check "list shows it" bash -c "MUXTOPUS_SLUG=job '$REPO/mux-done' list | grep -q '^bat rc=3'"
MUXTOPUS_SLUG=job "$REPO/mux-done" ack bat
check "ack removes it" [ ! -f "$D/job/bat.done" ]

echo "== the re-nudge: a finished run, a window idle since before it ended"
lane job; lane busy
for l in job busy; do printf '# %s\nnext: wait for the battery\n' "$l" > "$HO/STATUS-$l.md"; done
old_turn job 40; old_turn busy 2
sleep 2; tree job; tree busy
MUXTOPUS_SLUG=job "$REPO/mux-done" mark bat "rc=1 BATTERY-DONE u1A: 228 suites, 2 red"
MUXTOPUS_SLUG=busy "$REPO/mux-done" mark bat "rc=0 BATTERY-DONE u1B: 231 suites"
touch -d '-20 minutes' "$D/job/bat.done" "$D/busy/bat.done"
pass; sleep 2
check "the idle lane is typed the summary line" grep -q '\[muxtopus\] A background run of yours finished .*BATTERY-DONE u1A: 228 suites, 2 red' <<<"$(heard job)"
check "..once: the marker is put aside as .nudged" [ -f "$D/job/bat.done.nudged" ] && [ ! -f "$D/job/bat.done" ]
check "a lane that had a turn after the run ended hears nothing" bash -c "! grep -q 'muxtopus' <<<\"\$(cat '$HOME/heard-busy' 2>/dev/null)\""
check "..its marker is put aside as .seen" [ -f "$D/busy/bat.done.seen" ]
n="$(heard job | grep -c '\[muxtopus\]')"
pass; sleep 1
check "a second pass types nothing more" [ "$(heard job | grep -c '\[muxtopus\]')" = "$n" ]
setkey WATCHDOG_DONE_NUDGE off
MUXTOPUS_SLUG=job "$REPO/mux-done" mark bat2 "rc=0 later"; touch -d '-20 minutes' "$D/job/bat2.done"
pass; sleep 1
check "WATCHDOG_DONE_NUDGE=off: nothing typed, the marker stays" bash -c "[ \$(grep -c 'muxtopus' '$HOME/heard-job') = $n ] && [ -f '$D/job/bat2.done' ]"
setkey WATCHDOG_DONE_NUDGE 5

echo "== mux-send: text, Enter, then a look"
lane talk; sleep 1
check "a line reaches the window" bash -c "MUX_SEND_DELAY=0.3 '$REPO/mux-send' claude:talk 'hello from the orchestrator' && sleep 1 && grep -qx 'hello from the orchestrator' '$HOME/heard-talk'"
lane stuck stuck; sleep 1
MUX_SEND_DELAY=0.3 "$REPO/mux-send" claude:stuck "this stays in the box" 2>"$SB/send.err"; rc=$?
check "a box that keeps the text: exit 1 after the retries" [ "$rc" = 1 ]
check "..saying so" grep -q "still in claude:stuck's input box" "$SB/send.err"
lane busy2 busy; sleep 1
MUX_SEND_DELAY=0.3 "$REPO/mux-send" claude:busy2 "for the busy one" 2>"$SB/send.err"; rc=$?
check "a busy window that queued the line: exit 0" [ "$rc" = 0 ]
check "..saying it was queued" grep -q "queued (the window is busy" "$SB/send.err"
check "no such pane: exit 2" bash -c "'$REPO/mux-send' claude:nowhere x 2>/dev/null; [ \$? = 2 ]"

echo "== e2e-slot --pc-first"
check "the option is in the usage" bash -c "'$REPO/e2e-slot' --help | grep -q -- '--pc-first SECS'"
check "..and with no pc slots configured the run takes a local one at once" \
  bash -c "E2E_PC= timeout 20 '$REPO/e2e-slot' --pc-first 600 --wait 10 -- true"
check "..it refuses a value that is not seconds" bash -c "'$REPO/e2e-slot' --pc-first soon -- true 2>/dev/null; [ \$? = 2 ]"

echo "== the config key"
check "WATCHDOG_DONE_NUDGE is a config key" grep -q '^WATCHDOG_DONE_NUDGE=' "$REPO/profile.sh"

sb_done
