#!/usr/bin/env bash
# Phase 4: muxtelegram -- the phone answers a fork.
# Sandbox tmux (-L mxnotify) + fake claude + fake Bot API. /questions lists the
# files as buttons, a press sends that file's forks, a button answer and a
# typed reply both land as muxhandovers.write_answer lines, the last fork marks
# the file ANSWERED and tells the lane's idle pane, and a file the lane rewrote
# underneath is re-applied to the same fork.
#   bash tests/test_notify_forks.sh
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"; T="$REPO/muxtelegram.py"
ST="$XDG_STATE_HOME/claude-watchdog"; SH="$XDG_STATE_HOME/muxtopus-notify"
HO="$HOME/.code/handovers"; LEG="$HOME/.code/theprototype-app/core/plans"
NLOG="$ST/notify.log"
DATE="$(date +%F)"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"

setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
pass() { "$W" --once >/dev/null 2>&1; }
poll() { python3 "$T" poll; }
texts() { sb_calls sendMessage | jq -r .text; }
last_text() { sb_calls sendMessage | tail -1 | jq -r .text; }
last_edit() { sb_calls editMessageText | tail -1 | jq -r .text; }
cb_said() { sb_calls answerCallbackQuery | tail -1 | jq -r .text; }
# The fake API numbers messages 1001, 1002 ... in the order they were sent.
mid_of() { sb_calls sendMessage | jq -r '.text | split("\n")[0]' | grep -n -- "$1" | tail -1 | cut -d: -f1 | awk '{print 1000 + $1}'; }
kb_of() { sb_calls sendMessage | jq -c --arg re "$1" 'select(.text|test($re)) | .reply_markup | fromjson' | tail -1; }
labels_of() { kb_of "$1" | jq -c '[.inline_keyboard[] | [.[] .text]]'; }
cb_of() { kb_of "$1" | jq -r --arg l "$2" '.inline_keyboard[][] | select(.text==$l) | .callback_data'; }
UID_N=0
press() {  # press DATA [MID]
  UID_N=$(( UID_N + 1 ))
  sb_update "$(jq -cn --arg d "$1" --argjson u "$UID_N" --argjson m "${2:-1001}" \
    '{update_id:$u, callback_query:{id:("q"+($u|tostring)), from:{id:4242}, message:{message_id:$m, chat:{id:4242}, text:"x"}, data:$d}}')"
}
reply() {  # reply TO_MID TEXT [CHAT]
  UID_N=$(( UID_N + 1 ))
  sb_update "$(jq -cn --arg t "$2" --argjson r "$1" --argjson c "${3:-4242}" --argjson u "$UID_N" \
    '{update_id:$u, message:{message_id:(500+$u), from:{id:$c}, chat:{id:$c, type:"private"}, text:$t, reply_to_message:{message_id:$r}}}')"
}
say() {
  UID_N=$(( UID_N + 1 ))
  sb_update "$(jq -cn --arg t "$1" --argjson u "$UID_N" \
    '{update_id:$u, message:{message_id:(500+$u), from:{id:4242}, chat:{id:4242, type:"private"}, text:$t}}')"
}
# The fork a line sits in: the nearest `## ` heading above it.
fork_of() { awk -v pat="$2" '/^## /{h=$0} index($0, pat){print h; exit}' "$1"; }

# ---- the lane: a live, idle window, so the last answer can tell it
printf '● done.\n\n────\n❯ \n────\n' > "$HOME/fake-screen"
tmux new-session -d -s claude -n '➥lane-q' -x 100 -y 40 "cd $HOME && claude"
for i in $(seq 50); do ls "$HOME/.claude/sessions/"*.json >/dev/null 2>&1 && break; sleep 0.1; done
PANE="$(tmux list-panes -t claude -F '#{pane_id}' | head -1)"
WID="$(tmux list-windows -t claude -F '#{window_id}' | head -1)"
for k in WAITING QUESTIONS TROUBLE DONE; do setkey "MUXTOPUS_NOTIFY_$k" off; done
"$W" --on >/dev/null
pass; pass
printf 'lane-q\t\t%s\t%s\t%s\tlane-q.md\n' "$WID" "$PANE" "$(date +%s)" > "$ST/tree.tsv"
check "the sandbox lane is idle in status.tsv" \
  bash -c 'awk -F"\t" -v p="$1" "\$3==p{print \$6}" "$2" | grep -qx idle' _ "$PANE" "$ST/status.tsv"

