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
# PICK A MENU ROW BY NAME. tests/sandbox/README.md's rule, and this menu
# needs it more than most: it is built from the selected row, so "Mark
# answered" is the second row on one kind and absent on another, and a test
# that counts Downs silently fires whatever happens to be there.
pick() {
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    snap
    grep -qF "▸ $1" "$NOW" && return 0
    $K Down
  done
  bad "could not find the menu row: $1"
  return 1
}

# A RECORDING EDITOR. env.sh points $EDITOR at /usr/bin/true unless
# SANDBOX_EDITOR says otherwise; this one writes down which file the
# dashboard handed it, which is the only way to tell "opened for editing"
# from "opened read-only" out of a capture.
mkdir -p -- "${SB:?}/bin"
cat > "${SB:?}/bin/edstub" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "$(dirname "$0")/../edited.log"
exit 0
STUB
chmod +x -- "${SB:?}/bin/edstub"
export SANDBOX_EDITOR="${SB:?}/bin/edstub"
EDLOG="${SB:?}/edited.log"

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

echo "== enter opens: a questions file to edit, a handover READ-ONLY"
# The section above left the dashboard on the MAIN view, where enter opens a
# session's window. Back to the tab first -- a test that presses keys at the
# wrong screen proves nothing and can do something.
$K s; $K Right
: > "$EDLOG"
$K Enter
sleep 1.5
has "enter on a QUESTIONS row opens the ANSWER screen"  "answer · QUESTIONS-root-lane.md"
check "...and hands nothing to an editor" \
  bash -c '! [ -s "'"$EDLOG"'" ]'
$K Escape
$K e
sleep 1.5
check "e is what opens a questions file for editing" \
  grep -q "QUESTIONS-root-lane.md" "$EDLOG"
$K Down; $K Down
: > "$EDLOG"
$K Enter
sleep 1.5
snap
check "enter on a HANDOVER shows the file instead" \
  grep -qF "Phase 1 done. Next: phase 2." "$NOW"
check "...and never hands it to an editor -- a live lane is writing it" \
  bash -c '! grep -q STATUS "'"$EDLOG"'"'
$K q
sleep 1
has "q comes back to the tab"                "▸handovers"

echo "== answering a fork without leaving the dashboard"
"$HERE/clean.sh"
"$HERE/stop.sh" >/dev/null
"$HERE/start.sh" 40 >/dev/null
Q="${H:?}/QUESTIONS-root-lane.md"
$K s; $K Right
$K Enter
has "the screen names the file"              "answer · QUESTIONS-root-lane.md"
has "...and says where it is in it"          "fork 1 of 2 · 0 answered"
has "the fork's options are the rows"        "(a) RECOMMENDED: schedules first, handovers second."
has "...with the recommended one marked"     "← recommended"
has "...and the editor is on every screen"   "open the file in the editor  (e)"
snap
check "the recommended option is PRESELECTED" \
  grep -qE "▸ \(a\) RECOMMENDED" "$NOW"
check "and the detail panel above shows that fork in full" \
  grep -qF -- "- (b) whichever was open last, first." "$NOW"

$K Enter
has "choosing an option offers a note first" "a note, or enter for none"
"$HERE/type.sh" "because it reads left to right"
$K Enter
sleep 1.5
check "the answer is in the file, one line, inside its own fork" \
  grep -q '^\*\*Answer (user, [0-9-]*):\*\* (a) — because it reads left to right$' "$Q"
check "...and it is the SEVENTH line, not appended to the file" \
  bash -c 'sed -n 7p "'"$Q"'" | grep -q "because it reads left to right"'
has "and the screen has moved on"            "fork 2 of 2 · 1 answered"

# A TYPED ANSWER, for the fork whose options nobody wants.
$K Down; $K Down
snap
check "type an answer… is a row"             grep -qE "▸ type an answer" "$NOW"
$K Enter
has "it asks for the words"                  "your answer"
# ASCII only: type.sh sends one character per send-keys -l, and a
# multi-byte one does not survive that intact.
"$HERE/type.sh" "neither - count them in the strip"
$K Enter
sleep 1.5
check "a typed answer is written as itself" \
  grep -q "neither - count them in the strip" "$Q"
has "every fork is answered now"             "every fork in this file is answered"
has "...and it offers the marker"            "Mark the file answered"

