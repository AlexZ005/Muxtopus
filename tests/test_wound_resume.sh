#!/usr/bin/env bash
# A HARD WIND-DOWN IS NOT A ONE-WAY DOOR -- the bug, and the fix, as a test.
#
#   bash tests/test_wound_resume.sh
#
# WHAT HAPPENED, measured on 2026-09-20 in ~/.local/state/claude-watchdog/:
# window `muxtopus-updates`, session 2e4704f3, `wound` row
#
#     2e4704f3…   2   1789897500   1789896340
#
# -- band 2 (hard) at 12:25:40, for the budget window that resets at 12:45.
# The band-2 directive says "land the step you are on now and commit it, then
# write a handoff … Then stop." The window obeyed and stopped at 12:32 with an
# open handover saying "Resume after the session reset". The reset passed. At
# 13:10 it was still idle and nothing had touched it.
#
# It could not have been touched. The resume path fires only for a pane whose
# text matches "hit your session limit", and a window that stopped BECAUSE IT
# WAS TOLD TO, before reaching the limit, never prints that banner; wind_down
# writes no schedule entry either. The one mechanism that would restart it
# keys off a condition its own directive guarantees will never occur.
#
# So the real row above is replayed here, twice: once against the watchdog as
# it is now (the window is resumed, exactly once), and once with
# WATCHDOG_WOUND_RESUME=off, which is today's code path -- and there the
# window is never prompted, which is the bug, reproduced.
#
# THE CLOCK IS NOT FAKED, THE LEDGER IS: every case writes the `wound` row it
# needs with an epoch the required distance from now, which is the same idiom
# tests/test_stats_watchdog.sh uses for the collect stamp. Nothing sleeps.
#
# SANDBOX DISCIPLINE: its own HOME, XDG_*, MUXTOPUS_CONFIG and
# CLAUDE_CONFIG_DIR, and a tmux pinned to -L mxwound, so nothing here can
# reach `claude:0` or any window you are working in.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
W="$REPO/claude-watchdog.sh"
FAILS=0; PASSES=0
ok()   { PASSES=$(( PASSES + 1 )); printf '  ok   %s\n' "$1"; }
bad()  { FAILS=$(( FAILS + 1 ));  printf '  FAIL %s\n' "$1"; }
check() { local what="$1"; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

# THE SOCKET CARRIES THIS RUN'S PID. tests/test_stats_watchdog.sh can use a
# fixed name because nothing else drives it; two lanes (or a lane and a
# re-run) starting this file at once on one name would share a tmux server,
# and the first to finish would kill the other's pane out from under it --
# measured, and it reads as twenty unrelated assertion failures.
SOCK="mxwound$$"
SB="$(mktemp -d "${TMPDIR:-/tmp}/mxwound-XXXXXX")"
export HOME="$SB/home"
export XDG_CONFIG_HOME="$HOME/.config" XDG_STATE_HOME="$HOME/.local/state"
export XDG_DATA_HOME="$HOME/.local/share" XDG_RUNTIME_DIR="$SB/run"
export MUXTOPUS_CONFIG="$HOME/.config/muxtopus/config"
unset CLAUDE_CONFIG_DIR TMUX TMUX_PANE MUXTOPUS_HOME MUXTOPUS_DIR MUXTOPUS_PROFILES_DIR
for k in $(compgen -e); do
  case "$k" in WATCHDOG_*|DASHBOARD_*|MUXTOPUS_NOTIFY_*) unset "$k" ;; esac
done
mkdir -p "$HOME/.config/muxtopus" "$HOME/.claude/sessions" "$HOME/.claude/projects" \
         "$XDG_STATE_HOME" "$SB/run" "$SB/bin"
printf 'MUXTOPUS_HOME="%s"\nWATCHDOG_INTERVAL=1\nWATCHDOG_STRANDED=0\n' "$HOME/.code" \
  > "$MUXTOPUS_CONFIG"