# ---- the files
cat > "$HO/QUESTIONS-lane-q.md" <<'EOF'
# Questions: lane-q

## 1. Which clock
- **(a) host clock** -- simple.
- **(b) mesh clock** -- consistent across machines.
Recommendation: (b)

## 2. Which port
Options: (a) 80; (b) 8080.

## 3. Which log
Where should the logs go? No options -- say it.
EOF
mkdir -p "$LEG"
printf '# Q\n\n## 1. Legacy fork\n(a) keep (b) drop\n' > "$LEG/QUESTIONS-legacy.md"
{ printf '# Many\n'; for i in $(seq 10); do printf '\n## %d. Fork number %d\n(a) yes (b) no\n' "$i" "$i"; done; } > "$HO/QUESTIONS-many.md"

echo "== /questions: the unanswered files, as buttons"
say /questions; poll
Q="$(kb_of 'press one for its forks')"
check "one button per file, one per row" \
  [ "$(jq -c '[.inline_keyboard[] | [.[] .text]]' <<<"$Q")" = '[["lane-q · 3 forks"],["many · 10 forks"],["legacy · 1 fork"]]' ]
check "..and the text lists them with the account" grep -q "^personal · lane-q · 3 forks$" <<<"$(texts)"
check "..the legacy file is said to be one" grep -q "legacy · 1 fork (legacy folder)" <<<"$(texts)"

echo "== a press sends that file's forks, one message each"
n0="$(sb_ncalls sendMessage)"
press "$(jq -r '.inline_keyboard[0][0].callback_data' <<<"$Q")"; poll
check "three messages" [ "$(sb_ncalls sendMessage)" = $(( n0 + 3 )) ]
check "each names the file and its place" grep -q "^personal · lane-q · fork 2/3" <<<"$(texts)"
check "the fork's own text is in it" grep -q "Options: (a) 80; (b) 8080." <<<"$(texts)"
check "fork 1: (a) · ★ (b), then ✎ type" [ "$(labels_of 'lane-q · fork 1/3')" = '[["(a)","★ (b)"],["✎ type"]]' ]
check "fork 2: inline options, none recommended" [ "$(labels_of 'lane-q · fork 2/3')" = '[["(a)","(b)"],["✎ type"]]' ]
check "fork 3: no options -- ✎ type alone" [ "$(labels_of 'lane-q · fork 3/3')" = '[["✎ type"]]' ]
check "the /questions keyboard still works (asking is not consumed)" \
  [ -f "$SH/pending/$(jq -r '.inline_keyboard[0][0].callback_data' <<<"$Q").json" ]

echo "== capped at 8"
n0="$(sb_ncalls sendMessage)"
press "$(jq -r '.inline_keyboard[1][0].callback_data' <<<"$Q")"; poll
check "eight forks and a 'more' line" [ "$(sb_ncalls sendMessage)" = $(( n0 + 9 )) ]
check "..which says how many are left" grep -q "many: showing 8; 2 more -- open the dashboard" <<<"$(last_text)"

echo "== a button answer lands as a write_answer line"
M1="$(mid_of 'lane-q · fork 1/3')"
B1="$(cb_of 'lane-q · fork 1/3' '★ (b)')"; A1="$(cb_of 'lane-q · fork 1/3' '(a)')"
press "$B1" "$M1"; poll
check "the line is muxhandovers' own, source and all" grep -qx "\*\*Answer (user via telegram, $DATE):\*\* (b)" "$HO/QUESTIONS-lane-q.md"
check "..inside fork 1" [ "$(fork_of "$HO/QUESTIONS-lane-q.md" '**Answer (user via telegram')" = "## 1. Which clock" ]
check "..and it is the line write_answer writes" python3 - "$REPO" "$DATE" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1]); import muxhandovers as mh
assert mh.answer_line("(b)", sys.argv[2], "user via telegram") == "**Answer (user via telegram, %s):** (b)" % sys.argv[2]
assert mh.answer_line("(b)", sys.argv[2]) == "**Answer (user, %s):** (b)" % sys.argv[2]   # the dashboard's, unchanged
assert mh.OURS_RE.match(mh.answer_line("x", "d", "user via telegram"))
EOF
check "the press was answered" [ "$(cb_said)" = written ]
check "the message was edited: what, and when" grep -q "✓ (b) written from the phone at [0-9][0-9]:[0-9][0-9]$" <<<"$(last_edit)"
check "..keeping the fork's text above it" grep -q "Which clock" <<<"$(last_edit)"
check "notify.log has a line" grep -q "fork answered from the phone: .*QUESTIONS-lane-q.md#.* = (b)" "$NLOG"
check "the file is NOT marked yet" bash -c '! grep -q ANSWERED "$1"' _ "$HO/QUESTIONS-lane-q.md"
press "$A1" "$M1"; poll
check "the other button of that message is spent" [ "$(cb_said)" = "expired or already used" ]
check "..and did not add a second answer" [ "$(grep -c '^\*\*Answer' "$HO/QUESTIONS-lane-q.md")" = 1 ]

