#!/usr/bin/env bash
# Phase 2: the watchdog's `waiting` state, and four events told once.
# A sandbox tmux server (-L mxnotify), a fake claude showing scripted screens,
# the sandbox watchdog run pass by pass (--once) and then as a --daemon killed
# by pid, and every message landing in tests/fake_telegram.py.
#   bash tests/test_notify_watchdog.sh
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"
FIX="$REPO/tests/fixtures/prompts"
HO="$HOME/.code/handovers"; SC="$HOME/.code/schedules"
ST="$XDG_STATE_HOME/claude-watchdog"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"
chmod 600 "$CLAUDE_NOTIFY_CONF"

setkey() {  # setkey KEY VALUE -- the hand-written sandbox config
  sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"
}
pass() { "$W" --once >/dev/null 2>&1; }
msgs() { sb_ncalls sendMessage; }
texts() { sb_calls sendMessage | jq -r .text; }
state_of() { awk -F'\t' -v n="$1" '$2==n{print $6}' "$ST/status.tsv"; }
screen() { if [ -n "${1:-}" ]; then cp "$1" "$HOME/fake-screen"; else printf '● done.\n\n────\n❯ \n────\n' > "$HOME/fake-screen"; fi; sleep 0.8; }

screen
tmux new-session -d -s claude -n '➥lane-a' -x 100 -y 40 "cd $HOME && claude"
for i in $(seq 50); do ls "$HOME/.claude/sessions/"*.json >/dev/null 2>&1 && break; sleep 0.1; done
check "the fake claude published a session" ls "$HOME/.claude/sessions/"*.json
"$W" --on >/dev/null

echo "== an idle pane, and the baseline pass"
pass
check "status.tsv lists the pane as idle" [ "$(state_of '➥lane-a')" = idle ]
check "the baseline was taken" [ -f "$ST/notify/baseline" ]
check "no message for an idle pane" [ "$(msgs)" = 0 ]

echo "== today's prompt: waiting on pass 2, one message, none on passes 3-5"
screen "$FIX/rm-dangerous.txt"
pass
check "pass 1: still idle (not a flash)" [ "$(state_of '➥lane-a')" = idle ]
check "pass 1: nothing sent" [ "$(msgs)" = 0 ]
pass
check "pass 2: status.tsv says waiting" [ "$(state_of '➥lane-a')" = waiting ]
check "pass 2: ONE message" [ "$(msgs)" = 1 ]
check "the title names the account and the window" grep -q "^personal · needs you: ➥lane-a" <<<"$(texts)"
check "the message quotes the prompt box" grep -q "Dangerous rm operation" <<<"$(texts)"
check "the log says waiting once" [ "$(grep -c 'waiting: ➥lane-a' "$ST/log")" = 1 ]
pass; pass; pass
check "passes 3-5: still ONE message" [ "$(msgs)" = 1 ]
check "passes 3-5: still waiting" [ "$(state_of '➥lane-a')" = waiting ]

echo "== the prompt clears and returns: a new message"
screen
pass
check "cleared: idle again" [ "$(state_of '➥lane-a')" = idle ]
check "cleared: the key was dropped" bash -c '! grep -q "^waiting:" "$1"' _ "$ST/notify/sent.tsv"
screen "$FIX/rm-dangerous.txt"; pass; pass
check "returned: a second message" [ "$(msgs)" = 2 ]

echo "== WAITING off -> nothing sent, the state still published"
screen; pass
setkey MUXTOPUS_NOTIFY_WAITING off
screen "$FIX/edit-file.txt"; pass; pass
check "switch off: no message" [ "$(msgs)" = 2 ]
check "switch off: still waiting in status.tsv" [ "$(state_of '➥lane-a')" = waiting ]
setkey MUXTOPUS_NOTIFY_WAITING on
setkey MUXTOPUS_NOTIFY_PANE_TEXT off
pass
check "switch back on: the ongoing prompt is told" [ "$(msgs)" = 3 ]
check "PANE_TEXT off: the box is not quoted" bash -c '! grep -q "12 +NEW" <<<"$1"' _ "$(texts | tail -12)"
check "PANE_TEXT off: the question still is" grep -q "Do you want to make this edit" <<<"$(texts | tail -12)"
setkey MUXTOPUS_NOTIFY_PANE_TEXT on
screen; pass

