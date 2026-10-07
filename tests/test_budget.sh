#!/usr/bin/env bash
# THE BUDGET GUARD (claude-watchdog.sh budget_check / budget_gate), as a test.
#
#   bash tests/test_budget.sh
#
# WHY IT EXISTS. 2026-10-06, Max 5x: nineteen lanes started together after a
# reset and spent 61% of the 5-hour window in about fifteen minutes; every one
# of them then stopped at the limit. A due entry is now HELD past a cap of
# working windows, past a session line that moves with its priority class,
# when it could not reach a checkpoint before the budget runs out, and when
# the week is ahead of its pace (a manual weekly reset counting as a week
# already spent); `at: reset` entries go out in waves.
#
# THE ACCOUNT IS FAKED, THE DAEMON IS NOT: usage.tsv and usage.log are written
# here, so "41% read a minute ago, a manual reset on Tuesday" is two printfs.
# Every case runs the real `--once` pass against the real launcher in the
# sandbox of tests/notify_sandbox.sh (its own HOME and XDG dirs, a tmux pinned
# to a private -L socket, a fake claude), so nothing here can reach a real
# pane, a real schedule or the real budget.
#
# COUNTERFACTUAL: run this file against origin/main's claude-watchdog.sh
# (BUDGET_WATCHDOG=...) and every "held" case launches its entry.
SB_SOCKET="mxbudget$$"
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="${BUDGET_WATCHDOG:-$REPO/claude-watchdog.sh}"
SC="$HOME/.code/schedules"; ST="$XDG_STATE_HOME/claude-watchdog"
mkdir -p "$ST"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
unkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; }
NOW="$(date +%s)"
# usage SESSION_PCT AGE_MIN [WEEK_PCT [WEEK_RESET_IN_H [SESSION_RESET_IN_MIN]]]
usage() {
  local sr=$(( NOW + ${5:-240} * 60 )) wr=$(( NOW + ${4:-144} * 3600 ))
  printf 'at\t%s\nsession_pct\t%s\nsession_reset\t%s\nsession_reset_at\t%s\nweek_pct\t%s\nweek_reset\t%s\nmodel\tFable\nmodel_pct\t0\naccount\tpersonal\n' \
    $(( NOW - $2 * 60 )) "$1" "$(date -d "@$sr" +%H:%M)" "$sr" "${3:-10}" "$(date -d "@$wr" '+%b %d, %H:%M')" > "$ST/usage.tsv"
}
# logline AGO_MIN SESSION WEEK SESSION_RESET WEEK_RESET_DATE
logline() {
  printf '%s\tsession=%s%%\tresets=%s\tweek=%s%%\tresets=%s, 17:00\tFable=0%%\n' \
    "$(date -d "@$(( NOW - $1 * 60 ))" '+%F %T')" "$2" "$4" "$3" "$5" >> "$ST/usage.log"
}
entry() {  # entry NAME [priority] [at]
  printf 'type: work\nat: %s\nslug: %s\ncwd: %s\n%sstatus: pending\n---\ncarry on\n' \
    "${3:-2020-01-01 00:00}" "$1" "$HOME" "${2:+priority: $2
}" > "$SC/$1.md"
}
launched() { grep -q '^status: launched' "$SC/$1.md"; }
pending() { grep -q '^status: pending' "$SC/$1.md"; }
verdict() { awk -F'\t' -v b="$1.md" '$1==b{print $2}' "$ST/sched-why.tsv"; }
why() { awk -F'\t' -v b="$1.md" '$1==b{print $3}' "$ST/sched-why.tsv"; }
bval() { awk -F'\t' -v k="$1" '$1==k{print $2}' "$ST/budget"; }
pass() { "$W" --once >/dev/null 2>&1; }
# working N: N windows whose claude is mid-turn ("esc to interrupt")
printf '● Working… (esc to interrupt)\n❯ \n' > "$SB/working-screen"
working() {
  local i
  for i in $(seq 1 "$1"); do
    tmux new-window -d -t claude: -n "busy$i" "env FAKE_SCREEN_FILE=$SB/working-screen claude"
  done
  sleep 1.5
}
reset_sandbox() {
  rm -f "$SC"/*.md "$ST/budget-starts" "$ST/week-resets" "$ST/usage.log"
  tmux kill-window -t claude:busy1 2>/dev/null; local i
  for i in 1 2 3 4 5 6; do tmux kill-window -t "claude:busy$i" 2>/dev/null; done
  for w in $(tmux list-windows -t claude -F '#{window_name}' | grep -v '^home$'); do tmux kill-window -t "claude:$w"; done
  rm -f "$HOME/.claude/sessions"/*.json
  sleep 0.5
}
printf '● ready\n❯ \n' > "$HOME/fake-screen"
tmux new-session -d -s claude -n home -x 160 -y 40 "sleep 600"
"$W" --on >/dev/null

echo "== the plan: detected from the account's rateLimitTier, overridable"
check "no credentials: max5x numbers, and it says it guessed" grep -q "plan=max5x (not detected" <<<"$("$W" --budget)"
printf '{"claudeAiOauth":{"subscriptionType":"max","rateLimitTier":"default_claude_max_20x"}}\n' > "$HOME/.claude/.credentials.json"
out="$("$W" --budget)"
check "max_20x tier: the 20x preset" grep -q "plan=max20x (detected (default_claude_max_20x))" <<<"$out"
check "..its cap is 12" grep -q "cap 12 windows" <<<"$out"
printf '{"claudeAiOauth":{"subscriptionType":"team","rateLimitTier":"default_claude_max_5x"}}\n' > "$HOME/.claude/.credentials.json"
check "team subscription with the max_5x tier: the TIER wins" grep -q "plan=max5x (detected (default_claude_max_5x))" <<<"$("$W" --budget)"
printf '{"claudeAiOauth":{"subscriptionType":"pro"}}\n' > "$HOME/.claude/.credentials.json"
check "pro with no tier: pro, cap 1" grep -q "cap 1 windows" <<<"$("$W" --budget)"
setkey WATCHDOG_BUDGET_PLAN max5x; setkey WATCHDOG_BUDGET_LANES 7
out="$("$W" --budget)"
check "WATCHDOG_BUDGET_PLAN pins the preset" grep -q "plan=max5x (WATCHDOG_BUDGET_PLAN=max5x)" <<<"$out"
check "..and one knob overrides one number" grep -q "cap 7 windows · hold at 70%" <<<"$out"
unkey WATCHDOG_BUDGET_LANES
# The rest of the file runs the measured preset, whatever the box says.
rm -f "$HOME/.claude/.credentials.json"

echo "== the cap: past WATCHDOG_BUDGET_LANES working windows a due entry is HELD"
usage 5 1; setkey WATCHDOG_BUDGET_LANES 2
working 2; entry capped; pass
check "two working, cap 2: not launched" pending capped
check "..its verdict is held" [ "$(verdict capped)" = held ]
check "..naming the count and the key" grep -q "2 windows working, the cap is 2 (WATCHDOG_BUDGET_LANES" <<<"$(why capped)"
check "one log line when the guard starts holding" [ "$(grep -c 'budget: holding 1 launch' "$ST/log")" = 1 ]
check "the budget file counts them" [ "$(bval running):$(bval held)" = 2:1 ]
check "--check says HELD" grep -q "verdict *HELD -- due.*the cap is 2" <<<"$("$W" --check capped 2>/dev/null)"
setkey WATCHDOG_BUDGET_LANES 3; pass
check "cap 3: launched" launched capped
check "..and the log says the guard let go" grep -q "budget: no longer holding launches" "$ST/log"
reset_sandbox

echo "== the session line moves with the class: release +10, p1 0, ops -5, p2 -10"
setkey WATCHDOG_BUDGET_LANES 9
usage 65 1
entry rel release; entry one p1; entry opsy ops; entry low p2; entry plain; pass
check "65%: release launches (line 80)" launched rel
check "65%: p1 launches (line 70)" launched one
check "65%: no priority: is p1, launches" launched plain
check "65%: ops is held (line 65)" [ "$(verdict opsy)" = held ]
check "65%: p2 is held (line 60)" [ "$(verdict low)" = held ]
check "..saying which line, and why it moved" grep -q "at or over the p2 line of 60% (WATCHDOG_BUDGET_HOLD_PCT=70 -10 for p2)" <<<"$(why low)"
reset_sandbox

echo "== the estimate: an old reading plus the burn since it"
usage 50 60
working 2; entry est1; pass
check "50% an hour ago, 2 working x 8%/h: ~66%" [ "$(bval session_est)" = 66 ]
check "..p1 (line 70) launches" launched est1
check "..and the file says how it was made" grep -q "read 50% 60m ago, + 16%/h since" <<<"$(bval session_est_src)"
setkey WATCHDOG_BUDGET_LANE_PCT 20; entry est2; pass
check "at 20%/lane-hour the same reading is ~90%: held" [ "$(verdict est2)" = held ]
check "..and a projected exhaustion before the reset" [ -n "$(bval exhaust_at)" ]
unkey WATCHDOG_BUDGET_LANE_PCT
reset_sandbox

echo "== a reading older than WATCHDOG_USAGE_STALE is blind: the cap still holds, the line does not"
usage 95 300; setkey WATCHDOG_BUDGET_LANES 1; working 1; entry blind1; pass
check "blind, but one working at cap 1: held by the cap" grep -q "the cap is 1" <<<"$(why blind1)"
check "..the file says why it is blind" grep -q "past WATCHDOG_USAGE_STALE" <<<"$(bval blind)"
setkey WATCHDOG_BUDGET_LANES 9; pass
check "room under the cap: a blind guard launches at 95%" launched blind1
reset_sandbox

echo "== never start what cannot reach a checkpoint before the budget runs out"
setkey WATCHDOG_BUDGET_HOLD_PCT 95; setkey WATCHDOG_BUDGET_LANE_PCT 40
usage 80 0 10 144 240; entry ck1; pass
check "80%, 40%/h, reset in 4h: ~24m left < 30m -- held" [ "$(verdict ck1)" = held ]
check "..saying so" grep -q "would run out in ~24m.*before a 30m checkpoint" <<<"$(why ck1)"
usage 80 0 10 144 10; pass
check "the same, but the reset is 10 min away: launched" launched ck1
unkey WATCHDOG_BUDGET_HOLD_PCT; unkey WATCHDOG_BUDGET_LANE_PCT
reset_sandbox

echo "== the week's pace, a manual reset counted as a week already spent"
# week resets in 6 days: one day elapsed, the pace allows 14 x 2 = 28%
usage 5 1 40 144
entry wp2 p2; entry wp1 p1; entry wrel release; pass
check "40% a day in: p2 is held (pace 28%)" [ "$(verdict wp2)" = held ]
check "..p1 launches (two days in hand: 56%)" launched wp1
check "..release launches" launched wrel
rm -f "$SC"/*.md
D="$(date -d "@$(( NOW + 144 * 3600 ))" '+%b %d')"
logline 300 10 95 10:00 "$D"; logline 240 12 3 10:00 "$D"
logline 120 20 30 10:00 "$D"; logline 1 22 40 10:00 "$D"
entry wp1b p1; entry wrelb release; pass
check "95% -> 3% with the same reset date: one manual reset" [ "$(bval manual_resets)" = 1 ]
check "..the week reads 140% effective" [ "$(bval week_eff)" = 140 ]
check "..p1 is held now" [ "$(verdict wp1b)" = held ]
check "..naming the reset" grep -q "140% effective (40% + 1 manual reset x 100)" <<<"$(why wp1b)"
check "..release still launches" launched wrelb
"$W" --budget-reset-spent "pressed on the phone" >/dev/null
pass
check "--budget-reset-spent adds one by hand" [ "$(bval manual_resets)" = 2 ]
reset_sandbox
usage 5 1 100 1; entry spent release; pass
check "a week at 100% holds even a release entry" grep -q "the week is at its limit (100%)" <<<"$(why spent)"
reset_sandbox
logline 300 10 95 10:00 "Oct 03"; logline 240 12 3 10:00 "Oct 10"; pass
check "a drop where the reset DATE moved is a natural reset: not counted" [ "$(bval manual_resets)" = 0 ]
reset_sandbox

echo "== priority order: when one may start, release starts before p2"
usage 5 1; setkey WATCHDOG_BUDGET_LANES 2; working 1
entry a-low p2; entry z-rel release; pass
check "the release entry (later in file order) launched" launched z-rel
check "the p2 entry (first in file order) is held by the cap" [ "$(verdict a-low)" = held ]
reset_sandbox

echo "== waves: \`at: reset\` entries start WATCHDOG_BUDGET_WAVE at a time"
setkey WATCHDOG_BUDGET_LANES 9; setkey WATCHDOG_BUDGET_WAVE 1
usage 5 1
entry wave1 p1 reset; entry wave2 p1 reset; entry timed p1; pass
n=0; launched wave1 && n=$((n+1)); launched wave2 && n=$((n+1))
check "one of two at: reset entries started" [ "$n" = 1 ]
check "..the other is held, waiting for its wave" grep -q "resuming in waves of 1 every 10m" <<<"$(why wave1)$(why wave2)"
check "an entry with a time is not in a wave" launched timed
pass
n=0; launched wave1 && n=$((n+1)); launched wave2 && n=$((n+1))
check "a pass later, still one (the wave is 10 minutes)" [ "$n" = 1 ]
sed -i "s/^[0-9]*\t/$(( NOW - 900 ))\t/" "$ST/budget-starts"; pass
check "ten minutes on, the next wave starts" bash -c "grep -q '^status: launched' '$SC/wave1.md' && grep -q '^status: launched' '$SC/wave2.md'"
unkey WATCHDOG_BUDGET_WAVE
reset_sandbox

echo "== WATCHDOG_BUDGET=off: nothing is held"
setkey WATCHDOG_BUDGET off; setkey WATCHDOG_BUDGET_LANES 1
usage 99 1 100; working 2; entry free p2; pass
check "launched at 99%, over the cap, a p2" launched free
check "the file says off" [ "$(bval on)" = off ]
unkey WATCHDOG_BUDGET; unkey WATCHDOG_BUDGET_LANES
reset_sandbox

echo "== the wind-down: a p2 lane is told to checkpoint ten points before a p1"
"$W" --monitor-on >/dev/null
setkey WATCHDOG_BUDGET_LANES 9
usage 5 1
cp "$SB/working-screen" "$HOME/fake-screen"
entry wlow p2; entry wone p1; pass
check "both launched" bash -c "grep -q '^status: launched' '$SC/wlow.md' && grep -q '^status: launched' '$SC/wone.md'"
sleep 1; usage 77 0; pass
sid_of() { awk -F'\t' -v n="$1" '$2==n{print $1}' "$ST/status.tsv"; }
DL="$ST/directives/$(sid_of wlow)"; DO="$ST/directives/$(sid_of wone)"
check "77%: the p2 lane (hard line 75) got the checkpoint" grep -q "^Budget checkpoint" "$DL"
check "..although its context is small" grep -q "wound down .* in wlow band=2 .*ctx=0 class=p2" "$ST/log"
check "77%: the p1 lane (hard line 85) only the soft note" grep -q "^Budget note" "$DO"
printf '● ready\n❯ \n' > "$HOME/fake-screen"

sb_done
