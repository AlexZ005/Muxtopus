#!/usr/bin/env bash
# handover.sh: the marker, and what `done` carries with it.
#
#   tests/test_handover_sh.sh
#
# IT RUNS IN A HOME OF ITS OWN. profile.sh builds MUX_HANDOVERS out of
# MUXTOPUS_HOME, which falls back to $XDG_DATA_HOME/muxtopus and then to
# $HOME/.local/share/muxtopus -- so a sandbox HOME, XDG_DATA_HOME,
# XDG_CONFIG_HOME and MUXTOPUS_CONFIG put every folder this touches inside
# the sandbox. The first thing the script does is ASK the tool where it
# thinks its folder is and refuse to run if that is not under the sandbox:
# this test moves and deletes files, and the real folder is the user's record
# of every lane that has ever run here.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
FIX="$ROOT/tests/fixtures/handovers"

SB="$(mktemp -d "${TMPDIR:-/tmp}/handover-sh-XXXXXX")"
export HOME="$SB/home"
export XDG_DATA_HOME="$SB/home/.local/share"
export XDG_CONFIG_HOME="$SB/config"
export XDG_STATE_HOME="$SB/state"
export MUXTOPUS_CONFIG="$SB/config/muxtopus/config"
export MUXTOPUS_PROFILES_DIR="$SB/config/muxtopus/profiles"
mkdir -p "$HOME" "$XDG_CONFIG_HOME/muxtopus/profiles" "$XDG_STATE_HOME"

