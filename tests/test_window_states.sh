#!/usr/bin/env bash
# ONE STATE, ANY NUMBER OF TAGS: what claude-watchdog.sh now says a window
# is doing, beyond working / idle / stranded. window_tags, tag_servers,
# tag_alerts and the idle refinements in pass().
#
#   bash tests/test_window_states.sh
#
# WHY. MEASURED on 2026-10-07: lane 38-int-a read `idle` while its tests ran
# in the background (and would have gone `stranded` after two hours), lane
# 37-int-126 read `idle` while it watched CI, and two lanes the day before sat
# waiting for an e2e slot while the dashboard said `working`. A finished lane
# and a lane stopped at a checkpoint both read `idle`; so did one that died on
# an API error.
#
# THE WINDOWS ARE FAKED, THE DAEMON IS NOT. Each "claude" here is a bash in
# a pane of a private tmux server that publishes its own session file and
# starts, under a shell whose argv looks like Claude Code's tool shell, the
# process a real lane would: a test runner, `gh run watch`, an e2e-slot run
# on private lock files, a poller, a script. The real `--once` pass reads
# them. tests/notify_sandbox.sh is the sandbox: its own HOME and XDG dirs, a
# fake Telegram, nothing that can reach a real pane, slot or phone.
#
# COUNTERFACTUAL: against origin/main's watchdog (STATES_WATCHDOG=...) every
# one of these windows reads `idle` and status.tsv has no TAGS column.
SB_SOCKET="mxstates$$"
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="${STATES_WATCHDOG:-$REPO/claude-watchdog.sh}"
ST="$XDG_STATE_HOME/claude-watchdog"; HO="$HOME/.code/handovers"; SC="$HOME/.code/schedules"
WK="$SB/work"; mkdir -p "$ST" "$WK" "$HOME/.claude/projects/p"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"
chmod 600 "$CLAUDE_NOTIFY_CONF"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
export E2E_SLOT_LOCK="$SB/e2e.lock" E2E_SLOTS=1

# The fake claude: publishes sessions/<pid>.json for its own pane, starts
# what $3 says under a tool-shell-looking bash, and shows a prompt.
SNAP='source /nowhere/.claude/shell-snapshots/snapshot-bash-1.sh 2>/dev/null'
cat > "$SB/lane.sh" <<EOF
#!/bin/bash
printf '{"pid":%s,"sessionId":"sid-%s","cwd":"%s","version":"0","status":"idle","kind":"interactive","tmux":"x:@0.%s"}\\n' \\
  \$\$ "\$1" "\$2" "\$TMUX_PANE" > "\$HOME/.claude/sessions/\$\$.json"
cd "\$2"
case "\$3" in
  test)  bash -c "$SNAP; (exec -a 'npx vitest run' sleep 600); :" & ;;
  ci)    bash -c "$SNAP; (exec -a 'gh run watch' sleep 600); :" & ;;
  poll)  bash -c "$SNAP; sleep 600; :" & ;;
  job)   bash -c "$SNAP; bash $SB/run-snap.sh; :" & ;;
  e2e)   bash -c "$SNAP; $REPO/e2e-slot -- sleep 600; :" & ;;
esac
printf '● ready\\n❯ \\n'
exec sleep 900
EOF
chmod +x "$SB/lane.sh"
printf '#!/bin/bash\nsleep 600\n' > "$SB/run-snap.sh"
lane() {  # lane NAME MODE [CWD]
  local d="${3:-$WK/$1}"; mkdir -p "$d"
  tmux new-window -d -t claude: -n "$1" "$SB/lane.sh $1 $d ${2:-none}"
}
pass() { "$W" --once >/dev/null 2>&1; }
col() { awk -F'\t' -v n="$1" -v c="$2" '$2==n{print $c}' "$ST/status.tsv"; }
state() { col "$1" 6; }
tags() { col "$1" 21; }
has_tag() { [[ ",$(tags "$1")," == *",$2,"* ]]; }
told() { sb_calls sendMessage | jq -r .text | grep -c "$1"; }

tmux new-session -d -s claude -n home -x 200 -y 40 "sleep 900"
"$W" --on >/dev/null

lane bgtest test; lane bgci ci; lane bgpoll poll; lane bgjob job
lane e2erun e2e; sleep 1; lane e2ewait e2e
lane plain; lane handed; lane finished; lane orch; lane asks; lane crashed; lane pausedw
lane serverlane none "$WK/theprototype-lane-serverlane"
printf '# handed\nnext: phase 2\n' > "$HO/STATUS-handed.md"
printf '# done\n' > "$HO/done/STATUS-finished.md"
printf '# orch\n' > "$HO/STATUS-orch.md"
printf 'type: work\nat: 2099-01-01 00:00\nslug: orch-l1\nwindow: orch\ncwd: %s\nstatus: pending\n---\nx\n' "$HOME" > "$SC/orch-l1.md"
printf '# asks\n' > "$HO/STATUS-asks.md"
printf '1. Which colour?\n' > "$HO/QUESTIONS-asks.md"
printf '{"type":"assistant","timestamp":"%s","message":{"model":"claude-opus-5-5","content":[{"type":"text","text":"API Error: Server error mid-response. The response above may be incomplete."}],"usage":{"input_tokens":1,"output_tokens":1}}}\n' \
  "$(date -u +%FT%T.000Z)" > "$HOME/.claude/projects/p/sid-crashed.jsonl"