$K Enter
sleep 2
has "marking it drops the strip count"       "handovers 3 open · 1 ?"
# root-lane's handover is already in done/, so handover.sh takes the
# answered questions file along with it -- which is §2.2's rule and is what
# tests/test_handover_sh.sh proves on its own.
check "and the ANSWERED marker is in the file, which moved with its lane" \
  grep -q "^\*\*ANSWERED" "${H:?}/done/QUESTIONS-root-lane.md"

echo "== skip, esc, and the editor, from inside the flow"
"$HERE/clean.sh"
"$HERE/stop.sh" >/dev/null
"$HERE/start.sh" 40 >/dev/null
$K s; $K Right
$K Enter
$K Down; $K Down; $K Down
snap
check "skip this fork is a row"              grep -qE "▸ skip this fork" "$NOW"
$K Enter
has "skip moves to the next fork and writes nothing" "fork 2 of 2 · 0 answered"
check "...nothing at all"                    bash -c '! grep -q "Answer (user" "'"$Q"'"'
: > "$EDLOG"
$K e
sleep 1.5
check "e from INSIDE the flow reaches the editor with that file" \
  grep -q "QUESTIONS-root-lane.md" "$EDLOG"
has "...and the flow is closed behind it"    "▸handovers"

$K Enter
$K Enter
$K Enter
sleep 1.5
check "one fork answered" grep -c "Answer (user" "$Q" >/dev/null
$K Escape
has "esc leaves the flow"                    "▸handovers"
check "and what was answered stays answered" grep -q "Answer (user" "$Q"

echo "== the lane rewrote the file underneath, and the answer still lands"
"$HERE/clean.sh"
"$HERE/stop.sh" >/dev/null
"$HERE/start.sh" 40 >/dev/null
$K s; $K Right
$K Enter
has "the flow is open on fork 1"             "fork 1 of 2 · 0 answered"
# The lane adds a fork ABOVE the one being answered, which is exactly the
# case a position-based id would get wrong.
printf '\n0. **A fork the lane added while you were reading.** (a) yes; (b) no.\n' \
  > "${SB:?}/insert.txt"
sed -i '3r '"${SB:?}/insert.txt" "$Q"
sleep 1
$K Enter
$K Enter
sleep 1.5
has "the screen says the file changed under it" "the lane rewrote the file"
check "and the answer landed in the fork it was READ from, not the new one" \
  bash -c 'awk "/Which way round should the strip read/,/^2\./" "'"$Q"'" |
           grep -q "Answer (user"'
check "...and the lane's new fork is untouched" \
  bash -c '! awk "/A fork the lane added/,/^1\./" "'"$Q"'" | grep -q "Answer (user"'

echo "== E edits a handover anyway, behind a warning that names the risk"
# launched-lane's window is @0 in the fixture tree, which IS the sandbox
# dashboard's own window, so the tree says that lane is still running.
"$HERE/clean.sh"
"$HERE/stop.sh" >/dev/null
"$HERE/start.sh" 40 >/dev/null
$K s; $K Right
$K Down; $K Down                 # onto STATUS-launched-lane
: > "$EDLOG"
$K E
has "E on a lane whose window is open asks first" "may rewrite this file while you edit"
has "...naming the lane"                     "➥launched-lane"
$K n
check "n means the editor is not opened" \
  bash -c '! grep -q STATUS "'"$EDLOG"'"'
$K E
$K y
sleep 1.5
check "y opens it"                           grep -q "STATUS-launched-lane.md" "$EDLOG"
# shadow-lane's window is not in the tree at all, so nothing can race the edit
# and a warning nobody needs is a warning nobody reads.
$K Down
: > "$EDLOG"
$K E
sleep 1.5
check "E on a lane with no live window skips the warning entirely" \
  grep -q "STATUS-shadow-lane.md" "$EDLOG"
snap
check "...and there was no confirm to answer" \
  bash -c '! grep -q "may rewrite" "'"$NOW"'"'
$K Up; $K Up; $K Up

echo "== space: the menu is built from the row under the cursor"
$K Space
has "a QUESTIONS row offers the marker"      "Mark answered"
has "...and a way to its handover"           "Show its handover"
has "...and says why it cannot tell the window" "(no live window)"
$K Escape
$K Down; $K Down
$K Space
has "a HANDOVER row offers a read-only view" "View (read-only)"
has "...the force edit"                      "Edit anyway…"
has "...its window, because that one is open" "Open its window ➥launched-lane"
has "...and Mark done"                       "Mark done…"
$K Escape

