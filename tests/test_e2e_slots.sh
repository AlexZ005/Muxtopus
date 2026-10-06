#!/usr/bin/env bash
# e2e-slot's slot COUNT: MUXTOPUS_E2E_SLOTS (or E2E_SLOTS for one run).
#
#   bash tests/test_e2e_slots.sh
#
# WHY. Two slots were right for the box e2e-slot was written on and wrong for
# a bigger one, and a budget that lets twelve lanes run queued most of them
# here. The count is a knob now; these cases hold what it must not break: the
# two-slot files are still slot A and B (an old e2e-slot and a new one share
# them), --exclusive holds every slot, and a full house still exits 75.
#
# Private lock files (E2E_SLOT_LOCK) and a scratch HOME: nothing here can
# take a slot a real lane is waiting for.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
ES="$REPO/e2e-slot"
T="$(mktemp -d "${TMPDIR:-/tmp}/mxslots-XXXXXX")"
trap 'rm -rf "${T:?}"' EXIT
export HOME="$T/home" XDG_CONFIG_HOME="$T/home/.config" MUXTOPUS_CONFIG="$T/home/.config/muxtopus/config"
unset E2E_SLOTS MUXTOPUS_E2E_SLOTS MUXTOPUS_HOME MUXTOPUS_DIR CLAUDE_CONFIG_DIR
mkdir -p "$HOME/.config/muxtopus"; : > "$MUXTOPUS_CONFIG"
export E2E_SLOT_LOCK="$T/lock"
FAILS=0; PASSES=0
check() { local what="$1"; shift; if "$@"; then PASSES=$((PASSES+1)); echo "  ok   $what"; else FAILS=$((FAILS+1)); echo "  FAIL $what"; fi; }

# hold N: N runs that each take a slot and sit on it; their letters in $T/got
hold() { local i; : > "$T/got"
  for i in $(seq 1 "$1"); do "$ES" -- bash -c 'echo "$E2E_SLOT" >> "$1"; sleep 4' _ "$T/got" & done
  sleep 1.5; }

echo "== the default is two: A and B, and a third waits"
hold 2
check "two runs got A and B" [ "$(sort "$T/got" | paste -sd, -)" = "A,B" ]
"$ES" --wait 1 -- true; rc=$?
check "a third, with both held, exits 75" [ "$rc" = 75 ]
check "..and the two locks are the classic files" bash -c "[ -f '$T/lock' ] && [ -f '$T/lock.b' ] && [ ! -e '$T/lock.c' ]"
wait

echo "== MUXTOPUS_E2E_SLOTS=3 in the config: three at once"
printf 'MUXTOPUS_E2E_SLOTS=3\n' > "$MUXTOPUS_CONFIG"
hold 3
check "three runs got A, B and C" [ "$(sort "$T/got" | paste -sd, -)" = "A,B,C" ]
check "..C's lock is .c" [ -f "$T/lock.c" ]
wait
check "--exclusive holds every slot" [ "$("$ES" --exclusive -- bash -c 'echo $E2E_SLOT')" = ABC ]

echo "== E2E_SLOTS in the environment beats the config for one run"
hold 1
E2E_SLOTS=1 "$ES" --wait 1 -- true; rc=$?
check "E2E_SLOTS=1 with A held: 75" [ "$rc" = 75 ]
wait
check "nonsense in the config is the old two" bash -c "printf 'MUXTOPUS_E2E_SLOTS=lots\n' > '$MUXTOPUS_CONFIG'; [ \"\$('$ES' --exclusive -- bash -c 'echo \$E2E_SLOT')\" = AB ]"

echo
if [ "$FAILS" = 0 ]; then echo "$PASSES passed"; else echo "$FAILS FAILED, $PASSES passed"; fi
[ "$FAILS" = 0 ]
