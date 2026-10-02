#!/usr/bin/env bash
# THE MEMORY GUARD ON SCREEN: the red badge, the red `held` row and its why
# line, and that each one goes away when it should.
#
#   tests/sandbox/memguard.sh            assert, and compare with tests/goldens-memguard/
#   tests/sandbox/memguard.sh --bless    rewrite those goldens
#
# What the WATCHDOG decides (when to hold, when to let go) is
# tests/test_mem_guard.sh's subject. This file proves the dashboard draws the
# daemon's verdict: the `memory` file it publishes and a `held` row in
# sched-why.tsv, both written here into the fake machine. The goldens are
# their own folder, not tests/goldens/, because goldens.sh --bless deletes and
# rewrites that one whole. The 148 screens there are taken with no memory
# file, so they must not change; this pair shows the guard tripped.
#
# Sandbox only: its own tmux server (-L mxsplit via bin/tmux), its own HOME
# and state dir. Nothing here reads the real watchdog's files.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env.sh"

K="$HERE/k.sh"; C="$HERE/cap.sh"
GOLD="${SCRIPTS:?}/tests/goldens-memguard"
CAPS="${SB:?}/caps-memguard"
WD="${SB:?}/state/claude-watchdog-${SANDBOX_ACCOUNT:?}"
# dashboard/core.py RED, #d47f7f: as truecolour, or as the 256-colour index
# tmux hands back when the sandbox terminal does not advertise RGB.
RED_SGR='(38;2;212;127;127|38;5;174)'
pass=0; fail=0
ok()  { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }
check() { if "${@:2}"; then ok "$1"; else bad "$1"; fi; }

# A settled frame: two identical reads in a row (handovers.sh says why).
scap() {
  local a b i
  a="$("$C" "$@")"
  for i in 1 2 3 4 5 6 7 8; do
    sleep 0.15; b="$("$C" "$@")"
    [ "$a" = "$b" ] && break
    a="$b"
  done
  printf '%s\n' "$a"
}
held_file() {   # held_file STATE [age-seconds]
  printf '%s\t3145728\t12\t%s\t%s\t%s\n' "$(( $(date +%s) - ${2:-0} ))" "$1" "$(date +%s)" \
    "3.0 GB available, under WATCHDOG_MEM_MIN_GB=4" > "${WD:?}/memory"
}

"$HERE/setup.sh" >/dev/null
rm -rf -- "${CAPS:?}"; mkdir -p -- "${CAPS:?}"
# The due entry becomes held, in the daemon's own words.
sed -i "s|^f-work.md\tdue\t.*|f-work.md\theld\theld: memory -- 3.0 GB available, under WATCHDOG_MEM_MIN_GB=4; launches by itself once memory recovers (WATCHDOG_MEM_GUARD=off to stop holding)\t1735800000|" \
  "${WD:?}/sched-why.tsv"
held_file low
# Rewritten while the dashboard runs, like the daemon does every pass, so a
# slow route never sees the reading go stale.
( while :; do held_file low; sleep 5; done ) & KEEP=$!
trap 'kill "$KEEP" 2>/dev/null; "$HERE/stop.sh" >/dev/null 2>&1' EXIT

echo "== the main view: the badge on the deck panel"
"$HERE/start.sh" 40 >/dev/null
scap > "${CAPS:?}/memguard-main.txt"
check "the deck border carries the badge" grep -q "deck · MEMORY LOW · new windows held" "${CAPS:?}/memguard-main.txt"
check "..in red" grep -qE "${RED_SGR}m· MEMORY LOW" <<<"$(scap -e)"
check "..and the claude title does not repeat it" bash -c '! grep -q "memory low: new windows held" "$1"' _ "${CAPS:?}/memguard-main.txt"

echo "== the schedules tab: the held row and its sentence"
"$K" s
for i in 1 2 3 4 5 6 7 8; do
  scap | grep -q "▸ *held" && break
  "$K" Down
done
scap > "${CAPS:?}/memguard-sched.txt"
check "the due entry reads held" grep -q "▸ *held *work" "${CAPS:?}/memguard-sched.txt"
check "..in red" grep -qE "${RED_SGR}m("$'\e'"\[[0-9;]*m)*held" <<<"$(scap -e)"
check "its why line names the figure and the key" grep -q "held: memory -- 3.0 GB available, under WATCHDOG_MEM_MIN_GB=4" "${CAPS:?}/memguard-sched.txt"
check "the other rows keep their verdicts" grep -q "blocked *work" "${CAPS:?}/memguard-sched.txt"
"$K" Escape

echo "== the deck panel hidden: the badge moves to the claude title"
printf 'DASHBOARD_PANELS_HIDDEN=deck\n' >> "${MUXTOPUS_CONFIG:?}"
"$HERE/start.sh" 40 >/dev/null
check "the claude title carries it" grep -q "monitor on · memory low: new windows held" <<<"$(scap)"
sed -i '/^DASHBOARD_PANELS_HIDDEN=/d' "${MUXTOPUS_CONFIG:?}"

echo "== a stale reading, or one that says ok, draws nothing"
kill "$KEEP" 2>/dev/null; wait "$KEEP" 2>/dev/null
held_file low 600
"$HERE/start.sh" 40 >/dev/null
check "ten minutes old: no badge (a stopped daemon holds nothing)" bash -c '! grep -q "MEMORY LOW" <<<"$1"' _ "$(scap)"
held_file ok
"$K" r
check "ok: no badge" bash -c '! grep -q "MEMORY LOW" <<<"$1"' _ "$(scap)"

echo "== goldens"
python3 "$HERE/normalise.py" "${CAPS:?}"/*.txt
if [ "${1:-}" = "--bless" ]; then
  rm -rf -- "${GOLD:?}"; mkdir -p -- "${GOLD:?}"
  cp -- "${CAPS:?}"/*.txt "${GOLD:?}/"
  echo "blessed $(ls -1 "${GOLD:?}" | wc -l) memguard goldens"
else
  for g in "${GOLD:?}"/*.txt; do
    n="$(basename "$g")"
    if diff -u "$g" "${CAPS:?}/$n" > /dev/null; then ok "golden $n"
    else bad "golden $n"; diff -u "$g" "${CAPS:?}/$n" | head -30; fi
  done
fi

echo
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
