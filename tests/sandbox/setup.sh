#!/usr/bin/env bash
# Build the fake machine from tests/fixtures/dashboard/, replacing @SB@ with
# the sandbox root and @SCRIPTS@ with this checkout. Idempotent: it removes
# and rebuilds the fixture half, and leaves nothing else on the machine.
set -euo pipefail
. "$(dirname "$0")/env.sh"
FIX="${SANDBOX_FIXTURES:?}"

rm -rf -- "${SB:?}"
mkdir -p -- "${SB:?}"
cp -r -- "$FIX/." "${SB:?}/"
# The fixtures name the sandbox by placeholder so they can be read and
# reviewed as files; nothing in them is a path until now.
grep -rIl '@SB@\|@SCRIPTS@' -- "${SB:?}" | while read -r f; do
  sed -i "s|@SB@|${SB:?}|g; s|@SCRIPTS@|${SCRIPTS:?}|g" -- "$f"
done

mkdir -p -- "${CLAUDE_CONFIG_DIR:?}" "${SB:?}/home/.claude/sessions" \
            "${SB:?}/home/.local/bin" "${SB:?}/caps"
# The fake claude is reached through PATH; a copy in the fake HOME as well,
# because the launcher prefers ~/.local/bin/claude when it is there.
cp -- "$(dirname "$0")/bin/claude" "${SB:?}/home/.local/bin/claude"
echo "sandbox built: ${SB:?}"