echo "== Mark done names what it releases, and releasing it is real"
# An entry held `after: launched-lane`, so there is something to release.
cat > "${SB:?}/muxhome/schedules-mxsplit/g-waits.md" <<'ENTRY'
type: work
at: reset
title: waits for the launched lane
slug: waits-for-launched
cwd: @SB@/work/repo-a
after: launched-lane
status: pending
created: 2024-01-01 09:06
launched:
---
It waits.
ENTRY
sed -i "s|@SB@|${SB:?}|g" -- "${SB:?}/muxhome/schedules-mxsplit/g-waits.md"
"$SCRIPTS/claude-watchdog.sh" --check waits-for-launched > "${SB:?}/check1.txt" 2>&1
check "the executor says that entry is HELD by the lane" \
  bash -c 'grep -q "blocked: waiting for launched-lane" "'"${SB}"'/check1.txt" &&
           grep -q "HELD by after:" "'"${SB}"'/check1.txt"'
sleep 2.5
snap
check "the tab shows the lane now holding one entry up" \
  grep -qE "launched-lane +@0 ● +1 " "$NOW"
$K Space
pick "Mark done…"
$K Enter
has "the confirm NAMES the entry it would release" \
     "releases: waits-for-launched"
$K n
has "n changes nothing"                      "cancelled"
check "...and the handover is still open"    \
  [ -f "${SB:?}/muxhome/handovers-mxsplit/STATUS-launched-lane.md" ]
# The MENU is still open behind the answered confirm -- confirm_key clears
# the confirm, not the menu -- so space here would close it, not reopen it.
$K Escape
$K Space
pick "Mark done…"
$K Enter
$K y
sleep 2.5
check "y moves the file into done/" \
  [ -f "${SB:?}/muxhome/handovers-mxsplit/done/STATUS-launched-lane.md" ]
check "...and out of the open folder" \
  [ ! -f "${SB:?}/muxhome/handovers-mxsplit/STATUS-launched-lane.md" ]
"$SCRIPTS/claude-watchdog.sh" --check waits-for-launched > "${SB:?}/check2.txt" 2>&1
check "and the EXECUTOR now says that entry is released" \
  grep -q "after launched-lane: finished" "${SB:?}/check2.txt"
rm -f -- "${SB:?}/muxhome/schedules-mxsplit/g-waits.md"

echo "== Mark answered flips the row and the strip count with it"
"$HERE/clean.sh"
"$HERE/stop.sh" >/dev/null
"$HERE/start.sh" 40 >/dev/null
# A questions file for a lane whose handover is still OPEN, written here
# rather than committed as a fixture: the committed set is what the goldens
# were blessed against, and one more row would mean re-blessing fifty screens
# to prove something about a menu. handover.sh leaves this one where it is --
# it moves an answered file only when its lane is already finished, which is
# the root-lane case and is covered in tests/test_handover_sh.sh.
cp -- "$FIX/muxhome/handovers-mxsplit/QUESTIONS-root-lane.md" \
      "${H:?}/QUESTIONS-stranded-lane.md"
$K s; $K Right
$K f                            # finished rows shown, or an answered one hides
sleep 2.5
has "three files are asking to begin with"   "· 3 ?"
snap
check "the new one is the top row"           grep -qE "▸ +\? ask .* stranded-lane" "$NOW"
$K Space
pick "Mark answered"
$K Enter
sleep 2
has "the row says it is answered now"        "? done"
has "...and the strip has one fewer"         "· 2 ?"
check "the marker is in the file" \
  grep -q "ANSWERED" "${H:?}/QUESTIONS-stranded-lane.md"
check "...and the file has NOT moved: its lane is still open" \
  [ -f "${H:?}/QUESTIONS-stranded-lane.md" ]
$K Space
pick "Mark unanswered"
$K Enter
sleep 2
has "Mark unanswered puts it back"           "· 3 ?"
check "...and takes the marker out again" \
  bash -c '! grep -q ANSWERED "'"${H}"'/QUESTIONS-stranded-lane.md"'
rm -f -- "${H:?}/QUESTIONS-stranded-lane.md"
$K f

