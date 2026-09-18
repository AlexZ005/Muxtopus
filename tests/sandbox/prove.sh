#!/usr/bin/env bash
# THE SMALL-TERMINAL PROOF: every screen fits, at 24, 40 and 58 rows and at
# 160, 100, 80, 60 and 40 columns (40 is where nine tabs must SCROLL), and every tab is reachable at each of them.
#
#   prove.sh            run it; non-zero if anything does not fit
#
# It drives a COPY of the checkout with tests/fixtures/many_tabs.py dropped
# into dashboard/views/, so `s` has NINE tabs and the strip has to shorten
# and then scroll -- the real dashboard has two, which would prove nothing
# about the width. Nothing here writes to the checkout you are in.
#
# Each capture goes through assert_fit.py (no more lines than rows, no line
# wider than cols, the footer on screen, every box closed). Reachability is
# asserted by what each tab SAYS it is -- its body or its footer -- never by
# the strip, which is the thing under test:
#
#   → nine times from schedules visits all nine tabs and comes back;
#   ← once from schedules lands on the LAST tab, the one most scrolled off;
#   with two tabs hidden (one of them among the locked six), → visits the
#     seven shown and the strip's subtitle counts the two.
#
# Captures are kept in $SB/prove/<rows>x<cols>-<screen>.txt to be looked at.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env.sh"

COPY="${SB:?}/prove-checkout"
OUT="${SB:?}/prove"
pass=0; fail=0
ok()  { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }

rm -rf -- "${COPY:?}" "${OUT:?}"
mkdir -p -- "${COPY:?}" "${OUT:?}"
tar -C "${SCRIPTS:?}" --exclude=.git --exclude=.venv --exclude=__pycache__ \
    --exclude=tests/goldens -cf - . | tar -x -C "${COPY:?}"
ln -sfn "${SCRIPTS:?}/.venv" "${COPY:?}/.venv"
cp -- "${SCRIPTS:?}/tests/fixtures/many_tabs.py" "${COPY:?}/dashboard/views/zz_many_tabs.py"
export SCRIPTS="${COPY:?}"
K="$HERE/k.sh"; C="$HERE/cap.sh"
CONF="${SB:?}/config/muxtopus/profiles/mxsplit.dashboard.conf"

fit() {   # fit <name> <rows> <cols> <footer> [must...]
  local name="$1" r="$2" c="$3"; shift 3
  "$C" > "${OUT:?}/$name.txt"
  if python3 "$HERE/assert_fit.py" "${OUT:?}/$name.txt" "$r" "$c" "$@"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
  fi
}

# Which tab is on screen, from the tab's OWN words.
which_tab() {
  local cap; cap="$("$C" | tr '\n' ' ' | tr -s ' ')"
  if grep -q "this is tab " <<<"$cap"; then
    grep -o "this is tab [a-z]*" <<<"$cap" | head -1 | cut -d' ' -f4
  elif grep -q "E force-edit" <<<"$cap"; then echo handovers
  elif grep -q "o options" <<<"$cap"; then echo sched
  else echo "?"
  fi
}

ALL="sched handovers deployments alerts pages backups certificates queues workers"

for H in 24 40 58; do
  for W in 160 100 80 60 40; do
    G="${H}x${W}"
    echo "== $G"
    "$HERE/clean.sh"
    COLS="$W" "$HERE/start.sh" "$H" >/dev/null
    fit "$G-main" "$H" "$W" " q quit" "claude [mxsplit]"
    # The cursor to the LAST session: the claude table must scroll to it
    # and still end in its bottom border above the footer.
    for i in 1 2 3 4 5; do PAUSE=0.1 $K Down; done
    sleep 0.4
    # The cursor's row is on screen, wherever the table had to scroll to
    # put it there (at 24 rows it scrolls; at 24x160 the deck header steps
    # aside and all six fit, so a ▲ is not the thing to ask for).
    fit "$G-main-last" "$H" "$W" " q quit" "▸✔"
    $K Space
    # The menu's hint line is its footer; "↑↓ pick" is its start, which
    # survives the ellipsis a 40-column menu puts on "esc close".
    fit "$G-session-menu" "$H" "$W" "↑↓ pick"
    $K Escape
    $K Escape
    fit "$G-mux-menu" "$H" "$W" "↑↓ pick" "Settings"
    $K Escape
    $K s
    fit "$G-sched" "$H" "$W" " ↑↓ pick" "←→ tab"
    seen=""
    for i in 1 2 3 4 5 6 7 8 9; do
      t="$(which_tab)"
      seen="$seen $t"
      fit "$G-tab$i-$t" "$H" "$W" "q quit" "←→ tab"
      $K Right
    done
    got="$(tr ' ' '\n' <<<"$seen" | sed '/^$/d' | sort | tr '\n' ' ')"
    want="$(tr ' ' '\n' <<<"$ALL" | sort | tr '\n' ' ')"
    if [ "$got" = "$want" ] && [ "$(which_tab)" = sched ]; then
      ok "$G: → visits all nine tabs and comes back to schedules"
    else
      bad "$G: → visited [$seen], now on $(which_tab)"
    fi
    $K Left
    if [ "$(which_tab)" = workers ]; then
      ok "$G: ← from schedules lands on the last tab, however far off the strip"
    else
      bad "$G: ← from schedules landed on $(which_tab)"
    fi
    $K Escape
    $K i
    fit "$G-insights" "$H" "$W" "i/esc back"
    $K Escape
    "$HERE/stop.sh" >/dev/null 2>&1
  done
done

echo "== two tabs hidden, one of them locked (24x80)"
"$HERE/clean.sh"
printf 'DASHBOARD_TABS_HIDDEN="handovers,alerts"\n' >> "$CONF"
COLS=80 "$HERE/start.sh" 24 >/dev/null
$K s
fit "hidden-sched" 24 80 " ↑↓ pick" "2 hidden"
seen=""
for i in 1 2 3 4 5 6 7; do seen="$seen $(which_tab)"; $K Right; done
if ! grep -qw "handovers\|alerts" <<<"$seen" && [ "$(which_tab)" = sched ] \
   && [ "$(tr ' ' '\n' <<<"$seen" | sed '/^$/d' | sort -u | wc -l)" = 7 ]; then
  ok "→ visits the seven shown, never a hidden one, and comes back"
else
  bad "→ with two hidden visited [$seen]"
fi
"$HERE/stop.sh" >/dev/null 2>&1
"$HERE/clean.sh"

echo
echo "prove: $pass passed, $fail failed  (captures in $OUT)"
[ "$fail" = 0 ]