printf 'sid-pausedw\t2\t%s\t%s\n' $(( $(date +%s) + 3600 )) "$(date +%s)" >> "$ST/wound"
# A dev server a lane's e2e run started, detached, from a folder named after
# the lane -- not under the lane's own working folder. And a window sitting
# in the shared parent folder, which must NOT be given it.
mkdir -p "$WK/run-serverlane"
( cd "$WK/run-serverlane" && exec -a "node $WK/run-serverlane/node_modules/.bin/vite dev --port 5390 --strictPort" sleep 600 ) &
SB_PIDS+=($!)
lane parentdir none "$WK"
sleep 3
pass

echo "== what idle was hiding"
check "a tool shell running a test: background" [ "$(state bgtest)" = background ]
check "..tagged test" has_tag bgtest test
check "watching CI: background, ci" bash -c "[ '$(state bgci)' = background ] && [[ ',$(tags bgci),' == *,ci,* ]]"
check "a poller: background, sleep" has_tag bgpoll sleep
check "a script the turn left running: job:run-snap.sh" has_tag bgjob job:run-snap.sh
check "..but not the processes inside it" bash -c "! [[ '$(tags bgjob)' == *job:sleep* ]]"
check "holding an e2e slot: e2e" has_tag e2erun e2e
check "waiting for one: e2e-wait" has_tag e2ewait e2e-wait
check "..and not also e2e" bash -c "! [[ ',$(tags e2ewait),' == *,e2e,* ]]"
check "the shell's own argv (it names e2e-slot) is never matched: no job tag" bash -c "! [[ '$(tags e2erun)' == *job:* ]]"

echo "== the idle that is a fact about the lane"
check "an open handover: handed off" [ "$(state handed)" = handed-off ]
check "a handover in done/: done" [ "$(state finished)" = done ]
check "an open handover and a lane pending under it: orchestrating" [ "$(state orch)" = orchestrating ]
check "an unanswered QUESTIONS file: tagged asking" has_tag asks asking
check "a turn that ended on an API error: error" [ "$(state crashed)" = error ]
check "wound down hard, its budget window still ahead: paused" [ "$(state pausedw)" = paused ]
check "..tagged with the budget that paused it" has_tag pausedw session
check "nothing at all: still plain idle, no tags" bash -c "[ '$(state plain)' = idle ] && [ '$(tags plain)' = - ]"

echo "== dev servers"
check "a server from run-serverlane belongs to serverlane: serve:5390" has_tag serverlane serve:5390
check "..not to the window in the shared parent folder" bash -c "! [[ '$(tags parentdir)' == *serve* ]]"

echo "== a background lane is never stranded"
setkey WATCHDOG_STRANDED 1
printf '# bgtest\n' > "$HO/STATUS-bgtest.md"
# two hours idle: the transcript's last turn is old
printf '{"type":"assistant","timestamp":"%s","message":{"model":"x","content":[{"type":"text","text":"running the suite"}],"usage":{"input_tokens":1}}}\n' \
  "$(date -u -d '-3 hours' +%FT%T.000Z)" > "$HOME/.claude/projects/p/sid-bgtest.jsonl"
printf '{"type":"assistant","timestamp":"%s","message":{"model":"x","content":[{"type":"text","text":"stopping"}],"usage":{"input_tokens":1}}}\n' \
  "$(date -u -d '-3 hours' +%FT%T.000Z)" > "$HOME/.claude/projects/p/sid-handed.jsonl"
pass
check "idle 3h, open handover, tests still running: background, not stranded" [ "$(state bgtest)" = background ]
check "..while the same with nothing running is stranded" [ "$(state handed)" = stranded ]

echo "== the tag alerts (MUXTOPUS_NOTIFY_TAGS)"
printf '# serverlane\n' > "$HO/done/STATUS-serverlane.md"
pass; pass
check "off by default: no message about the server" [ "$(told 'server left running')" = 0 ]
setkey MUXTOPUS_NOTIFY_TAGS on; pass
check "on: a done lane with its server up is told" grep -q "server left running: serverlane" <<<"$(sb_calls sendMessage | jq -r .text)"
check "..naming the port" grep -q "serve:5390" <<<"$(sb_calls sendMessage | jq -r .text)"
n="$(told 'server left running')"
pass
check "..once" [ "$(told 'server left running')" = "$n" ]

echo "== --status names the column"
check "TAGS is in the header" grep -q $'\tSAID\tTAGS$' <<<"$("$W" --status | sed -n 2p)"

sb_done