echo "== Tell types one line into the lane's own pane, never automatically"
"$HERE/clean.sh"
"$HERE/stop.sh" >/dev/null
"$HERE/start.sh" 40 >/dev/null
WID2="$(tmux new-window -d -t "${SANDBOX_SESSION:?}" -P -F '#{window_id}' 'cat > '"${SB:?}"'/heard.txt')"
PID2="$(tmux list-panes -a -F '#{window_id} #{pane_id}' | awk -v w="$WID2" '$1==w{print $2}')"
printf 'root-lane\t\t%s\t%s\t1735700000\ta-pending.md\n' "$WID2" "$PID2" >> "$WD/tree.tsv"
sleep 2.5
$K s; $K Right
$K Space
snap
check "the menu now offers to tell that window" \
  grep -qF "Tell ➥root-lane its answers are in" "$NOW"
pick "Tell ➥root-lane its answers are in"
$K Enter
has "and asks before touching a live pane"   "Type that into ➥root-lane"
$K n
check "n types nothing" bash -c '[ ! -s "'"${SB}"'/heard.txt" ]'
# The menu is still open behind the answered confirm; space would close it.
$K Escape
$K Space
pick "Tell ➥root-lane its answers are in"
$K Enter
$K y
sleep 2
tmux kill-window -t "$WID2" 2>/dev/null
sleep 0.5
check "y types the sentence, naming the file to read" \
  grep -q "Your questions are answered in .*QUESTIONS-root-lane.md" "${SB:?}/heard.txt"
cp -- "$FIX/state/claude-watchdog-mxsplit/tree.tsv" "$WD/tree.tsv"

echo "== the two filters, and they survive an R"
"$HERE/clean.sh"
"$HERE/stop.sh" >/dev/null
"$HERE/start.sh" 40 >/dev/null
CONF="${SB:?}/config/muxtopus/profiles/mxsplit.dashboard.conf"
$K s; $K Right
has "finished rows are hidden to begin with"  "done hidden: 4"
$K f
has "f says what it did"                      "finished rows shown"
has "...and the finished handovers are there" "done       1d      root-lane"
has "...answered question files too"          "? done"
has "...and a stamped earlier run says which" "old-lane ·earlier"
check "the setting is on disk, not just on screen" \
  grep -q '^DASHBOARD_HANDOVERS_DONE="on"' "$CONF"
# R RE-EXECS THE DASHBOARD. That is the whole reason these two are on disk:
# every in-memory toggle dies here, and a done list that came back on every
# R would be switched off once and for good.
$K R
sleep 3
$K s; $K Right
has "and it is still on after R re-execs the whole dashboard" "done       1d      root-lane"
$K f
has "f puts it back"                          "finished rows hidden"
check "...on disk as well" grep -q '^DASHBOARD_HANDOVERS_DONE="off"' "$CONF"

$K a
has "a hides the question rows"               "question rows hidden"
snap
check "...every one of them" bash -c '! grep -q "? ask" "'"$NOW"'"'
has "...and says how many it is hiding"       "questions hidden: 3"
check "the setting is on disk" \
  grep -q '^DASHBOARD_HANDOVERS_QUESTIONS="off"' "$CONF"
has "the strip still carries the count the filter hides" "· 2 ?"
$K a
has "a brings them back"                      "question rows shown"

echo "== both filters are rows in the Settings menu, with no extra code"
$K Escape
$K Escape
$K Enter
has "the esc menu opens Settings"             "Menu layout"
has "the done filter is a row"                "Handovers: show finished rows"
has "and so is the question filter"           "Handovers: show question rows"
$K Escape; $K Escape

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

echo "== the main view says it in one character"
"$HERE/clean.sh"
"$HERE/stop.sh" >/dev/null
"$HERE/start.sh" 40 >/dev/null
has "the lane with an unanswered file carries a ?" "➥root-lane ?"
snapc
check "...in yellow" \
  bash -c 'grep -a "root-lane" "'"$COL"'" | grep -q "38;5;179m?"'
has "and the key line says how many files are waiting" "· 2 ?"
snap
check "a lane with nothing asked of it carries nothing" \
  bash -c '! grep -q "kid-lane ?" "'"$NOW"'"'
# ANSWERED, from outside the dashboard: the mark is a fact about the folder,
# not about this process, so the frame has to pick it up on its own.
"$SCRIPTS/handover.sh" answered root-lane >/dev/null 2>&1
sleep 7                          # muxhandovers.asking re-globs every 5s
snap
check "marking it answered takes the ? off the row" \
  bash -c '! grep -q "root-lane ?" "'"$NOW"'"'
has "...and the count with it"               "· 1 ?"
"$HERE/clean.sh"

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