mkdir -p "$HOME/.code/schedules" "$HOME/.code/handovers/done"

ST="$XDG_STATE_HOME/claude-watchdog"
HANDOVERS="$HOME/.code/handovers"

# tmux on a server of its own, under both names the code reaches it by: the
# PATH wrapper for anything that runs a bare `tmux`, and MUXTOPUS_TMUX_SOCKET
# for profile.sh's mux_tmux, which passes -L on every call (a later -L wins in
# tmux's own parsing, so the wrapper alone would be overridden).
printf '#!/bin/sh\nexec %s -u -L %s -f /dev/null "$@"\n' "$(command -v tmux)" "$SOCK" \
  > "$SB/bin/tmux"
chmod +x "$SB/bin/tmux"
export PATH="$SB/bin:$PATH"
export MUXTOPUS_TMUX_SOCKET="$SOCK"
T() { command tmux -u -L "$SOCK" -f /dev/null "$@"; }

cleanup() {
  T kill-server 2>/dev/null
  [ -n "${KEEP_SANDBOX:-}" ] || rm -rf "$SB"
}
trap cleanup EXIT

SID="2e4704f3-0000-4000-8000-000000000000"      # the real row's session, padded
LANE="muxtopus-updates"                          # and the real window's name
# The real `wound` row, to the second: band 2, budget window resetting 12:45,
# wound at 12:25:40 on 2026-09-20.
REAL_QKEY=1789897500
REAL_AT=1789896340

T kill-server 2>/dev/null
T new-session -d -s wd -n "$LANE" -x 100 -y 30 "sleep 900" || {
  echo "cannot start the sandbox tmux server"; exit 2; }
PANEID="$(T display-message -p -t wd:0 '#{pane_id}')"