echo "== trouble: stalled, TROUBLE off first"
setkey MUXTOPUS_NOTIFY_TROUBLE off
printf 'type: bogus\nat: now\ncwd: %s\nstatus: pending\n---\nbody\n' "$HOME" > "$SC/bad.md"
pass
check "TROUBLE off: stalled is not told" [ "$(msgs)" = 3 ]
setkey MUXTOPUS_NOTIFY_TROUBLE on
pass
check "TROUBLE on: one stalled message" grep -q "stalled: bad.md" <<<"$(texts)"
n="$(msgs)"; pass
check "stalled is told once" [ "$(msgs)" = "$n" ]
rm -f "$SC/bad.md"

echo "== trouble: an entry marked error"
printf 'type: work\nat: now\ncwd: %s\nstatus: error\n---\nbody\n' "$HOME" > "$SC/broke.md"
n="$(msgs)"; pass
check "error is told" grep -q "launch failed: broke.md" <<<"$(texts)"
pass
check "error is told once" [ "$(msgs)" = $(( n + 1 )) ]
rm -f "$SC/broke.md"

echo "== trouble: blocked past the threshold (faked clock file)"
printf '# STATUS: lane-x\nstill going\n' > "$HO/STATUS-lane-x.md"
printf 'type: work\nat: now\nafter: lane-x\ncwd: %s\nstatus: pending\n---\ncarry on\n' "$HOME" > "$SC/held.md"
n="$(msgs)"; pass
check "blocked.tsv tracks since" grep -q "^held.md	" "$ST/notify/blocked.tsv"
check "plain blocked is not told" [ "$(msgs)" = "$n" ]
setkey MUXTOPUS_NOTIFY_BLOCKED_AFTER 0
sed -i "s/^held.md\t.*/held.md\t$(( $(date +%s) - 3*3600 ))/" "$ST/notify/blocked.tsv"
pass
check "BLOCKED_AFTER=0: never" [ "$(msgs)" = "$n" ]
setkey MUXTOPUS_NOTIFY_BLOCKED_AFTER 120
pass
check "3h > 120m: told" grep -q "blocked 3h: held.md" <<<"$(texts)"
check "with the executor's why" grep -q "waiting for lane-x" <<<"$(texts)"
pass
check "blocked told once" [ "$(msgs)" = $(( n + 1 )) ]

echo "== done names the released entry (DONE off first)"
setkey MUXTOPUS_NOTIFY_DONE off
printf '# STATUS: lane-old\nold news\n' > "$HO/done/STATUS-lane-old.md"
n="$(msgs)"; pass
check "DONE off: nothing" [ "$(msgs)" = "$n" ]
setkey MUXTOPUS_NOTIFY_DONE on
pass
check "DONE on later: no flood of what finished meanwhile" [ "$(msgs)" = "$n" ]
printf '# STATUS: lane-x\n\nAll three phases committed; tests green.\n' > "$HO/STATUS-lane-x.md"
mv "$HO/STATUS-lane-x.md" "$HO/done/STATUS-lane-x.md"
pass
check "done is told" grep -q "done: lane-x" <<<"$(texts)"
check "with its gist" grep -q "All three phases committed" <<<"$(texts)"
check "naming the entry it released" grep -q "held.md" <<<"$(sb_calls sendMessage | jq -r .text | grep -A6 'done: lane-x')"
n="$(msgs)"; pass
check "done told once" [ "$(msgs)" = "$n" ]
tmux kill-window -t "claude:➥held" 2>/dev/null

echo "== questions (QUESTIONS off first)"
setkey MUXTOPUS_NOTIFY_QUESTIONS off
printf '# Questions: lane-q\n\n## 1. Which clock\n(a) host (b) mesh\n' > "$HO/QUESTIONS-lane-q.md"
n="$(msgs)"; pass
check "QUESTIONS off: nothing" [ "$(msgs)" = "$n" ]
setkey MUXTOPUS_NOTIFY_QUESTIONS on
printf '\n## 2. Which port\n(a) 80 (b) 8080\n\n## 3. Which log\n(a) file (b) journal\n' >> "$HO/QUESTIONS-lane-q.md"
pass
check "two NEW forks: a header and two fork messages" [ "$(msgs)" = $(( n + 3 )) ]
check "the header names the file" grep -q "questions: lane-q" <<<"$(texts)"
check "a fork message carries the fork" grep -q "Which port" <<<"$(texts)"
check "the fork already known is not re-sent" [ "$(texts | grep -c 'Which clock')" = 0 ]
n="$(msgs)"
printf '**Answer (user, 2026-09-17):** (a)\n' >> "$HO/QUESTIONS-lane-q.md"
pass
check "a fork answered: nothing sent" [ "$(msgs)" = "$n" ]
printf '**ANSWERED 2026-09-17**\n' >> "$HO/QUESTIONS-lane-q.md"
pass
check "file ANSWERED: its key is dropped" bash -c '! grep -q "^questions:" "$1"' _ "$ST/notify/sent.tsv"
check "and nothing sent" [ "$(msgs)" = "$n" ]
mkdir -p "$HOME/.code/theprototype-app/core/plans"
printf '# Q\n\n1. Legacy fork\n' > "$HOME/.code/theprototype-app/core/plans/QUESTIONS-legacy.md"
pass
check "the legacy folder is read too" grep -q "questions: legacy" <<<"$(texts)"

