#!/usr/bin/env bash
# THE HANDOVERS TAB, driven: what the strip says, what the rows say, what the
# arrows do, and what the keys that are NOT this tab's do instead.
#
#   tests/sandbox/handovers.sh
#
# Why this is not more goldens: a golden is a whole screen compared byte for
# byte, and most of what is proved here is a fact about ONE ROW -- its state,
# its window, how many entries it holds up -- which a reader of a 40-line
# capture cannot see is being tested. goldens.sh still photographs the screen
# this tab shares with the schedules; this file is what says why each thing on
# that photograph is there.
#
# It runs on the sandbox's own tmux server, its own fake machine and its own
# fixture handovers folder. It never touches ~/.code/handovers.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env.sh"

K="$HERE/k.sh"; C="$HERE/cap.sh"
FIX="${SCRIPTS:?}/tests/fixtures/dashboard"
H="${SB:?}/muxhome/handovers-mxsplit"
WD="${SB:?}/state/claude-watchdog-mxsplit"
NOW="${SB:?}/now.txt"; COL="${SB:?}/now-colour.txt"
pass=0; fail=0
ok()  { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }
check() { if "${@:2}"; then ok "$1"; else bad "$1"; fi; }

# A CAPTURE TAKEN MID-REPAINT IS MISSING A LINE, and that is not a theory:
# Live redraws the whole screen every 2s and capture-pane does not wait for
# it to finish, so one read came back without the CURSOR'S row -- the first
# one -- while the next, 50ms later, had it. Two identical reads in a row is
# a frame nobody is writing to. Everything here reads through this.
scap() {                        # scap [-e]  -- a settled frame, on stdout
  local a b i
  a="$("$C" "$@")"
  for i in 1 2 3 4 5 6 7 8; do
    sleep 0.15
    b="$("$C" "$@")"
    [ "$a" = "$b" ] && break
    a="$b"
  done
  printf '%s\n' "$a"
}
# THE FRAME UNDER TEST, in a file: every check greps $NOW, so consecutive
# assertions are about the same screen and the quoting stays readable.
snap()  { scap > "$NOW"; }
snapc() { scap -e > "$COL"; }
has()   { snap; check "$1" grep -qF -- "$2" "$NOW"; }

"$HERE/clean.sh"
"$HERE/start.sh" 40 >/dev/null

echo "== the strip carries both tabs and both counts, from either side"
$K s
has "the schedules tab is the one s opens"   "▸schedules 6"
has "...and the strip names the other one"   "handovers 3 open · 2 ?"
has "...and says how to move"                "←→ tab"
$K Right
has "→ lands on the handovers tab"           "▸handovers 3 open · 2 ?"
has "...and the schedules count is still legible from here" "schedules 6"
$K Left
has "← comes back"                           "▸schedules 6"
has "...to the schedules table"              "a pending plan"
$K Right

echo "== the order is what is OWED, first"
snap
grep -E '^│ +(▸ +)?(\? ask|open|done) ' "$NOW" > "${SB:?}/rows.txt"
check "five rows are drawn under the default filters" \
  bash -c 'test "$(wc -l < "'"${SB}"'/rows.txt")" = 5'
check "the first row is an unanswered question" \
  bash -c 'sed -n 1p "'"${SB}"'/rows.txt" | grep -q "? ask"'
check "the question rows are above every handover" \
  bash -c 'f="'"${SB}"'/rows.txt";
           n=$(grep -n "? ask" "$f" | tail -1 | cut -d: -f1);
           m=$(grep -n " open " "$f" | tail -1 | cut -d: -f1);
           [ "$n" -lt "$m" ]'
# sed, not `grep -n | head`: this file runs under `set -o pipefail`, and a
# `grep -q` that exits on its first match SIGPIPEs the head above it, which
# turns a PASSING assertion into 141.
check "newest first inside a state (2h above 8h)" \
  bash -c 'f="'"${SB}"'/rows.txt";
           sed -n 1p "$f" | grep -q "2h .*root-lane" &&
           sed -n 2p "$f" | grep -q "8h .*launched-lane"'
has "the cursor starts on the top row"       "▸     ? ask      2h"
# Not a literal age: clean.sh stamps the fixtures relative to NOW, so "12m"
# is "13m" a minute into the run. That every row HAS one is the claim.
check "every row carries the age of its file" \
  bash -c 'test "$(grep -cE " [0-9]+[smhd] +" "'"${SB}"'/rows.txt")" = 5'
has "a legacy question file says which folder it came from" "·legacy"
has "what a filter hides is counted, never silent" "done hidden: 4"

echo "== the states"
has "an unanswered questions file"           "? ask"
has "the both-files lane is flagged"         "open ⚠     3h      shadow-lane"
snapc
check "...in yellow, because after: already sees it as done" \
  bash -c 'grep -a shadow-lane "'"$COL"'" | grep -q "38;5;179"'
