#!/usr/bin/env bash
# REPORTS TO THE PARENT: what claude-watchdog.sh tells the window that
# spawned a lane, when the lane has stalled, finished, is asking, is stuck at
# a limit or holds an e2e slot too long -- and the phone, when no parent can
# hear it. report_pass, report_health, WATCHDOG_NUDGE_STALLED,
# WATCHDOG_CLOSE_FINISHED.
#
#   bash tests/test_stall_reports.sh
#
# WHY. MEASURED on 2026-10-22: three lanes sat 20-30 minutes at an empty
# prompt after "Compacted while idle" swallowed their background job's
# notification, two finished lanes held their windows, and the orchestrator
# that had spawned them all heard nothing until the owner asked it to look.
#
# THE WINDOWS ARE FAKED, THE DAEMON IS NOT. As in test_window_states.sh, each
# "claude" is a bash in a pane of a private tmux server that publishes its own
# session file. A "listening" one runs `cat` on its tty, so what the watchdog
# types into it lands in a file the test reads. tests/notify_sandbox.sh is the
# sandbox: its own HOME and XDG dirs, a fake Telegram, private e2e locks.
#
# COUNTERFACTUAL: against origin/main's watchdog (REPORTS_WATCHDOG=...) no
# window hears anything, and --health is an unknown option.
SB_SOCKET="mxreports$$"
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="${REPORTS_WATCHDOG:-$REPO/claude-watchdog.sh}"
ST="$XDG_STATE_HOME/claude-watchdog"; HO="$HOME/.code/handovers"; SC="$HOME/.code/schedules"
WK="$SB/work"; mkdir -p "$ST" "$WK" "$HOME/.claude/projects/p"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"
chmod 600 "$CLAUDE_NOTIFY_CONF"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
export E2E_SLOT_LOCK="$SB/e2e.lock" E2E_SLOTS=1

SNAP='source /nowhere/.claude/shell-snapshots/snapshot-bash-1.sh 2>/dev/null'
cat > "$SB/lane.sh" <<EOF
#!/bin/bash
printf '{"pid":%s,"sessionId":"sid-%s","cwd":"%s","version":"0","status":"idle","kind":"interactive","tmux":"x:@0.%s"}\\n' \\
  \$\$ "\$1" "\$2" "\$TMUX_PANE" > "\$HOME/.claude/sessions/\$\$.json"
cd "\$2"
case "\$3" in
  e2e)   bash -c "$SNAP; $REPO/e2e-slot -- sleep 600; :" & ;;
  limit) printf "You've hit your session limit · resets %s\\\\n" "\$(date -d '-5 minutes' '+%-I:%M%P')" ;;
esac
printf '● ready\\\\n❯ \\\\n'
# A listening window: whatever is typed into it, a line at a time.
[ "\$3" = listen ] && exec cat >> "\$HOME/heard-\$1"
exec sleep 900
EOF
chmod +x "$SB/lane.sh"
lane() {  # lane NAME MODE
  local d="$WK/$1"; mkdir -p "$d"
  tmux new-window -d -t claude: -n "$1" "$SB/lane.sh $1 $d ${2:-none}"
}
# A tree row, as a launch would have written it: slug, parent, window, pane.
tree() {
  local wid pane
  wid="$(tmux display-message -p -t "claude:$1" '#{window_id}')"
  pane="$(tmux display-message -p -t "claude:$1" '#{pane_id}')"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "${2:-}" "$wid" "$pane" "$(date +%s)" "$1.md" >> "$ST/tree.tsv"
}
old_turn() {  # old_turn NAME MINUTES
  printf '{"type":"assistant","timestamp":"%s","message":{"model":"x","content":[{"type":"text","text":"waiting for the e2e job"}],"usage":{"input_tokens":1}}}\n' \
    "$(date -u -d "-$2 minutes" +%FT%T.000Z)" > "$HOME/.claude/projects/p/sid-$1.jsonl"
}
pass() { "$W" --once >/dev/null 2>&1; }
state() { awk -F'\t' -v n="$1" '$2==n{print $6}' "$ST/status.tsv"; }
heard() { cat "$HOME/heard-$1" 2>/dev/null; }
nheard() { heard "$1" | grep -c 'MUXTOPUS watchdog'; }
phone() { sb_calls sendMessage | jq -r .text; }
nphone() { phone | grep -c "$1"; }
# Every reported problem looks a REPEAT_MIN old: the next pass may say it again.
age_ledger() { awk -F'\t' -v OFS='\t' -v t=$(( $(date +%s) - ${1:-7200} )) '{$2 = t; if ($3 != "") $3 = t; print}' \
  "$ST/reports" > "$ST/reports.tmp" && mv "$ST/reports.tmp" "$ST/reports"; }