# THE SESSION RECORD, REWRITTEN FROM WHAT THE PANE IS NOW. The daemon skips a
# record whose pid is not alive, and respawn-pane gives the pane a new one --
# so a record written once and left goes stale the first time a case respawns
# the pane, the session vanishes from status.tsv and every assertion about it
# fails for a reason that is the harness's and not the code's. Measured, on
# the first run of this file.
session_json() {   # $1 = the pane's command line
  rm -f "$HOME"/.claude/sessions/*.json
  T respawn-pane -k -t wd:0 "${1:-sleep 900}" 2>/dev/null
  T clear-history -t wd:0 2>/dev/null
  sleep 0.3
  PANEPID="$(T display-message -p -t wd:0 '#{pane_pid}')"
  printf '{"pid":%s,"sessionId":"%s","cwd":"%s","version":"0.0.0","status":"idle","kind":"interactive","tmux":"wd:@0.%s"}\n' \
    "$PANEPID" "$SID" "$HOME" "$PANEID" > "$HOME/.claude/sessions/$PANEPID.json"
}

# The state the watchdog is allowed to act from: the global switch on.
mkdir -p "$ST"
: > "$ST/enabled"

reset_state() {   # every case starts from the same slate
  rm -f "$ST/wound" "$ST/prompted" "$ST/status.tsv" "$ST/log"
  rm -f "$HANDOVERS/STATUS-$LANE.md" "$HANDOVERS/done/STATUS-$LANE.md"
  rm -f "$ST/optout" "$ST/monitor-optout"
  session_json
}

wound_row() {     # band, quantized reset epoch, when
  printf '%s\t%s\t%s\t%s\n' "$SID" "$1" "$2" "$3" >> "$ST/wound"
}
open_handover() { printf '# %s\n\nResume after the session reset.\n' "$LANE" \
                    > "$HANDOVERS/STATUS-$LANE.md"; }
done_handover() { open_handover; mv "$HANDOVERS/STATUS-$LANE.md" \
                    "$HANDOVERS/done/STATUS-$LANE.md"; }

run()  { "$W" --once >/dev/null 2>&1; }
dry()  { "$W" --dry-run >/dev/null 2>&1; }
col()  { awk -F'\t' -v s="$SID" -v c="$1" '$1==s{print $c}' "$ST/status.tsv" 2>/dev/null; }
acted(){ col 8; }
state(){ col 6; }
typed(){ T capture-pane -p -t wd:0 2>/dev/null | grep -c 'Continue from where you left off'; }
# grep -c PRINTS 0 and then EXITS 1 when it matches nothing, and prints
# NOTHING at all when the file is absent -- so the count has to be defaulted
# here rather than leaned on (the idiom tests/test_stats_watchdog.sh uses).
nprompted() { local n; n="$(grep -c "^$SID" "$ST/prompted" 2>/dev/null)"; echo "${n:-0}"; }

echo "== the real row, replayed: band 2, idle, epoch passed, handover open"
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
open_handover
run
check "the window was resumed"                [ "$(acted)" = wound-resume ]
check "...by typing the continue message into its pane" [ "$(typed)" -ge 1 ]
check "...and it now reads as working"        [ "$(state)" = working ]
check "one prompted row, keyed on the wound epoch" [ "$(nprompted)" = 1 ]
check "the prompted row carries the quantized reset epoch" \
  grep -qP "^$SID\t$REAL_QKEY\t" "$ST/prompted"
check "the log says WHY, not just that it did" \
  grep -q "wound down hard for the budget window" "$ST/log"
check "the RESUMED column is filled in"       [ -n "$(col 9)" ]

echo "== and ONCE: a second pass does not prompt it again"
before="$(typed)"
run
check "the second pass did not act"           [ -z "$(acted)" ]
check "...and typed nothing further"          [ "$(typed)" = "$before" ]
check "...and wrote no second prompted row"   [ "$(nprompted)" = 1 ]
run
check "nor did a third"                       [ "$(nprompted)" = 1 ]

echo "== THE COUNTERFACTUAL: the same row with the new branch out of the way"
# WATCHDOG_WOUND_RESUME=off is the code path as it was before this change, so
# this is today's bug reproduced against today's real data -- and it is also
# the escape hatch's own test.
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
open_handover
WATCHDOG_WOUND_RESUME=off run
check "nothing was typed into the window"     [ "$(typed)" = 0 ]
check "no action was recorded"                [ -z "$(acted)" ]
check "it is simply idle, forever"            [ "$(state)" = idle ]
check "and nothing was ever prompted"         [ "$(nprompted)" = 0 ]

echo "== band 1 (soft) is a note about style: it never resumes anything"
reset_state
wound_row 1 "$REAL_QKEY" "$REAL_AT"
open_handover
run
check "a soft wind-down does not arm a resume" [ -z "$(acted)" ]
check "...and nothing was typed"               [ "$(typed)" = 0 ]
check "...and the window stays idle"           [ "$(state)" = idle ]

echo "== a window that is still WORKING is never typed into"
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
open_handover
# The TUI's own marker for a turn in flight, which is what the daemon reads.
session_json "sh -c 'echo esc to interrupt; sleep 900'"
run
check "a working window is left alone"         [ -z "$(acted)" ]
check "...and reads as working, not resume-due" [ "$(state)" = working ]
check "...and nothing was typed into it"        [ "$(typed)" = 0 ]

echo "== a pane that is ASKING A QUESTION is not answered with the resume"
# The window stopped at a permission dialog, not because it was told to. Typing
# the continue message there would put a sentence in the box and the Enter
# after it would ANSWER the dialog -- option 1, whatever option 1 is.
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
open_handover
T send-keys -t wd:0 "" 2>/dev/null
T respawn-pane -k -t wd:0 "sh -c 'cat $REPO/tests/fixtures/prompts/rm-dangerous.txt; sleep 900'"
sleep 0.4
PANEPID="$(T display-message -p -t wd:0 '#{pane_pid}')"
rm -f "$HOME"/.claude/sessions/*.json
printf '{"pid":%s,"sessionId":"%s","cwd":"%s","version":"0.0.0","status":"idle","kind":"interactive","tmux":"wd:@0.%s"}\n' \
  "$PANEPID" "$SID" "$HOME" "$PANEID" > "$HOME/.claude/sessions/$PANEPID.json"
run
check "a pane at a prompt is not resumed"      [ -z "$(acted)" ]
check "...and nothing was typed into it"       [ "$(typed)" = 0 ]
check "...and nothing was prompted"            [ "$(nprompted)" = 0 ]

echo "== a lane that FINISHED -- handover in done/ -- is not poked"
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
done_handover
run
check "a finished lane is not resumed"         [ -z "$(acted)" ]
check "...and nothing was typed"               [ "$(typed)" = 0 ]

echo "== no handover at all: nothing says the window meant to continue"
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
run
check "no handover, no resume"                 [ -z "$(acted)" ]
check "...and nothing was typed"               [ "$(typed)" = 0 ]

echo "== the budget window has NOT come back yet"
reset_state
wound_row 2 "$(( $(date +%s) + 3600 ))" "$(date +%s)"
open_handover
run
check "an epoch in the future does not fire"   [ -z "$(acted)" ]
check "...and nothing was typed"               [ "$(typed)" = 0 ]
check "...and the window is plain idle"        [ "$(state)" = idle ]

echo "== opted out of restarts (--optout): seen, said, and NOT typed into"
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
open_handover
printf '%s\n' "$SID" > "$ST/optout"
run
check "the opt-out is honoured"                [ "$(acted)" = opted-out ]
check "...and nothing was typed"               [ "$(typed)" = 0 ]
check "...but the pending resume is VISIBLE"   [ "$(state)" = resume-due ]
rm -f "$ST/optout"

echo "== opted out of MONITORING since: the wind-down's own switch"
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
open_handover
printf '%s\n' "$SID" > "$ST/monitor-optout"
run
check "a monitor opt-out also stops the resume" [ "$(acted)" = monitor-opted-out ]
check "...and nothing was typed"                [ "$(typed)" = 0 ]
rm -f "$ST/monitor-optout"

echo "== the watchdog switched off acts on nothing"
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
open_handover
rm -f "$ST/enabled"
run
check "the global switch is honoured"          [ "$(acted)" = watchdog-off ]
check "...and nothing was typed"               [ "$(typed)" = 0 ]
: > "$ST/enabled"

echo "== --dry-run says what it WOULD do, and does not do it"
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
open_handover
dry
check "--dry-run reports the pending resume"   [ "$(acted)" = WOULD-RESUME ]
check "...and says so in the STATE column"     [ "$(state)" = resume-due ]
check "...and typed nothing"                   [ "$(typed)" = 0 ]
check "...and wrote no prompted row"           [ "$(nprompted)" = 0 ]
run
check "and the real pass after it does resume" [ "$(acted)" = wound-resume ]

echo "== the dedup is shared with the limit path: one prompt per limit window"
# A `due` prompt already written for this window, keyed by the epoch the
# BANNER carried -- a few minutes off the quantized one, because the two are
# derived from different readings of the same reset.
reset_state
wound_row 2 "$REAL_QKEY" "$REAL_AT"
open_handover
printf '%s\t%s\t%s\n' "$SID" "$(( REAL_QKEY - 300 ))" "$REAL_AT" > "$ST/prompted"
run
check "a window already resumed by the limit path is not resumed twice" \
  [ -z "$(acted)" ]
check "...and nothing was typed"               [ "$(typed)" = 0 ]
check "...and no second prompted row appeared" [ "$(nprompted)" = 1 ]

echo
if [ "$FAILS" = 0 ]; then
  echo "$PASSES checks passed"
else
  echo "$PASSES passed, $FAILS FAILED"
fi
exit $(( FAILS > 0 ))