check "the stranded lane is flagged in RED instead" \
  bash -c 'grep -a stranded-lane "'"$COL"'" | grep -q "38;5;174"'
$K Down; $K Down; $K Down
snap
check "and the detail says what the yellow one MEANS, in words" \
  grep -qF "done/STATUS-shadow-lane.md from an earlier run" "$NOW"
$K Up; $K Up; $K Up

echo "== HOLDS is the after: interaction, seen from the other side"
# b-blocked.md is `after: root-lane` and pending, so root-lane -- and only
# root-lane -- is holding something up. The entry knew; the lane never did.
snap
check "the row of the lane a pending entry waits for carries a count" \
  grep -qE "root-lane +exited +1 " "$NOW"
check "and the detail names the entry, not just the number" \
  grep -qF "holds: blocked-behind-a-lane (after:)" "$NOW"
$K Down; $K Down
snap
check "a lane nothing is waiting for holds nothing" \
  bash -c '! grep -q "holds:" "'"$NOW"'"'
$K Up; $K Up

echo "== WINDOW follows a real tmux window"
# The fixture tree points at window ids the sandbox server does not have, so
# make a REAL one and point the tree at it: ● has to mean "this window exists
# NOW", and only a window that can then be killed proves that it does.
WID="$(tmux new-window -d -t "${SANDBOX_SESSION:?}" -P -F '#{window_id}' 'sleep 600')"
printf 'shadow-lane\t\t%s\t%%99\t1735700000\tb-blocked.md\n' "$WID" >> "$WD/tree.tsv"
sleep 2.5
snap
check "a live window is drawn with its id and a dot" \
  grep -qE "shadow-lane +$WID ●" "$NOW"
tmux kill-window -t "$WID"
sleep 2.5
snap
check "and it reads exited once that window is gone" \
  grep -qE "shadow-lane +exited" "$NOW"
cp -- "$FIX/state/claude-watchdog-mxsplit/tree.tsv" "$WD/tree.tsv"
sleep 2.5

echo "== the keys that are not this tab's say so"
for k in c o l d; do
  $K "$k"
  has "$k refuses here rather than acting on a row nobody can see" \
      "$k: schedules tab only"
done
$K r
has "r re-reads the folder"                  "handovers re-read"
$K Escape
has "esc leaves the tab for the main view"   "➥root-lane"
$K s
has "s always opens on the SCHEDULES tab"    "▸schedules 6"
$K Right
has "...and the handovers are one arrow away" "▸handovers"
$K s
has "s from the handovers tab leaves too"    "➥root-lane"

echo "== the viewport: more rows than the screen has, and a bottom border"
# THIRTY MORE ROWS. done rows are hidden by default and the filter that shows
# them is phase 4, so what overflows the screen here is unanswered question
# files -- which the default filter shows, and which are the kind of row a
# person would actually come to have too many of.
for i in $(seq 10 39); do
  printf '# QUESTIONS — bulk-%s\n\n1. **A fork.** (a) yes; (b) no.\n' "$i" \
    > "${H:?}/QUESTIONS-bulk-$i.md"
  touch -d "$i hours ago" -- "${H:?}/QUESTIONS-bulk-$i.md"
done
$K s; $K Right
sleep 2.5
has "the strip counts every one of them"     "handovers 3 open · 32 ?"
"$HERE/stop.sh" >/dev/null
"$HERE/start.sh" 24 >/dev/null
$K s; $K Right
snap
check "on 24 rows the table scrolls rather than losing its border" \
  grep -qE "▼ [0-9]+ more" "$NOW"
check "and the bottom border of the last panel is still drawn" \
  bash -c 'tail -3 "'"$NOW"'" | grep -q "╰.*╯"'
check "the footer is still the last line" \
  bash -c 'grep -v "^$" "'"$NOW"'" | tail -1 | grep -q "s/esc back"'
for i in $(seq 1 34); do PAUSE=0.05 $K Down; done
sleep 1
snap
check "the cursor reaches the bottom of the list" \
  grep -qE "▲ [0-9]+ more" "$NOW"
check "...and the frame is still whole down there" \
  bash -c 'grep -v "^$" "'"$NOW"'" | tail -1 | grep -q "s/esc back"'
rm -f -- "${H:?}"/QUESTIONS-bulk-*.md
"$HERE/stop.sh" >/dev/null

echo "== the WHY line on the schedules tab is unchanged"
# handover_state is now a call to muxhandovers.lane_state, whose order is the
# watchdog's. The one row it draws on the other tab must say what it always said.
"$HERE/clean.sh"
"$HERE/start.sh" 40 >/dev/null
$K s
$K Down; $K Down; $K Down
snap
check "the launched entry still reports its handover" \
  grep -qE "handover open, .* ago" "$NOW"
"$HERE/stop.sh" >/dev/null

echo
if [ "$fail" = 0 ]; then echo "$pass checks: the handovers tab"; else
  echo "$pass passed, $fail FAILED"; fi
exit $((fail > 0))
