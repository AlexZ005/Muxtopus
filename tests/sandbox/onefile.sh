#!/usr/bin/env bash
# A VIEW IS ONE NEW FILE. The claim the whole split was for, fired.
#
# Copies the checkout, drops tests/fixtures/demo_view.py into its
# dashboard/views/, starts the dashboard on THAT copy, and checks that every
# registry carried it -- a tab of `s` with its own label, ←→ between them, a
# row in the esc menu opening a menu of its own, a badge on every session, a
# note in the footer, a section of `?`, a setting in Settings and a state in
# the table -- while `git status` in the copy names ONE added file and no
# modified one.
#
# Then it drops a views/broken.py that raises on import and checks that the
# dashboard says so and keeps working, because "one lane's bad commit must
# not take down the screen the others are tested in" is a promise, and an
# untested promise is a wish.
#
# THE COPY IS THE POINT: nothing here writes to the checkout you are in.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env.sh"

COPY="${SB:?}/checkout"
pass=0; fail=0
ok()  { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }
check() { if "${@:2}"; then ok "$1"; else bad "$1"; fi; }

echo "== a copy of the checkout, with one file added"
rm -rf -- "${COPY:?}"
mkdir -p -- "${COPY:?}"
# The WORKING TREE, not HEAD: this has to test the code as it stands, which
# during a phase is exactly the code that is not committed yet.
tar -C "${SCRIPTS:?}" --exclude=.git --exclude=.venv --exclude=__pycache__ \
    --exclude=tests/goldens -cf - . | tar -x -C "${COPY:?}"
# The venv is not in git and deck-status.sh needs it to prefer this renderer.
ln -sfn "${SCRIPTS:?}/.venv" "${COPY:?}/.venv"
git -C "${COPY:?}" init -q
git -C "${COPY:?}" add -A && git -C "${COPY:?}" -c user.email=t@t -c user.name=t commit -qm base

cp -- "${SCRIPTS:?}/tests/fixtures/demo_view.py" "${COPY:?}/dashboard/views/demo.py"
changed="$(git -C "${COPY:?}" status --porcelain)"
check "git status names exactly one file" \
  [ "$(printf '%s\n' "$changed" | wc -l)" = 1 ]
check "...and it is the one that was added" \
  [ "$changed" = "?? dashboard/views/demo.py" ]

# Drive the copy, not this checkout.
export SCRIPTS="${COPY:?}"
K="$HERE/k.sh"; C="$HERE/cap.sh"
"$HERE/clean.sh"
"$HERE/start.sh" 58 >/dev/null

echo "== it loaded, and the seam carried every part of it"
# TWO badges now: dashboard/views/handovers.py puts a yellow ? on a lane
# with an unanswered QUESTIONS file, at order=10, and the demo's ◆ follows
# it. That two modules can both write on one row, in a fixed order neither
# of them chose, is the registry working -- so the check names both rather
# than pretending the row is the demo's alone.
check "a badge is on every session row" grep -q "root-lane ? ◆" <("$C")
check "a hint is on the footer"         grep -q "· demo loaded" <("$C")
$K Escape
check "its row is in the esc menu"      grep -q "Demo ▸  a row this file added" <("$C")
check "...under Settings, where order=15 puts it" \
  bash -c '"'"$C"'" | grep -A1 "Settings ▸" | grep -q "Demo ▸"'
$K Down
$K Enter
check "and it opens a menu of its own"  grep -q "a demo menu row" <("$C")
$K Escape
check "esc_to takes it back to the esc menu" grep -q "Disconnect" <("$C")
$K Escape

echo "== it is a TAB of s, with its own label, and ←→ cycles"
$K s
check "the strip shows both tabs, with the count"  \
  grep -q "▸schedules 6 │ demo 0" <("$C")
check "...and says how to move"      grep -q "←→ tab" <("$C")
$K Right
check "→ lands on the demo tab"      grep -q "the demo view is a tab of s" <("$C")
$K x
$K x
check "its own key works"            grep -q "x pressed 2 time(s)" <("$C")
check "and its tab LABEL is live"    grep -q "▸demo 2" <("$C")
$K Left
check "← comes back to the schedules" grep -q "a pending plan" <("$C")
$K Escape

echo "== ? and Settings"
$K "?"
check "its help section is in ?"     grep -q "THE DEMO TAB" <("$C")
check "...in the order it asked for, after LANE STATE" \
  bash -c '"'"$C"'" | grep -n "LANE STATE\|THE DEMO TAB" | tail -2 | head -1 | grep -q "LANE STATE"'
$K q
$K Escape
$K Enter
check "its setting is in Settings"   grep -q "Demo: stranded after (minutes)" <("$C")
$K Escape; $K Escape
"$HERE/stop.sh"

echo "== a module that raises on import is skipped, loudly"
printf 'raise RuntimeError("this module is deliberately broken")\n' \
  > "${COPY:?}/dashboard/views/broken.py"
"$HERE/start.sh" 58 >/dev/null
check "the notice names the module and the reason" \
  grep -q "views.broken failed to load: this module is deliberately broken" <("$C")
check "the main view still drew"     grep -q "root-lane" <("$C")
check "...with the demo badge still on it" grep -q "root-lane ? ◆" <("$C")
$K s
$K Right
check "and the demo tab still works" grep -q "the demo view is a tab of s" <("$C")
"$HERE/stop.sh"

echo
if [ "$fail" = 0 ]; then echo "$pass checks: a view is one new file"; else
  echo "$pass passed, $fail FAILED"; fi
exit $((fail > 0))
