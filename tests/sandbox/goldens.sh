#!/usr/bin/env bash
# Run the route and compare every capture with tests/goldens/.
#
#   goldens.sh            compare; non-zero and a diff on the first mismatch
#   goldens.sh --bless    write the captures as the goldens
#
# --bless is phase 0's key and nobody else's: after the split has started, a
# capture that differs from its golden is a bug in the move. The only blessed
# change planned is the HELP screen, and its commit says so out loud.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/env.sh"
GOLD="${SCRIPTS:?}/tests/goldens"
CAPS="${SB:?}/caps"

"$HERE/route.sh" >/dev/null || { echo "route failed"; exit 2; }

if [ "${1:-}" = "--bless" ]; then
  rm -rf -- "${GOLD:?}"; mkdir -p -- "${GOLD:?}"
  cp -- "${CAPS:?}"/*.txt "${GOLD:?}/"
  echo "blessed $(ls -1 "${GOLD:?}" | wc -l) goldens"
  exit 0
fi

fail=0
for g in "${GOLD:?}"/*.txt; do
  n="$(basename "$g")"
  if [ ! -f "${CAPS:?}/$n" ]; then
    echo "MISSING capture: $n"; fail=1; continue
  fi
  if ! diff -u "$g" "${CAPS:?}/$n" > /dev/null; then
    echo "DIFF $n"; diff -u "$g" "${CAPS:?}/$n" | head -40; fail=1
  fi
done
for c in "${CAPS:?}"/*.txt; do
  n="$(basename "$c")"
  [ -f "${GOLD:?}/$n" ] || { echo "EXTRA capture: $n"; fail=1; }
done
[ "$fail" = 0 ] && echo "goldens: $(ls -1 "${GOLD:?}" | wc -l) identical"
exit "$fail"