has_window() { tmux list-windows -t claude -F '#{window_name}' | grep -qx "$1"; }

tmux new-session -d -s claude -n home -x 220 -y 40 "sleep 900"
"$W" --on >/dev/null

# orch spawned stl (stalled), fin (finished) and nud; lone and lonefin have
# no parent at all.
lane orch listen; lane stl; lane fin; lane lone; lane lonefin
for l in orch stl lone; do printf '# %s\nnext: wait for e2e\n' "$l" > "$HO/STATUS-$l.md"; done
for l in fin lonefin; do printf '# %s\n' "$l" > "$HO/done/STATUS-$l.md"; done
old_turn stl 30; old_turn lone 30; old_turn fin 30
sleep 2
tree orch; tree stl orch; tree fin orch; tree lone; tree lonefin
pass

echo "== the parent hears its lanes, in ONE line"
check "stl is stalled" [ "$(state stl)" = stalled ]
check "orch heard one machine report" [ "$(nheard orch)" = 1 ]
check "..naming stl as stalled, and where it is" grep -qE 'stalled stl \(claude:[0-9]+\): idle 30m at its prompt' <<<"$(heard orch)"
check "..and fin as finished" grep -q 'finished fin (claude:' <<<"$(heard orch)"
check "..and says it is a machine report, not the owner" grep -q 'a machine report for orch, not the owner' <<<"$(heard orch)"
check "..and nothing about the lanes that are not its own" bash -c "! grep -q 'lone' <<<\"\$(cat '$HOME/heard-orch')\""

echo "== no parent: the phone, for what the phone has not heard"
check "the phone hears that lone stalled" [ "$(nphone 'stalled lone')" = 1 ]
check "..but not that lonefin finished (MUXTOPUS_NOTIFY_DONE said so)" [ "$(nphone 'finished lonefin')" = 0 ]

echo "== said once, then again only after WATCHDOG_REPORT_REPEAT_MIN"
pass
check "a second pass: nothing new for orch" [ "$(nheard orch)" = 1 ]
check "..or for the phone" [ "$(nphone 'stalled lone')" = 1 ]
age_ledger
pass
check "an hour on: orch hears it again" [ "$(nheard orch)" = 2 ]
check "..saying it is still so" grep -q 'stalled stl .*(still, since' <<<"$(heard orch | tail -1)"
check "..but finished is said once, ever" bash -c "! grep -q 'finished fin' <<<\"\$(tail -1 '$HOME/heard-orch')\""
check "the phone hears lone again too" [ "$(nphone 'stalled lone')" = 2 ]

echo "== --health: the same verdicts, sending nothing"
out="$("$W" --health)"; rc=$?
check "exit 1 while something is wrong" [ "$rc" = 1 ]
check "..lists stl as stalled under orch" grep -qE '^stalled +stl +orch ' <<<"$out"
check "..and lonefin as left to the phone" grep -qE '^finished +lonefin .*phone has it' <<<"$out"
check "..and typed nothing" [ "$(nheard orch)" = 2 ]

