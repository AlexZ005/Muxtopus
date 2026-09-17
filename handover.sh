#!/usr/bin/env bash
# handover.sh -- the per-account folder of STATUS handoffs and QUESTIONS files.
#
#   handover.sh path <slug>      print where to write it (makes the folder)
#   handover.sh write <slug>     write it from stdin
#   handover.sh list             what is open here, what is asked, what is done
#   handover.sh show <slug>      print one
#   handover.sh done <slug>      move it to done/  (the whole item is finished)
#   handover.sh reopen <slug>    move it back out of done/
#   handover.sh answered <slug>  mark that lane's QUESTIONS file answered
#   handover.sh unanswer <slug>  take the marker off again
#   handover.sh --profile work list
#
# WHY IT IS NOT A FILE IN THE REPO. A handoff used to be written as
# STATUS-<window>.md into the working tree, which is wrong twice: it is scratch
# state under version control, and once a second account works the same tree,
# two windows of the same name overwrite each other's handoff without a word.
# So it lives beside the account's schedules instead: handovers/ for the
# default account, handovers-work/ for the next one -- or plain handovers/
# inside that account's own home, if the config gives it one (profile.sh).
#
# WHY done/ RATHER THAN rm. A finished handoff is the record of what a lane
# actually did, and it costs nothing to keep. Moving it also makes `list` mean
# something: what is left in the folder is what is still owed.
#
# WHAT "ANSWERED" IS, and why it is a marker rather than a move. A QUESTIONS
# file is answered iff some line of it matches ^\W*ANSWERED\b -- which is what
# the user was already typing by hand before anything read it. The file does
# NOT move when it is marked: {{QUESTIONS}} told the lane that exact path and
# the lane reads its answers there, so moving it would take the answers away
# from the window that asked. It travels with its handover instead: `done`
# carries an ANSWERED file into done/ and LEAVES an unanswered one, because a
# finished lane's unanswered forks are still owed a look.
#
# The dashboard's handovers tab shells out to this script for every state
# change, so never-clobber and the marker have ONE implementation. The one
# exception is the legacy questions folder (MUXTOPUS_QUESTIONS_DIR), which
# this script does not own: muxhandovers.mark_answered writes the marker
# there, and tests/test_handover_sh.sh asserts the two write the same line.
set -uo pipefail

. "$(dirname "$(readlink -f "$0")")/profile.sh"
if [ "${1:-}" = "--profile" ]; then
  [ -n "${2:-}" ] || { echo "--profile needs a name" >&2; exit 2; }
  mux_use_profile "$2"; shift 2
fi

DIR="$MUX_HANDOVERS"
DONE="$DIR/done"
mkdir -p "$DONE"

# A slug is a filename, never a path: it is pasted into prompts and typed back
# by an agent, so a stray ../ must not be able to reach out of the folder.
# The PREFIX is an argument because QUESTIONS files need the same guard, and
# one guard that both kinds go through cannot be half-applied to the newer one.
slugfile() {
  local prefix="$1" s="${2:-}"
  [ -n "$s" ] || { echo "need a name" >&2; exit 2; }
  s="${s##*/}"
  s="${s%.md}"
  s="${s#STATUS-}"
  s="${s#QUESTIONS-}"
  printf '%s/%s-%s.md' "$DIR" "$prefix" "$s"
}

slug_of() {
  local s="${1:-}"
  s="${s##*/}"; s="${s%.md}"; s="${s#STATUS-}"; s="${s#QUESTIONS-}"
  printf '%s' "$s"
}

# NEVER CLOBBER. The same window name comes round again -- a lane is resumed, a
# scheduled item repeats -- and the earlier file is the only record of what
# that run did, so a second one takes a stamped name rather than overwriting
# the first. muxhandovers.slug_of parses that name back.
move_to_done() {
  local f="$1" t
  t="$DONE/$(basename "$f")"
  [ -e "$t" ] && t="$DONE/$(basename "${f%.md}")-$(date +%Y%m%d-%H%M%S).md"
  mv "$f" "$t" && printf '%s' "$t"
}

is_answered() {
  grep -qE '^[^A-Za-z0-9_]*ANSWERED([^A-Za-z0-9_]|$)' "$1" 2>/dev/null
}

# The marker goes under the first heading, which is where a reader looks and
# where the user has been putting it by hand. Mirrored by
# muxhandovers.mark_answered for the legacy folder; the test compares them.
add_marker() {
  local f="$1" tmp
  tmp="$f.tmp.$$"
  awk -v marker="**ANSWERED $(date +%F)** (marked from the dashboard)" '
    { line[NR] = $0 }
    END {
      at = 1
      for (i = 1; i <= NR; i++) if (substr(line[i], 1, 1) == "#") { at = i + 1; break }
      while (at <= NR && line[at] ~ /^[ \t]*$/) at++
      for (i = 1; i < at; i++) print line[i]
      print marker
      print ""
      for (i = at; i <= NR; i++) print line[i]
    }' "$f" > "$tmp" && mv "$tmp" "$f"
}