H="$ROOT/handover.sh"
pass=0; fail=0
ok()  { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad() { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }
check() { if "${@:2}"; then ok "$1"; else bad "$1"; fi; }

# ---- 0. the folder this is about to move files around in ------------------
DIR="$(bash -c '. "'"$ROOT"'/profile.sh"; printf "%s" "$MUX_HANDOVERS"')"
echo "MUX_HANDOVERS = $DIR"
case "$DIR" in
  "$SB"/*) ok "the folder under test is inside the sandbox" ;;
  *) echo "REFUSING TO RUN: $DIR is not under $SB" >&2; exit 2 ;;
esac
DONE="$DIR/done"

fresh() {   # a folder with one open handover and one questions file per shape
  rm -rf -- "${DIR:?}"
  mkdir -p -- "${DONE:?}"
  cp -- "$FIX/hdir/STATUS-open-lane.md" "$DIR/STATUS-lane-a.md"
  cp -- "$FIX/hdir/STATUS-open-lane.md" "$DIR/STATUS-lane-b.md"
  cp -- "$FIX/hdir/QUESTIONS-open-lane.md" "$DIR/QUESTIONS-lane-a.md"
  cp -- "$FIX/hdir/QUESTIONS-open-lane.md" "$DIR/QUESTIONS-lane-b.md"
}

echo "== the marker"
fresh
"$H" answered lane-a > "$SB/out" 2>&1
check "answered says which file it marked" grep -q "answered: .*QUESTIONS-lane-a.md" "$SB/out"
check "and the file carries the marker" \
  grep -q '^\*\*ANSWERED [0-9-]*\*\* (marked from the dashboard)$' "$DIR/QUESTIONS-lane-a.md"
check "...under the first heading, not above it" \
  bash -c 'head -1 "'"$DIR"'/QUESTIONS-lane-a.md" | grep -q "^# QUESTIONS"'
n="$(grep -c 'ANSWERED' "$DIR/QUESTIONS-lane-a.md")"
check "exactly one marker line" [ "$n" = 1 ]

cp -- "$DIR/QUESTIONS-lane-a.md" "$SB/once.md"
"$H" answered lane-a > "$SB/out" 2>&1
check "marking it again is refused, not stacked" grep -q "already answered" "$SB/out"
check "...and the file is byte for byte what it was" \
  cmp -s "$SB/once.md" "$DIR/QUESTIONS-lane-a.md"

# The hand-typed marker the user was writing before anything read it.
printf '# QUESTIONS — hand\n\n**ANSWERED 2026-09-17: as written**\n\n1. a fork\n' \
  > "$DIR/QUESTIONS-hand.md"
"$H" answered hand > "$SB/out" 2>&1
check "the marker the USER types by hand already counts" grep -q "already answered" "$SB/out"

echo "== unanswer puts it back"
cp -- "$FIX/hdir/QUESTIONS-open-lane.md" "$SB/before.md"
cp -- "$SB/before.md" "$DIR/QUESTIONS-lane-b.md"
"$H" answered lane-b >/dev/null 2>&1
"$H" unanswer lane-b > "$SB/out" 2>&1
check "unanswer says so" grep -q "unanswered: " "$SB/out"
check "and the file is EXACTLY what it was before the marker" \
  cmp -s "$SB/before.md" "$DIR/QUESTIONS-lane-b.md"
"$H" unanswer lane-b > "$SB/out" 2>&1
check "unanswering an unmarked file is a no-op that says so" \
  grep -q "was not answered" "$SB/out"
check "...and still did not change it" cmp -s "$SB/before.md" "$DIR/QUESTIONS-lane-b.md"

echo "== done takes an ANSWERED questions file along, and leaves an open one"
fresh
"$H" answered lane-a >/dev/null 2>&1
"$H" done lane-a > "$SB/out" 2>&1
check "the handover moved"        [ -f "$DONE/STATUS-lane-a.md" ]
check "...and is gone from the open folder" [ ! -f "$DIR/STATUS-lane-a.md" ]
check "the answered questions went with it" [ -f "$DONE/QUESTIONS-lane-a.md" ]
check "and done said so"          grep -q "questions: .*done/QUESTIONS-lane-a.md" "$SB/out"

"$H" done lane-b > "$SB/out" 2>&1
check "the second lane's handover moved"     [ -f "$DONE/STATUS-lane-b.md" ]
check "its UNANSWERED questions file stayed" [ -f "$DIR/QUESTIONS-lane-b.md" ]
check "...and done said why"      grep -q "left open -- it has no ANSWERED marker" "$SB/out"

echo "== answered on a lane that is already finished moves it at once"
check "the file is still open before the marker" [ -f "$DIR/QUESTIONS-lane-b.md" ]
"$H" answered lane-b > "$SB/out" 2>&1
check "answered moved it, because the handover is already in done/" \
  [ -f "$DONE/QUESTIONS-lane-b.md" ]
check "and said which"            grep -q "its handover is already in done/" "$SB/out"
check "...it is not in both places" [ ! -f "$DIR/QUESTIONS-lane-b.md" ]

echo "== never clobber, for both kinds"
fresh
"$H" answered lane-a >/dev/null 2>&1
"$H" done lane-a >/dev/null 2>&1
cp -- "$FIX/hdir/STATUS-open-lane.md" "$DIR/STATUS-lane-a.md"
cp -- "$FIX/hdir/QUESTIONS-open-lane.md" "$DIR/QUESTIONS-lane-a.md"
"$H" answered lane-a >/dev/null 2>&1
"$H" done lane-a > "$SB/out" 2>&1
check "the first finish is still there" [ -f "$DONE/STATUS-lane-a.md" ]
s="$(ls -1 "$DONE" | grep -c '^STATUS-lane-a-[0-9]\{8\}-[0-9]\{6\}\.md$')"
check "and the second took a stamped name" [ "$s" = 1 ]
q="$(ls -1 "$DONE" | grep -c '^QUESTIONS-lane-a-[0-9]\{8\}-[0-9]\{6\}\.md$')"
check "the questions file did the same" [ "$q" = 1 ]
check "the stamped name is one muxhandovers parses back" \
  bash -c 'python3 -c "
import sys; sys.path.insert(0, \"'"$ROOT"'\")
import muxhandovers as mh, os
for f in os.listdir(\"'"$DONE"'\"):
    kind, slug, stamp = mh.slug_of(f)
    assert kind and slug == \"lane-a\", (f, kind, slug)
"'

echo "== the path-escape guard, on both prefixes"
fresh
mkdir -p "$SB/outside"
printf 'not ours\n' > "$SB/outside/STATUS-escape.md"
printf 'not ours\n' > "$SB/outside/QUESTIONS-escape.md"
"$H" done "../outside/STATUS-escape" > "$SB/out" 2>&1
check "a ../ slug cannot reach out of the folder (done)" [ -f "$SB/outside/STATUS-escape.md" ]
check "...and it is refused by name"  grep -q "no open handoff named" "$SB/out"
"$H" answered "../outside/QUESTIONS-escape" > "$SB/out" 2>&1
check "a ../ slug cannot reach out of the folder (answered)" \
  bash -c '! grep -q ANSWERED "'"$SB"'/outside/QUESTIONS-escape.md"'
check "...and it is refused by name"  grep -q "no questions file named" "$SB/out"
p="$("$H" path "../../etc/passwd")"
case "$p" in "$DIR"/STATUS-passwd.md) ok "path flattens a slug to a filename" ;;
             *) bad "path flattened to $p" ;; esac
"$H" answered "" > "$SB/out" 2>&1
check "an empty slug is refused"      grep -q "need a name" "$SB/out"

echo "== list says what is asked as well as what is open"
fresh
"$H" answered lane-a >/dev/null 2>&1
"$H" list > "$SB/out" 2>&1
check "the open handovers are listed" grep -q "lane-b " "$SB/out"
check "there is a questions section"  grep -q "questions:" "$SB/out"
check "an answered file says so"      grep -qE "lane-a +answered" "$SB/out"
check "an unanswered one says so"     grep -qE "lane-b +unanswered" "$SB/out"

echo "== --profile puts it in that account's folder"
WORK="$(bash -c '. "'"$ROOT"'/profile.sh"; mux_use_profile work; printf "%s" "$MUX_HANDOVERS"')"
check "a named account has a folder of its own" [ "$WORK" != "$DIR" ]
case "$WORK" in "$SB"/*) ok "...still inside the sandbox" ;;
                *) echo "REFUSING: $WORK" >&2; exit 2 ;; esac
mkdir -p "$WORK"
cp -- "$FIX/hdir/QUESTIONS-open-lane.md" "$WORK/QUESTIONS-lane-w.md"
"$H" --profile work answered lane-w > "$SB/out" 2>&1
check "--profile marked the work account's file" grep -q ANSWERED "$WORK/QUESTIONS-lane-w.md"
check "and left the default account's alone" \
  bash -c '! grep -q ANSWERED "'"$DIR"'/QUESTIONS-lane-b.md"'

echo "== the two writers of the marker agree"
# handover.sh owns the handovers folder; muxhandovers.mark_answered owns the
# LEGACY questions folder, which this script has no business writing to. Two
# implementations, therefore, and a test that they produce the same line.
fresh
"$H" answered lane-a >/dev/null 2>&1
python3 - "$ROOT" "$FIX/hdir/QUESTIONS-open-lane.md" "$SB/py.md" <<'PY'
import datetime, pathlib, sys
sys.path.insert(0, sys.argv[1])
import muxhandovers as mh
text = pathlib.Path(sys.argv[2]).read_text()
pathlib.Path(sys.argv[3]).write_text(
    mh.mark_answered(text, datetime.date.today().isoformat()))
PY
check "muxhandovers writes the same file as handover.sh" \
  cmp -s "$SB/py.md" "$DIR/QUESTIONS-lane-a.md"

echo "== --help lists every command"
"$H" --help > "$SB/out" 2>&1
for c in path write list show done reopen answered unanswer --profile; do
  check "--help mentions $c" grep -q -- "$c" "$SB/out"
done
"$H" nonsense > "$SB/out" 2>&1; rc=$?
check "an unknown command exits non-zero" [ "$rc" != 0 ]
check "...and prints the usage"       grep -q "handover.sh path" "$SB/out"

rm -rf -- "${SB:?}"
echo
if [ "$fail" = 0 ]; then echo "$pass checks: handover.sh"; else
  echo "$pass passed, $fail FAILED"; fi
exit $((fail > 0))