echo "== trouble: stranded"
sid="$(jq -r .sessionId "$HOME/.claude/sessions/"*.json | head -1)"
mkdir -p "$HOME/.claude/projects/sb"
printf '{"type":"assistant","timestamp":"%s"}\n' "$(date -u -d '-3 hours' +%Y-%m-%dT%H:%M:%SZ)" > "$HOME/.claude/projects/sb/$sid.jsonl"
printf '# STATUS: lane-a\nhalf way\n' > "$HO/STATUS-lane-a.md"
n="$(msgs)"; pass
check "status.tsv says stranded" [ "$(state_of '➥lane-a')" = stranded ]
check "stranded is told" grep -q "stranded: ➥lane-a" <<<"$(texts)"
check "a prompt beats stranded" bash -c 'cp "$1" "$HOME/fake-screen"; sleep 0.8; "$2" --once; "$2" --once; awk -F"\t" "\$2==\"➥lane-a\"{print \$6}" "$3" | grep -qx waiting' \
  _ "$FIX/trust-folder.txt" "$W" "$ST/status.tsv"
screen; rm -f "$HO/STATUS-lane-a.md" "$HOME/.claude/projects/sb/$sid.jsonl"; pass

echo "== restart re-sends nothing; unconfigured still publishes waiting"
n="$(msgs)"; pass; pass
check "no message on a quiet restart" [ "$(msgs)" = "$n" ]
mv "$CLAUDE_NOTIFY_CONF" "$CLAUDE_NOTIFY_CONF.off"
screen "$FIX/rm-dangerous-boxed.txt"; pass; pass
check "unconfigured: waiting still published" [ "$(state_of '➥lane-a')" = waiting ]
check "unconfigured: nothing reaches the API" [ "$(msgs)" = "$n" ]
mv "$CLAUDE_NOTIFY_CONF.off" "$CLAUDE_NOTIFY_CONF"
screen; pass

echo "== the sandbox DAEMON, killed by pid"
setkey WATCHDOG_INTERVAL 1
: > "$FAKE/calls.jsonl"
"$W" --daemon >/dev/null 2>&1 & dpid=$!
SB_PIDS+=("$dpid")
sleep 2
screen "$FIX/trust-folder.txt"
for i in $(seq 40); do [ "$(state_of '➥lane-a')" = waiting ] && break; sleep 0.25; done
check "daemon: waiting published" [ "$(state_of '➥lane-a')" = waiting ]
sleep 3
check "daemon: exactly one message over several passes" [ "$(msgs)" = 1 ]
kill "$dpid"; wait "$dpid" 2>/dev/null
check "daemon stopped by pid" bash -c '! kill -0 "$1" 2>/dev/null' _ "$dpid"

echo "== the key-list mirror"
check "tests/test_settings.py green" bash -c 'python3 "$1/tests/test_settings.py" >/dev/null' _ "$REPO"
check "--prompt: every positive fixture is a prompt" bash -c 'for f in rm-dangerous rm-dangerous-boxed edit-file trust-folder plan-approval; do "$1" --prompt "$2/$f.txt" >/dev/null || exit 1; done' _ "$W" "$FIX"
check "--prompt: quoted text and an idle pane are not" bash -c '! "$1" --prompt "$2/quoted-then-idle.txt" >/dev/null && ! "$1" --prompt "$2/idle.txt" >/dev/null' _ "$W" "$FIX"
check "--prompt: a policy-changing option 1 is not a yes" bash -c '"$1" --prompt "$2/plan-approval.txt" | grep -qx "yes	0"' _ "$W" "$FIX"
check "--prompt: a plain yes is" bash -c '"$1" --prompt "$2/rm-dangerous-boxed.txt" | grep -qx "yes	1"' _ "$W" "$FIX"
check "the sha ignores where the cursor is" bash -c 'a=$("$1" --prompt "$2/rm-dangerous.txt" | head -1); sed "s/❯ 1\. Yes/  1. Yes/; s/  2\. Yes, and/❯ 2. Yes, and/" "$2/rm-dangerous.txt" > "$3/moved.txt"; b=$("$1" --prompt "$3/moved.txt" | head -1); [ "$a" = "$b" ]' _ "$W" "$FIX" "$SB"

sb_done
