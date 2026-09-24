#!/usr/bin/env bash
# Lanes are named for their slug, and a window you opened yourself is not one.
#
#   bash tests/test_lane_names.sh
#
# TWO THINGS ARE UNDER TEST, and the second is the one that matters.
#
# 1. tree_wname no longer decorates: a lane's window is called <slug>, at any
#    depth. The ➥ markers were a cache, in the display name, of things already
#    on disk -- "this is a lane" (tree.tsv, the schedules, the handovers) and
#    how deep it sits (tree.tsv's parent column, which is what the dashboard's
#    `t` has always drawn the tree from).
#
# 2. THE INVARIANT: A WINDOW YOU OPEN BY HAND IS NOT A LANE. Removing the
#    arrows removes the test `tree_adopt` used to make, so it would have been
#    very easy to replace it with "adopt everything" -- which would pull
#    `status`, the plain `claude` window and every scratch window you ever
#    opened into the tree, and hand them handover paths. tree_is_lane is a
#    whitelist for exactly that reason, and most of this file is about the
#    windows that must NOT be touched.
#
# The sandbox of tests/notify_sandbox.sh on a socket of its own. Nothing here
# reaches a real pane, session, account or config.
SB_SOCKET=mxnames
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"
SC="$HOME/.code/schedules"; ST="$XDG_STATE_HOME/claude-watchdog"
HO="$HOME/.code/handovers"
mkdir -p "$SC" "$HO"
printf '● ready\n❯ \n' > "$HOME/fake-screen"
"$W" --on >/dev/null

wname() { tmux list-windows -t claude -F '#{window_name}' | paste -sd, -; }
has_window() { tmux list-windows -t claude -F '#{window_name}' | grep -qxF "$1"; }
tree_has() { awk -F'\t' -v s="$1" '$1==s{f=1} END{exit !f}' "$ST/tree.tsv" 2>/dev/null; }

echo "== a launched lane is named for its slug, with no marker"
tmux new-session -d -s claude -n status -c "$HOME" -x 120 -y 40 "sleep 600"
cat > "$SC/lane-a.md" <<EOF
type: work
at: 2020-01-01 00:00
slug: lane-a
cwd: $HOME
status: pending
---
carry on
EOF
"$W" --once >/dev/null 2>&1
for i in $(seq 40); do grep -q '^status: launched' "$SC/lane-a.md" && break; sleep 0.25; done
check "the window is called lane-a" has_window lane-a
no_markers() { ! tmux list-windows -t claude -F '#{window_name}' | grep -q '➥'; }
check "..and NOT ➥lane-a" no_markers
check "..and the tree knows it" tree_has lane-a

echo "== a CHILD is named for its slug too -- no second marker"
cat > "$SC/lane-b.md" <<EOF
type: work
at: 2020-01-01 00:00
slug: lane-b
parent: lane-a
cwd: $HOME
status: pending
---
carry on
EOF
"$W" --once >/dev/null 2>&1
for i in $(seq 40); do grep -q '^status: launched' "$SC/lane-b.md" && break; sleep 0.25; done
check "the child window is called lane-b" has_window lane-b
check "..no ➥➥ anywhere" no_markers
child_of() { awk -F'\t' -v c="$1" -v p="$2" '$1==c && $2==p{f=1} END{exit !f}' "$ST/tree.tsv"; }
check "..and the tree records its parent" child_of lane-b lane-a

echo "== THE INVARIANT: a window opened by hand is not a lane"
tmux new-window -d -t claude -n scratch -c "$HOME" "sleep 600"
tmux new-window -d -t claude -n my-notes -c "$HOME" "sleep 600"
"$W" --once >/dev/null 2>&1
not_in_tree() { ! tree_has "$1"; }
check "a hand-made window is not adopted into the tree" not_in_tree scratch
check "..nor the second one" not_in_tree my-notes
check "..nor the status window muxtopus draws itself" not_in_tree status
both_there() { has_window scratch && has_window my-notes; }
check "..and they are all still on screen, untouched" both_there
# window: and parent: of a pending entry hold a lane off `stranded`, but they
# must not make the window they name a lane: `window:` is the field that
# routinely names a window opened by hand. Far-future, so never launched.
for f in 'window: scratch' 'parent: my-notes'; do
  n="under-${f%%:*}"
  printf 'type: work\nat: 2099-01-01 00:00\nslug: %s\n%s\ncwd: %s\nstatus: pending\n---\nlater\n' \
    "$n" "$f" "$HOME" > "$SC/$n.md"
done
"$W" --once >/dev/null 2>&1
check "a pending window: scratch does not adopt scratch" not_in_tree scratch
check "..nor a pending parent: my-notes adopt my-notes" not_in_tree my-notes
rm -f "$SC/under-window.md" "$SC/under-parent.md"

echo "== a hand-made window that HAS a handover IS a lane (it wrote one)"
tmux new-window -d -t claude -n adopted-me -c "$HOME" "sleep 600"
printf '# STATUS-adopted-me\n' > "$HO/STATUS-adopted-me.md"
"$W" --once >/dev/null 2>&1
check "a window with a handover of its own name is adopted" tree_has adopted-me

