#!/usr/bin/env bash
# The window's identity rides in the system prompt, and an empty plan pastes
# nothing.
#
#   bash tests/test_identity.sh
#
# The sandbox of tests/notify_sandbox.sh (-L mxnotify, a fake claude that
# records its argv and every key typed into it, and answers --help like the
# real one); nothing here reaches a real pane or schedule. Run it on its own:
# the notify sandboxes share a socket name and fake each other's failures
# when two run at once.
#
# WHAT IS UNDER TEST. The seven `[muxtopus]` identity lines used to be the top
# of every paste, followed by Enter -- so a window opened from the dashboard
# with no first prompt still got a first message, and spent its first turn
# answering it. Now:
#
#   - a launched window is given --append-system-prompt-file <file>, and the
#     file holds the slug and the handover path;
#   - the paste holds the body and nothing else: no identity lines in the
#     keys the window received;
#   - an empty plan pastes NOTHING and presses nothing -- no keys at all --
#     and the log says the window opened at a blank prompt;
#   - a claude whose --help lacks the flag (FAKE_CLAUDE_OLD=1) gets the old
#     shape: identity at the top of the paste, no flag on the command line,
#     one log line saying so;
#   - --check prints the identity and the paste as two blocks.
set -uo pipefail
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"
SC="$HOME/.code/schedules"; ST="$XDG_STATE_HOME/claude-watchdog"
entry() {  # entry NAME TYPE [body]
  { printf 'type: %s\nat: 2020-01-01 00:00\nslug: %s\ncwd: %s\nstatus: pending\n---\n' "$2" "$1" "$HOME"
    [ -n "${3:-}" ] && printf '%s\n' "$3"; } > "$SC/$1.md"
}
printf '● ready\n❯ \n' > "$HOME/fake-screen"
tmux new-session -d -s claude -n home -x 120 -y 40 "sleep 600"
"$W" --on >/dev/null

launch() {  # launch NAME: one pass, then wait for the status and (if any) the keys
  rm -f "$HOME/fake-claude.keys" "$HOME/fake-claude.argv"
  "$W" --once >/dev/null 2>&1
  for i in $(seq 40); do grep -q '^status: launched' "$SC/$1.md" && break; sleep 0.25; done
}
# %q-encoded, one key a line: a space is "\ ", so backslashes go too.
keys() { tr -d '\n\\' < "$HOME/fake-claude.keys" 2>/dev/null; }
argv_of() { grep -v -- '^--help' "$HOME/fake-claude.argv" 2>/dev/null | tail -1; }

echo "== a work entry: the flag and the file, and a paste without the header"
entry lane-work work "carry on"
launch lane-work
for i in $(seq 40); do keys | grep -q carry && break; sleep 0.25; done
check "launched" grep -q '^status: launched' "$SC/lane-work.md"
check "claude was given --append-system-prompt-file" \
  grep -q -- "--append-system-prompt-file $ST/identity/lane-work.md" <<<"$(argv_of)"
check "the file names the slug" grep -q 'Its lane slug is: lane-work' "$ST/identity/lane-work.md"
check "..and the handover path" grep -q 'STATUS-lane-work.md' "$ST/identity/lane-work.md"
check "..and the tmux warning" grep -q 'kill-server' "$ST/identity/lane-work.md"
check "the body was pasted" grep -q carry <<<"$(keys)"
check "the identity was NOT pasted" bash -c '! grep -q "This tmux window" <<<"$1"' _ "$(keys)"
check "..nor the old header" bash -c '! grep -q "lane slug" <<<"$1"' _ "$(keys)"
check "the footer still names the handover" grep -q 'STATUS-lane-work.md' <<<"$(keys)"

echo "== an empty plan: nothing pasted, nothing pressed"
entry lane-empty plan
launch lane-empty
sleep 2
check "launched" grep -q '^status: launched' "$SC/lane-empty.md"
check "the flag was still given" grep -q -- "--append-system-prompt-file $ST/identity/lane-empty.md" <<<"$(argv_of)"
check "no key reached the window at all" test ! -s "$HOME/fake-claude.keys"
check "the log says it opened at a blank prompt" grep -q 'lane-empty.md: empty body, nothing pasted' "$ST/log"

echo "== --check: two blocks, and 'nothing is pasted' for the empty plan"
out="$("$W" --check lane-work --body 2>&1)"
check "an identity block" grep -q 'the identity, in the system prompt' <<<"$out"
check "..with the slug in it" grep -q 'Its lane slug is: lane-work' <<<"$out"
check "a paste block" grep -q 'what would be pasted' <<<"$out"
check "..without the identity in it" bash -c 'sed -n "/what would be pasted/,\$p" <<<"$1" | grep -vq "lane slug is"' _ "$out"
check "the identity line names the file and the flag" grep -q 'identity .*identity/lane-work.md, on claude.s --append-system-prompt-file' <<<"$out"
out="$("$W" --check lane-empty 2>&1)"
check "the empty plan says nothing is pasted" grep -q 'empty -- nothing is pasted' <<<"$out"

echo "== an older claude: no flag, the identity pasted first, said once"
# A NEW DAEMON PROCESS, so the probe runs again: --once is one process per
# call here, and the fake's --help is what it reads.
entry lane-old work "carry on"
rm -f "$HOME/fake-claude.keys" "$HOME/fake-claude.argv"
FAKE_CLAUDE_OLD=1 "$W" --once >/dev/null 2>&1
for i in $(seq 40); do grep -q '^status: launched' "$SC/lane-old.md" && break; sleep 0.25; done
for i in $(seq 60); do keys | grep -q carry && break; sleep 0.25; done
check "launched" grep -q '^status: launched' "$SC/lane-old.md"
check "no --append-system-prompt-file on the command line" \
  bash -c '! grep -q -- "--append-system-prompt-file" <<<"$1"' _ "$(argv_of)"
check "the identity was pasted" grep -q 'Its lane slug is: lane-old' <<<"$(keys)"
check "..BEFORE the body" bash -c '[[ "$1" == *"lane slug is: lane-old"*"carry"* ]]' _ "$(keys)"
check "the log said why, once" test "$(grep -c 'does not list --append-system-prompt-file' "$ST/log")" = 1

sb_done
