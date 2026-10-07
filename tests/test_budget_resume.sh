#!/usr/bin/env bash
# AFTER A LIMIT: what the watchdog now recognises as stopped, and how it
# brings it back -- in waves, in priority order, and FRESH from the handover
# when the context is big. claude-watchdog.sh limit_scan, budget_queue,
# budget_resume_wave, budget_fresh_resume, budget_close_replaced.
#
#   bash tests/test_budget_resume.sh
#
# WHY. Three things measured on this box:
#   * "You've hit your weekly limit · resets Oct 10, 5pm" and "You've reached
#     your Fable limit" (18 and 7 of them in the transcripts) never matched the
#     one test the watchdog had, "hit your session limit": such a window was
#     `idle`, and nothing restarted it. Nor was a lane whose turn ENDED with
#     its own "the usage limit was reached" (roadmap 36, 2026-10-05).
#   * After a reset every stopped window was typed into in one pass: nineteen
#     cold resumes at once is the 61%-in-fifteen-minutes storm.
#   * A cold resume of a 500k context costs 2.1% of a Max 5x window for its
#     first turn alone, and 6.7%/h after; the lane's handover is cheaper.
#
# SANDBOX: tests/notify_sandbox.sh (own HOME and XDG dirs, a private -L tmux,
# a fake claude). The clock is real; the ledgers are written with epochs the
# right distance from now, as tests/test_wound_resume.sh does.
#
# COUNTERFACTUAL: against origin/main's claude-watchdog.sh (BUDGET_WATCHDOG=
# ...) the weekly and model windows read `idle`, all three limited windows are
# prompted in the first pass, and no resume entry is ever written.
SB_SOCKET="mxbres$$"
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="${BUDGET_WATCHDOG:-$REPO/claude-watchdog.sh}"
SC="$HOME/.code/schedules"; ST="$XDG_STATE_HOME/claude-watchdog"; HO="$HOME/.code/handovers"
mkdir -p "$ST" "$HOME/.claude/projects/p"
setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
NOW="$(date +%s)"
usage() {  # usage SESSION WEEK [MODEL_PCT [MODEL_RESET_AGO_H]]
  local sr=$(( NOW + 4 * 3600 )) wr=$(( NOW + 144 * 3600 )) mr=$(( NOW - ${4:--100} * 3600 ))
  printf 'at\t%s\nsession_pct\t%s\nsession_reset\t%s\nsession_reset_at\t%s\nweek_pct\t%s\nweek_reset\t%s\nmodel\tFable\nmodel_pct\t%s\nmodel_reset\t%s\naccount\tpersonal\n' \
    $(( NOW - 60 )) "$1" "$(date -d "@$sr" +%H:%M)" "$sr" "$2" "$(date -d "@$wr" '+%b %d, %H:%M')" \
    "${3:-0}" "$(date -d "@$mr" '+%b %d, %H:%M')" > "$ST/usage.tsv"
}
entry() {  # entry NAME [priority]
  printf 'type: work\nat: 2020-01-01 00:00\nslug: %s\ncwd: %s\nmodel: opus\neffort: high\n%sstatus: pending\n---\nthe original brief for %s\n' \
    "$1" "$HOME" "${2:+priority: $2
}" "$1" > "$SC/$1.md"
}
pass() { "$W" --once >/dev/null 2>&1; }
# launch NAME [priority]: the entry, the pass that opens its window, and the
# pass that first SEES the window (status.tsv is written before the launches).
launch() { entry "$@"; pass; pass; }
col() { awk -F'\t' -v n="$1" -v c="$2" '$2==n{print $c}' "$ST/status.tsv"; }
sid_of() { col "$1" 1; }
prompted() { grep -q "^$(sid_of "$1")	" "$ST/prompted" 2>/dev/null; }
screen() { printf '%b' "$1" > "$HOME/fake-screen"; sleep 1; }
transcript() {  # transcript NAME CTX TEXT AGO_MIN
  local sid; sid="$(sid_of "$1")"
  printf '{"type":"assistant","timestamp":"%s","message":{"model":"claude-opus-5-5","content":[{"type":"text","text":"%s"}],"usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":%s,"cache_creation_input_tokens":0}}}\n' \
    "$(date -u -d "@$(( NOW - $4 * 60 ))" +%FT%T.000Z)" "$3" "$2" > "$HOME/.claude/projects/p/$sid.jsonl"
}
clear_all() {
  local w
  rm -f "$SC"/*.md "$ST/prompted" "$ST/budget-starts" "$ST/usage.log" "$HO"/STATUS-*.md "$HOME/.claude/projects/p"/*.jsonl
  for w in $(tmux list-windows -t claude -F '#{window_id} #{window_name}' | awk '$2!="home"{print $1}'); do tmux kill-window -t "$w"; done
  rm -f "$HOME/.claude/sessions"/*.json
  screen '● ready\n❯ '
}
tmux new-session -d -s claude -n home -x 200 -y 40 "sleep 600"
"$W" --on >/dev/null
setkey WATCHDOG_BUDGET_PLAN max5x; setkey WATCHDOG_BUDGET_LANES 9
screen '● ready\n❯ '
usage 5 10

echo "== the weekly banner is a limit, not idle; due once its reset has passed"
launch wk
YDAY="$(date -d '-1 day' '+%b %-d'), $(date -d '-1 day' '+%-l%P')"
screen "You've hit your weekly limit · resets $YDAY (Europe/Bucharest)\n❯ "
setkey WATCHDOG_BUDGET off; pass
check "a weekly stop whose reset passed is prompted" prompted wk
check "..the status said why" grep -q "prompted .* in wk .*after reset" "$ST/log"
clear_all
TMRW="$(date -d '+1 day' '+%b %-d'), $(date -d '+1 day' '+%-l%P')"
launch wk2
screen "You've hit your weekly limit · resets $TMRW (Europe/Bucharest)\n❯ "
usage 5 100; pass
check "a weekly stop before its reset: state limited (was idle)" [ "$(col wk2 6)" = limited ]
check "..not prompted" bash -c "! grep -q . '$ST/prompted' 2>/dev/null"
clear_all

echo "== a model limit is a limit; due once usage.tsv's model_reset has passed"
launch md
screen "You've reached your Fable limit. Run /usage-credits to continue or switch models with /model.\n❯ "
usage 5 10 100 -24; pass
check "model limit, reset tomorrow: limited" [ "$(col md 6)" = limited ]
usage 5 10 0 1; pass
check "model reset an hour ago: prompted" prompted md
clear_all

echo "== a turn that ENDED saying the limit was reached, corroborated by usage.log"
launch said1
transcript said1 1000 "Stopping here: the session usage limit was reached in the subagent." 20
printf '%s\tsession=100%%\tresets=10:00\tweek=10%%\tresets=Oct 10, 17:00\tFable=0%%\n' "$(date -d "@$(( NOW - 600 ))" '+%F %T')" > "$ST/usage.log"
usage 3 11; pass
check "a reading after the stop shows room: prompted" prompted said1
clear_all
launch said2
transcript said2 1000 "The docs now explain what happens when the usage limit was reached." 20
printf '%s\tsession=40%%\tresets=10:00\tweek=10%%\tresets=Oct 10, 17:00\tFable=0%%\n' "$(date -d "@$(( NOW - 600 ))" '+%F %T')" > "$ST/usage.log"
usage 3 11; pass
check "the same words with no 100% reading near them: idle, untouched" [ "$(col said2 6)" = idle ]
check "..not prompted" bash -c "! grep -q . '$ST/prompted' 2>/dev/null"
clear_all

echo "== after a reset, stopped windows resume in WAVES, release first"
setkey WATCHDOG_BUDGET on; setkey WATCHDOG_BUDGET_WAVE 1
entry a-low p2; entry b-mid p1; launch c-rel release
AGO="$(date -d '-1 hour' '+%-l%P')"
screen "You've hit your session limit · resets $AGO (Europe/Bucharest)\n❯ "
pass
check "one wave of one: the release lane is prompted" prompted c-rel
check "..the p1 and p2 lanes are not, yet" bash -c "[ \"\$(grep -c . '$ST/prompted')\" = 1 ]"
check "..they wait as queued" [ "$(col b-mid 8):$(col a-low 8)" = queued:queued ]
check "..and the budget file says why" grep -q "resuming in waves of 1" "$ST/budget"
check "..one log line for the queue" [ "$(grep -c 'budget: 2 resume(s) waiting' "$ST/log")" = 1 ]
pass
check "a pass later: still one (the wave is ten minutes)" bash -c "[ \"\$(grep -c . '$ST/prompted')\" = 1 ]"
sed -i "s/^[0-9]*\t/$(( NOW - 900 ))\t/" "$ST/budget-starts"; pass
check "ten minutes on: the p1 lane next" prompted b-mid
check "..p2 still last" bash -c "! grep -q '^$(sid_of a-low)	' '$ST/prompted'"
sed -i "s/^[0-9]*\t/$(( NOW - 900 ))\t/" "$ST/budget-starts"; pass
check "and then the p2 lane" prompted a-low
clear_all

echo "== a big context with an open handover resumes FRESH from it"
setkey WATCHDOG_BUDGET_WAVE 2
launch big release
OLDWIN="$(tmux list-windows -t claude -F '#{window_id} #{window_name}' | awk '$2=="big"{print $1}')"
transcript big 300000 "working on it" 30
printf '# STATUS big\nnext: phase 3\n' > "$HO/STATUS-big.md"
OLDSID="$(sid_of big)"
screen "You've hit your session limit · resets $AGO (Europe/Bucharest)\n❯ "
pass
R="$SC/big-resume.md"
check "the resume entry is written" [ -f "$R" ]
check "..with the lane's own slug" grep -q '^slug: big$' "$R"
check "..the original's model, effort and priority" bash -c "grep -q '^model: opus$' '$R' && grep -q '^effort: high$' '$R' && grep -q '^priority: release$' '$R'"
check "..resume: fresh and the window it replaces" grep -q "^replaces: %[0-9]* $OLDSID$" "$R"
check "..'read your handover first', then the original brief" bash -c "grep -q 'resuming in a FRESH session.*300000 tokens' '$R' && grep -q 'the original brief for big' '$R'"
check "..and launched in the same pass" grep -q '^status: launched' "$R"
check "the old window is closed" bash -c "! tmux list-windows -t claude -F '#{window_id}' | grep -qx '$OLDWIN'"
check "..and the log names its session for claude --resume" grep -q "closed the old window $OLDWIN.*claude --resume $OLDSID" "$ST/log"
check "a window called big is open again" bash -c "tmux list-windows -t claude -F '#{window_name}' | grep -qx big"
check "the old session is in the prompted ledger (never typed into later)" grep -q "^$OLDSID	" "$ST/prompted"
check "--check sees the resume entry as launched" grep -q "status is 'launched'" <<<"$("$W" --check big-resume 2>/dev/null)"
clear_all

echo "== a big context WITHOUT a handover is resumed in place"
launch nohand
transcript nohand 300000 "working on it" 30
screen "You've hit your session limit · resets $AGO (Europe/Bucharest)\n❯ "
pass
check "prompted in place" prompted nohand
check "..no resume entry" [ ! -f "$SC/nohand-resume.md" ]
clear_all

echo "== --dry-run still only says what it would do"
launch dry
screen "You've hit your session limit · resets $AGO (Europe/Bucharest)\n❯ "
out="$("$W" --dry-run 2>/dev/null)"
check "WOULD-PROMPT, nothing queued" grep -q "WOULD-PROMPT" <<<"$out"
check "..nothing prompted" bash -c "! grep -q . '$ST/prompted' 2>/dev/null"

sb_done