echo "== --dry-run says what it would type, and types nothing"
age_ledger
out="$("$W" --dry-run 2>&1)"
check "WOULD-REPORT to orch's pane" grep -q 'WOULD-REPORT to %[0-9]*: MUXTOPUS watchdog' <<<"$out"
check "..and nothing reached orch" [ "$(nheard orch)" = 2 ]

echo "== disarmed: nothing is typed into any pane; the phone still hears"
"$W" --off >/dev/null
n="$(nphone 'stalled stl')"
pass
check "orch heard nothing" [ "$(nheard orch)" = 2 ]
check "..the phone heard about stl instead" [ "$(nphone 'stalled stl')" = $(( n + 1 )) ]
"$W" --on >/dev/null

echo "== WATCHDOG_REPORT"
setkey WATCHDOG_REPORT notify-only; age_ledger; n="$(nphone 'stalled stl')"
pass
check "notify-only: the phone, not orch" bash -c "[ $(nheard orch) = 2 ] && [ $(nphone 'stalled stl') = $(( n + 1 )) ]"
setkey WATCHDOG_REPORT off; age_ledger; n="$(phone | grep -c '')"
pass
check "off: nobody" bash -c "[ $(nheard orch) = 2 ] && [ $(phone | grep -c '') = $n ]"
check "..and the ledger is gone, so on again starts fresh" [ ! -f "$ST/reports" ]
check "..while the state is still published" [ "$(state stl)" = stalled ]
check "--health with it off: all good" bash -c "'$W' --health | grep -q '^all good'"
setkey WATCHDOG_REPORT on

echo "== the parent cannot hear: it is gone"
tmux kill-window -t claude:orch
sleep 1; pass
check "stl's stall goes to the phone instead" grep -q 'stalled stl' <<<"$(phone | tail -3)"
check "..saying why" grep -q 'stalled stl' "$ST/log" && grep -q 'report to the phone (parent orch has no live session)' "$ST/log"
lane orch listen; sleep 2
sed -i '/^orch\t/d' "$ST/tree.tsv"; tree orch

echo "== WATCHDOG_NUDGE_STALLED (off by default)"
lane nud listen; printf '# nud\n' > "$HO/STATUS-nud.md"; old_turn nud 30; sleep 2; tree nud orch
pass
check "off: nud is stalled and is not typed into" bash -c "[ '$(state nud)' = stalled ] && [ -z \"\$(cat '$HOME/heard-nud' 2>/dev/null)\" ]"
setkey WATCHDOG_NUDGE_STALLED on
rm -f "$ST/reports"     # a fresh episode for every lane
pass
check "on: nud is told its job ended" grep -q 'Your background job has ended' <<<"$(heard nud)"
check "..once" [ "$(heard nud | grep -c 'Your background job')" = 1 ]
check "..and the report says it did" grep -q 'stalled nud (claude:[0-9]*): .* -- nudged it to continue' <<<"$(heard orch)"
pass; age_ledger; pass
check "still stalled, an hour on: never nudged twice in one episode" [ "$(heard nud | grep -c 'Your background job')" = 1 ]
printf '# asks\n' > "$HO/QUESTIONS-nud.md"; rm -f "$ST/reports"; pass
check "a lane with an unanswered QUESTIONS file is not nudged" [ "$(heard nud | grep -c 'Your background job')" = 1 ]
check "..and the report says why" grep -q 'not nudged: its QUESTIONS file is unanswered' <<<"$(heard orch | tail -1)"
rm -f "$HO/QUESTIONS-nud.md"
setkey WATCHDOG_NUDGE_STALLED off

echo "== WATCHDOG_CLOSE_FINISHED (off by default)"
check "off: fin's window is still open" has_window fin
printf 'type: work\nat: 2099-01-01 00:00\nslug: after-lonefin\nafter: lonefin\ncwd: %s\nstatus: pending\n---\nx\n' "$HOME" > "$SC/after-lonefin.md"
setkey WATCHDOG_CLOSE_FINISHED 0
pass
check "0: fin's window is closed" bash -c "! tmux list-windows -t claude -F '#{window_name}' | grep -qx fin"
check "..and the log says how to get it back" grep -q 'closed finished window fin .*claude --resume sid-fin' "$ST/log"
check "lonefin is kept: a pending entry waits on it" has_window lonefin
check "stl is kept: it is not finished" has_window stl

