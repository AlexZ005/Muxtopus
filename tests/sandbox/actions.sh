#!/usr/bin/env bash
# THE ROWS THAT WRITE SOMETHING, fired -- not photographed.
#
# The goldens prove what the dashboard DRAWS. They open every menu, but a
# menu row is a picture until somebody presses enter on it, and the rows in
# this dashboard close windows, write schedule entries and queue directives.
# The split found two NameErrors on exactly those paths (see
# tests/test_names.py) and the 148 captures were green through both.
#
# So this fires them, in the sandbox, and looks at the files afterwards.
# Nothing here touches anything outside "${SB:?}".
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env.sh"

K="$HERE/k.sh"; C="$HERE/cap.sh"; T="$HERE/type.sh"
S="${SB:?}/muxhome/schedules-mxsplit"
WD="${SB:?}/state/claude-watchdog-mxsplit"
pass=0; fail=0

ok()  { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }
check() { if "${@:2}"; then ok "$1"; else bad "$1"; fi; }
notice() { "$C" | grep -qF -- "$1"; }

# NAVIGATE BY LOOKING, not by counting. The mover skips separators and
# headings, so "eight Downs" is a number that depends on how many of those a
# menu happens to have -- which is exactly the sort of thing a later phase is
# allowed to change without changing behaviour. This presses Down until the
# CURSOR row says what it should, and fails saying what it found instead.
down_to() {
  local want="$1" i
  for i in $(seq 1 25); do
    if "$C" | grep -q "▸ .*$want"; then ok "cursor is on: $want"; return 0; fi
    PAUSE=0.15 $K Down
  done
  bad "never reached the row: $want"
  "$C" | grep -o "▸ .\{0,60\}" | tail -1
  return 1
}

"$HERE/clean.sh"

echo "== the session menu: Schedule ➥resume of the cursor's window"
"$HERE/start.sh" 58 >/dev/null
$K Space                      # the session menu over ➥root-lane
down_to "Schedule ➥resume of ➥root-lane"
$K Enter
sleep 0.6
check "it wrote the entry"            test -f "${S:?}/resume-root-lane.md"
check "..with the lane's slug pinned" grep -q "^slug: resume-root-lane$" "${S:?}/resume-root-lane.md"
check "..the window it resumes"       grep -q "^window: ➥root-lane$" "${S:?}/resume-root-lane.md"
check "..the cursor's cwd"            grep -q "^cwd: ${SB:?}/work/repo-a$" "${S:?}/resume-root-lane.md"
check "..and the STATUS path the wind-down asks for (HANDOVERS_DIR)" \
  grep -q "STATUS-root-lane.md" "${S:?}/resume-root-lane.md"
check "the notice names it"           notice "scheduled ➥resume-root-lane"

echo "== the session menu: Wind down now"
$K Space
down_to "Wind down ➥root-lane now"
$K Enter
sleep 0.6
check "a directive was queued" test -f "${WD:?}/directives/aaaa1111"
check "..naming the handover file it must write" \
  grep -q "STATUS-root-lane.md" "${WD:?}/directives/aaaa1111"

echo "== the session menu: the per-window opt-out (space on the first row)"
$K Space
$K Enter
sleep 0.6
check "the session was opted out of restarts" grep -qx "aaaa1111" "${WD:?}/optout"
$K Space
$K Enter
sleep 0.6
check "..and back in"  bash -c '! grep -qx aaaa1111 "'"${WD:?}"'/optout"'

echo "== the session menu: Rename, on a pane that is not there"
$K Space
down_to "Rename ➥root-lane"
$K Enter
$T "renamed-lane"
$K Enter
sleep 0.6
check "a rename onto a dead pane is reported, not raised" \
  bash -c '"'"$C"'" | grep -qE "renamed to renamed-lane|rename failed"'
"$HERE/stop.sh"

echo "== the schedule view: Duplicate, Launch now, Delete"
"$HERE/clean.sh"
"$HERE/start.sh" 58 >/dev/null
$K s
$K Space
down_to "Duplicate as a new pending entry"
$K Enter
sleep 0.8
check "the copy exists"  test -f "${S:?}/a-pending-copy.md"
check "..is pending"     grep -q "^status: pending$" "${S:?}/a-pending-copy.md"
check "..says -copy"     grep -q -- "-copy$" "${S:?}/a-pending-copy.md"
check "..and the body is byte for byte" \
  bash -c 'diff <(sed -n "/^---$/,\$p" "'"${S:?}"'/a-pending.md") \
                <(sed -n "/^---$/,\$p" "'"${S:?}"'/a-pending-copy.md") >/dev/null'

# The copy sorts ABOVE its original ('-' < '.'), so the cursor is on it.
$K Space
down_to "Launch now"
$K Enter
sleep 0.6
check "launch now set at: to a wall-clock minute" \
  grep -qE "^at: 20[0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]$" "${S:?}/a-pending-copy.md"

$K d
sleep 0.4
check "the delete confirm names the file" grep -q "Delete a-pending-copy.md?" <("$C")
$K y
sleep 0.6
check "y deletes it" bash -c '! test -f "'"${S:?}"'/a-pending-copy.md"'
check "and nothing else went with it" test -f "${S:?}/a-pending.md"

echo "== the options table, saved for real"
$K o
sleep 0.4
$K Space                      # tick "questions go to a file"
down_to "save  what is ticked"
$K Enter
sleep 0.8
check "the entry still parses as one" grep -q "^type: plan$" "${S:?}/a-pending.md"
check "the notice counted the options" notice "option(s)"
"$HERE/stop.sh"

echo
if [ "$fail" = 0 ]; then echo "$pass actions fired, all as expected"; else
  echo "$pass passed, $fail FAILED"; fi
exit $((fail > 0))