echo "== the lane rewrites its file underneath: re-applied to the same fork"
M2="$(mid_of 'lane-q · fork 2/3')"; A2="$(cb_of 'lane-q · fork 2/3' '(a)')"
python3 - "$HO/QUESTIONS-lane-q.md" <<'EOF'
import sys; p = sys.argv[1]; s = open(p).read()
s = s.replace("## 2. Which port", "## 0. A fork added since\nIs this new? (a) yes (b) no\n\n## 2. Which port")
s = s.replace("# Questions: lane-q\n", "# Questions: lane-q\n\nThe lane wrote this line after the forks were sent.\n")
open(p, "w").write(s)
EOF
press "$A2" "$M2"; poll
check "the answer is in fork 2, not in the fork now above it" \
  [ "$(fork_of "$HO/QUESTIONS-lane-q.md" '**Answer (user via telegram, '"$DATE"'):** (a)')" = "## 2. Which port" ]
check "the lane's own line survived" grep -q "The lane wrote this line" "$HO/QUESTIONS-lane-q.md"
check "the message says it was re-applied" grep -q "the file had changed since this was sent; applied to the same fork" <<<"$(last_edit)"
check "..and the log" grep -q "= (a) (re-applied)" "$NLOG"

echo "== a stale button: the fork was answered at the machine meanwhile"
say /pending; poll
M0="$(mid_of 'lane-q · fork 1/2')"
check "/pending re-issues the forks still open, with buttons" \
  [ "$(labels_of 'lane-q · fork 1/2')" = '[["(a)","(b)"],["✎ type"]]' ]
check "..the fork the lane added among them" grep -q "0. A fork added since" <<<"$(sb_calls sendMessage | jq -rs '[.[] | select(.text|test("lane-q · fork 1/2"))] | last | .text')"
A0="$(cb_of 'lane-q · fork 1/2' '(a)')"
python3 - "$REPO" "$HO/QUESTIONS-lane-q.md" "$DATE" <<'EOF'
import sys; sys.path.insert(0, sys.argv[1]); import muxhandovers as mh
p = sys.argv[2]; s = open(p).read()
f = next(f for f in mh.parse_forks(s) if f["title"].startswith("0."))
open(p, "w").write(mh.write_answer(s, f["id"], "(b) -- from the dashboard", sys.argv[3]))
EOF
press "$A0" "$M0"; poll
check "not written over" bash -c '! grep -q "via telegram, .*:\*\* (a)$" <(sed -n "/^## 0\./,/^## 2\./p" "$1")' _ "$HO/QUESTIONS-lane-q.md"
check "..the press says so" [ "$(cb_said)" = "already answered at the machine" ]
check "..and so does the message" grep -q "already answered at the machine .*(b) -- from the dashboard" <<<"$(last_edit)"

echo "== a typed answer: ✎ type is a ForceReply, and the reply is written"
M3="$(mid_of 'lane-q · fork 2/2')"
press "$(cb_of 'lane-q · fork 2/2' '✎ type')" "$M3"; poll
check "a ForceReply was sent" [ "$(sb_calls sendMessage | tail -1 | jq -r '.reply_markup | fromjson | .force_reply')" = true ]
check "..as a reply to the fork" [ "$(sb_calls sendMessage | tail -1 | jq -r .reply_to_message_id)" = "$M3" ]
check "..naming the fork" grep -q "your answer to: 3. Which log" <<<"$(last_text)"
FR="$(sb_ncalls sendMessage | awk '{print 1000 + $1}')"
: > "$HOME/fake-claude.keys"
reply "$FR" "journal, rotated daily"; poll; sleep 1.5
check "the typed text is the answer, inside fork 3" \
  [ "$(fork_of "$HO/QUESTIONS-lane-q.md" "**Answer (user via telegram, $DATE):** journal, rotated daily")" = "## 3. Which log" ]