# Taking it off again puts the file back the way it was, blank line included:
# a marker this script wrote is followed by one, and leaving that behind would
# mean answered -> unanswer -> answered grew the file every time round.
drop_marker() {
  local f="$1" tmp
  tmp="$f.tmp.$$"
  awk '
    /^[^A-Za-z0-9_]*ANSWERED([^A-Za-z0-9_]|$)/ { skipblank = 1; next }
    skipblank && /^[ \t]*$/ { skipblank = 0; next }
    { skipblank = 0; print }
  ' "$f" > "$tmp" && mv "$tmp" "$f"
}

cmd="${1:-list}"; shift 2>/dev/null || true

case "$cmd" in
  path)
    slugfile STATUS "${1:-}"; echo ;;

  write)
    f="$(slugfile STATUS "${1:-}")"; cat > "$f"; echo "$f" ;;

  show)
    f="$(slugfile STATUS "${1:-}")"
    [ -f "$f" ] || f="$DONE/$(basename "$(slugfile STATUS "${1:-}")")"
    [ -f "$f" ] || { echo "no handoff named ${1:-}" >&2; exit 1; }
    cat "$f" ;;

  done)
    f="$(slugfile STATUS "${1:-}")"
    [ -f "$f" ] || { echo "no open handoff named ${1:-} in $DIR" >&2; exit 1; }
    t="$(move_to_done "$f")"
    echo "done: $t"
    # THE QUESTIONS FILE TRAVELS WITH IT, if it has been answered. An
    # unanswered one stays exactly where it is: the lane is finished, but its
    # forks are still owed a look, and that is what the tab's top rows are for.
    q="$(slugfile QUESTIONS "${1:-}")"
    if [ -f "$q" ]; then
      if is_answered "$q"; then
        echo "questions: $(move_to_done "$q")"
      else
        echo "questions: $q left open -- it has no ANSWERED marker"
      fi
    fi ;;

  reopen)
    b="$(basename "$(slugfile STATUS "${1:-}")")"
    [ -f "$DONE/$b" ] || { echo "nothing named ${1:-} in $DONE" >&2; exit 1; }
    mv "$DONE/$b" "$DIR/$b"
    echo "reopened: $DIR/$b" ;;

  answered)
    q="$(slugfile QUESTIONS "${1:-}")"
    [ -f "$q" ] || { echo "no questions file named ${1:-} in $DIR" >&2; exit 1; }
    if is_answered "$q"; then
      echo "already answered: $q"
    else
      add_marker "$q" || { echo "could not mark $q" >&2; exit 1; }
      echo "answered: $q"
    fi
    # A lane that is ALREADY finished has nothing left to read its answers,
    # so the file goes where its handover went, at once.
    s="$(slug_of "${1:-}")"
    if [ -f "$DONE/STATUS-$s.md" ] && [ -f "$q" ]; then
      echo "questions: $(move_to_done "$q")  (its handover is already in done/)"
    fi ;;

  unanswer)
    q="$(slugfile QUESTIONS "${1:-}")"
    if [ ! -f "$q" ]; then
      b="$(basename "$q")"
      [ -f "$DONE/$b" ] && { mv "$DONE/$b" "$q"; echo "brought back: $q"; }
    fi
    [ -f "$q" ] || { echo "no questions file named ${1:-} in $DIR" >&2; exit 1; }
    if is_answered "$q"; then
      drop_marker "$q" || { echo "could not unmark $q" >&2; exit 1; }
      echo "unanswered: $q"
    else
      echo "was not answered: $q"
    fi ;;

  list)
    n=0
    printf 'handovers (%s) -- %s\n' "$MUX_LABEL" "$DIR"
    for f in "$DIR"/STATUS-*.md; do
      [ -f "$f" ] || continue
      n=$((n+1))
      printf '  %-28s %s\n' \
        "$(basename "${f%.md}" | sed 's/^STATUS-//')" \
        "$(date -r "$f" '+%b %d %H:%M')"
    done
    [ "$n" = 0 ] && echo '  (none open)'
    # WHAT IS BEING ASKED OF YOU, beside what is being worked on. These are
    # the rows the dashboard's handovers tab puts at the top, and `list` is
    # what a window with no dashboard has instead.
    q=0
    for f in "$DIR"/QUESTIONS-*.md; do
      [ -f "$f" ] || continue
      q=$((q+1))
      [ "$q" = 1 ] && printf '  questions:\n'
      state=unanswered; is_answered "$f" && state=answered
      printf '  %-28s %-10s %s\n' \
        "$(basename "${f%.md}" | sed 's/^QUESTIONS-//')" "$state" \
        "$(date -r "$f" '+%b %d %H:%M')"
    done
    d=$(ls -1 "$DONE"/STATUS-*.md 2>/dev/null | wc -l)
    printf '  %s done in %s\n' "$d" "$DONE" ;;

  -h|--help) sed -n '2,12p' "$0" ;;
  *) echo "unknown command: $cmd" >&2; sed -n '2,12p' "$0" >&2; exit 2 ;;
esac