echo "== the migration renames old windows, once, and only lanes"
tmux new-window -d -t claude -n '➥old-lane' -c "$HOME" "sleep 600"
tmux new-window -d -t claude -n '➥➥old-child' -c "$HOME" "sleep 600"
tmux new-window -d -t claude -n '➥not-a-lane' -c "$HOME" "sleep 600"
printf '# STATUS-old-lane\n' > "$HO/STATUS-old-lane.md"
printf '# STATUS-old-child\n' > "$HO/STATUS-old-child.md"
out="$("$W" --migrate-names --dry-run 2>&1)"
said() { grep -q "$1" <<<"$out"; }
check "--dry-run names the lane it would rename" said "old-lane"
check "..and the child, with both markers off" said "➥➥old-child -> old-child"
not_said() { ! grep -q "$1" <<<"$out"; }
check "..and REFUSES the one with no evidence" not_said "would rename ➥not-a-lane"
check "..and changed nothing" has_window '➥old-lane'

"$W" --migrate-names >/dev/null 2>&1
check "the rename happened" has_window old-lane
check "..the child too" has_window old-child
check "..the one that is not a lane kept its name" has_window '➥not-a-lane'
check "..and the tree is re-keyed to the new name" tree_has old-lane

echo "== a rename that would collide is refused, not forced"
tmux new-window -d -t claude -n taken -c "$HOME" "sleep 600"
tmux new-window -d -t claude -n '➥taken' -c "$HOME" "sleep 600"
printf '# STATUS-taken\n' > "$HO/STATUS-taken.md"
"$W" --migrate-names >/dev/null 2>&1
no_clobber() { has_window taken && has_window '➥taken'; }
check "both windows still exist -- neither was clobbered" no_clobber
logged() { grep -q "$1" "$ST/log"; }
check "..and the refusal is in the log" logged REFUSED

echo "== a name of up to MAX_SLUG (32) characters is whole, everywhere it is shown"
# 30 characters: the kind of `<orchestrator>-<lane>` name the old limit of 22
# cut in silence. --check shows it pinned and whole; the launched window, the
# tree row and the footer's handover path all carry all 30 -- tmux itself
# never cuts a window name, so nothing between the rule and the status bar may.
long=orchestrate-plan-orch-executor
[ "${#long}" -eq 30 ] || { echo "fixture slug is ${#long}, not 30"; exit 1; }
printf 'type: work\nat: 2099-01-01 00:00\nslug: %s\ncwd: %s\nstatus: pending\n---\nlater\n' \
  "$long" "$HOME" > "$SC/long-lane.md"
chk="$("$W" --check long-lane 2>&1)"
check "--check shows a 30-character slug: whole" grep -qF " $long   (pinned by slug:)" <<<"$chk"
check "..with no TRUNCATED warning" bash -c '! grep -q TRUNCATED <<<"$1"' _ "$chk"
check "..and the pasted footer names its whole handover" \
  grep -qF "handover.sh done $long" <<<"$("$W" --check long-lane --body 2>&1)"
sed -i 's/^at: 2099-01-01 00:00$/at: 2020-01-01 00:00/' "$SC/long-lane.md"
"$W" --once >/dev/null 2>&1
for i in $(seq 40); do grep -q '^status: launched' "$SC/long-lane.md" && break; sleep 0.25; done
check "the window is called all 30 characters" has_window "$long"
check "..and so is its tree row" tree_has "$long"

# A TITLE over the limit is still cut -- at 32 now, not 22 -- and SAID so.
# 23 characters, the first length the old rule truncated, is left alone.
t23=twenty-three-characters
[ "${#t23}" -eq 23 ] || { echo "fixture title is ${#t23}, not 23"; exit 1; }
printf 'type: work\nat: 2099-01-01 00:00\ntitle: %s\ncwd: %s\nstatus: pending\n---\nlater\n' \
  "$t23" "$HOME" > "$SC/t23.md"
chk="$("$W" --check t23 2>&1)"
check "a 23-character title is its own slug" grep -qF " $t23   (derived from title:" <<<"$chk"
check "..and draws no warning (the old rule cut it to 22)" bash -c '! grep -q TRUNCATED <<<"$1"' _ "$chk"
t33=this-title-is-thirty-three-chars-
[ "${#t33}" -eq 33 ] || { echo "fixture title is ${#t33}, not 33"; exit 1; }
printf 'type: work\nat: 2099-01-01 00:00\ntitle: %s\ncwd: %s\nstatus: pending\n---\nlater\n' \
  "$t33" "$HOME" > "$SC/t33.md"
chk="$("$W" --check t33 2>&1)"
check "a 33-character title is cut to 32" grep -qF " ${t33:0:32}   (derived" <<<"$chk"
check "..and the cut is said" grep -qF "the title is 33 characters, so the slug is TRUNCATED to \"${t33:0:32}\"" <<<"$chk"
rm -f "$SC/t23.md" "$SC/t33.md"

sb_done
