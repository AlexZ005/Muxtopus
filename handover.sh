#!/usr/bin/env bash
# handover.sh -- the per-account folder of STATUS handoffs.
#
#   handover.sh path <slug>      print where to write it (makes the folder)
#   handover.sh write <slug>     write it from stdin
#   handover.sh list             what is open here, and how much is done
#   handover.sh show <slug>      print one
#   handover.sh done <slug>      move it to done/  (the whole item is finished)
#   handover.sh reopen <slug>    move it back out of done/
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
slugfile() {
  local s="${1:-}"
  [ -n "$s" ] || { echo "need a name" >&2; exit 2; }
  s="${s##*/}"
  s="${s%.md}"
  s="${s#STATUS-}"
  printf '%s/STATUS-%s.md' "$DIR" "$s"
}

cmd="${1:-list}"; shift 2>/dev/null || true

case "$cmd" in
  path)
    slugfile "${1:-}"; echo ;;

  write)
    f="$(slugfile "${1:-}")"; cat > "$f"; echo "$f" ;;

  show)
    f="$(slugfile "${1:-}")"
    [ -f "$f" ] || f="$DONE/$(basename "$(slugfile "${1:-}")")"
    [ -f "$f" ] || { echo "no handoff named ${1:-}" >&2; exit 1; }
    cat "$f" ;;

  done)
    f="$(slugfile "${1:-}")"
    [ -f "$f" ] || { echo "no open handoff named ${1:-} in $DIR" >&2; exit 1; }
    t="$DONE/$(basename "$f")"
    # NEVER CLOBBER. The same window name comes round again -- a lane is
    # resumed, a scheduled item repeats -- and the earlier handoff is the only
    # record of what that run did, so a second one takes a stamped name rather
    # than overwriting the first.
    [ -e "$t" ] && t="$DONE/$(basename "${f%.md}")-$(date +%Y%m%d-%H%M%S).md"
    mv "$f" "$t"
    echo "done: $t" ;;

  reopen)
    b="$(basename "$(slugfile "${1:-}")")"
    [ -f "$DONE/$b" ] || { echo "nothing named ${1:-} in $DONE" >&2; exit 1; }
    mv "$DONE/$b" "$DIR/$b"
    echo "reopened: $DIR/$b" ;;

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
    d=$(ls -1 "$DONE"/STATUS-*.md 2>/dev/null | wc -l)
    printf '  %s done in %s\n' "$d" "$DONE" ;;

  -h|--help) sed -n '2,10p' "$0" ;;
  *) echo "unknown command: $cmd" >&2; sed -n '2,10p' "$0" >&2; exit 2 ;;
esac