echo "== an e2e slot held past WATCHDOG_REPORT_E2E_MIN"
lane slot e2e; printf '# slot\n' > "$HO/STATUS-slot.md"; sleep 3; tree slot orch
pass
check "held a few seconds: nothing" bash -c "! grep -q 'e2e slot held' \"\$(echo '$HOME/heard-orch')\""
# Six hours of uptime more: every process looks six hours older.
read -r up _ < /proc/uptime
printf '%s 0\n' "$(( ${up%.*} + 21600 ))" > "$SB/uptime"
MUX_UPTIME="$SB/uptime" "$W" --once >/dev/null 2>&1
check "held 6h: orch is told, naming the lane" grep -qE 'e2e slot \(claude:[0-9]+\): an e2e slot held 6h by pid [0-9]+' <<<"$(heard orch | tail -1)"
check "..not when the clock says it is young again" bash -c "! '$W' --health | grep -q '^e2e'"

echo "== entries the memory guard has held past WATCHDOG_REPORT_MEM_MIN"
printf 'MemTotal: 30408704 kB\nMemFree: 1048576 kB\nMemAvailable: 1048576 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n' > "$SB/meminfo"
printf 'type: work\nat: 2020-01-01 00:00\nslug: orch-held\nparent: orch\ncwd: %s\nstatus: pending\n---\nx\n' "$HOME" > "$SC/orch-held.md"
MUX_MEMINFO="$SB/meminfo" "$W" --once >/dev/null 2>&1
check "the entry is held: memory" grep -q $'^orch-held.md\theld\theld: memory' "$ST/sched-why.tsv"
check "..and orch is not told at once" bash -c "! grep -q 'memory has been low' \"\$(echo '$HOME/heard-orch')\""
awk -F'\t' -v OFS='\t' -v t=$(( $(date +%s) - 3600 )) '{$5 = t; print}' "$ST/memory" > "$ST/memory.tmp" && mv "$ST/memory.tmp" "$ST/memory"
MUX_MEMINFO="$SB/meminfo" "$W" --once >/dev/null 2>&1
check "an hour on: orch is told which of its entries are held" grep -q 'memory: memory has been low for 1h (.*), holding orch-held' <<<"$(heard orch | tail -1)"
rm -f "$SC/orch-held.md"

echo "== a limit that reset and did not resume"
if [ "$(date +%H%M)" -lt 0010 ]; then
  echo "  (skipped: the minutes after midnight make a five-minutes-ago reset read as tonight's)"
else
  lane lim limit; printf '# lim\n' > "$HO/STATUS-lim.md"; sleep 2; tree lim orch
  "$W" --optout sid-lim >/dev/null    # so the watchdog itself never resumes it
  pass
  check "lim is due (opted out, so nothing types the continue message)" [ "$(state lim)" = due ]
  check "..and is not reported at once: resumes take a pass or a wave" bash -c "! grep -q 'limit lim' \"\$(echo '$HOME/heard-orch')\""
  age_ledger 1000; pass
  check "past WATCHDOG_STALL_MIN: orch is told" grep -q 'limit lim (claude:[0-9]*): its usage limit has reset and it has not resumed (due)' <<<"$(heard orch | tail -1)"
fi

echo "== the config keys"
check "every knob is a config key" bash -c "for k in WATCHDOG_STALL_MIN WATCHDOG_REPORT WATCHDOG_REPORT_REPEAT_MIN WATCHDOG_REPORT_E2E_MIN WATCHDOG_REPORT_MEM_MIN WATCHDOG_NUDGE_STALLED WATCHDOG_CLOSE_FINISHED; do grep -q \"^\$k=\" '$REPO/profile.sh' || exit 1; done"

sb_done