echo "== the last fork: the file is marked ANSWERED, and the idle lane is told"
check "the marker is in the file" grep -q '^\*\*ANSWERED' "$HO/QUESTIONS-lane-q.md"
check "..once" [ "$(grep -c 'ANSWERED' "$HO/QUESTIONS-lane-q.md")" = 1 ]
check "the fork message says so" grep -q "marked ANSWERED · told ➥lane-q" <<<"$(last_edit)"
check "the typed reply got the same note back" grep -q "✓ your answer written from the phone" <<<"$(last_text)"
typed="$(while IFS= read -r k; do eval "printf '%s' $k"; done < "$HOME/fake-claude.keys")"
check "the lane's pane got the sentence" grep -qF "Your questions are answered in $HO/QUESTIONS-lane-q.md" <<<"$typed"
say /questions; poll
check "/questions no longer lists it" bash -c '! grep -q "lane-q ·" <<<"$1"' _ "$(last_text)"

echo "== a plain reply to the fork message works too; the legacy folder is marked by muxhandovers"
press "$(jq -r '.inline_keyboard[2][0].callback_data' <<<"$Q")"; poll
ML="$(mid_of 'legacy · fork 1/1')"
reply "$ML" "drop it" 999; poll
check "a reply from the WRONG chat is dropped" bash -c '! grep -q "drop it" "$1"' _ "$LEG/QUESTIONS-legacy.md"
reply "$ML" "drop it"; poll
check "the plain reply is written" grep -qx "\*\*Answer (user via telegram, $DATE):\*\* drop it" "$LEG/QUESTIONS-legacy.md"
check "..and the file marked" grep -q "^\*\*ANSWERED $DATE\*\*" "$LEG/QUESTIONS-legacy.md"
check "a lane with no window is not told, and the note does not pretend" \
  bash -c '! grep -q "told" <<<"$1"' _ "$(last_edit)"
reply 999999 "hello?"; poll
check "a reply that answers nothing gets a hint" grep -q "reply to its message" <<<"$(last_text)"

echo "== INBOUND off: a press writes nothing"
setkey MUXTOPUS_NOTIFY_INBOUND off
printf '# Q\n\n## 1. Off fork\n(a) x (b) y\n' > "$HO/QUESTIONS-off.md"
python3 "$T" fork-message --path "$HO/QUESTIONS-off.md" \
  --fork "$(python3 "$T" questions | jq -r 'select(.slug=="off") | .forks[0].id')" --title "personal · off · fork 1/1" >/dev/null
press "$(cb_of 'off · fork 1/1' '(a)')" "$(mid_of 'off · fork 1/1')"; poll
check "refused" grep -q "may not answer" <<<"$(cb_said)"
check "the file is untouched" bash -c '! grep -q Answer "$1"' _ "$HO/QUESTIONS-off.md"
setkey MUXTOPUS_NOTIFY_INBOUND on

echo "== the watchdog's push carries the same buttons"
pass                                   # QUESTIONS is off: what exists is recorded quietly
setkey MUXTOPUS_NOTIFY_QUESTIONS on
printf '\n## 2. Pushed fork\n(a) one (b) two\n' >> "$HO/QUESTIONS-off.md"
pass
check "the new fork arrived with its buttons" [ "$(labels_of 'off · fork 1/1')" = '[["(a)","(b)"],["✎ type"]]' ]
check "..its text is the fork" grep -q "Pushed fork" <<<"$(sb_calls sendMessage | tail -1 | jq -r .text)"
press "$(cb_of 'off · fork 1/1' '(b)')" "$(mid_of 'off · fork 1/1')"; poll
check "..and a press on it is written" \
  [ "$(fork_of "$HO/QUESTIONS-off.md" "**Answer (user via telegram, $DATE):** (b)")" = "## 2. Pushed fork" ]

sb_done
