#!/usr/bin/env bash
# Phase 3b: muxtelegram -- /status, /pending and the bot's menu.
# Sandbox tmux (-L mxnotify) + fake claude + fake Bot API, with EVERY event
# switch off: the phone still finds out, by asking.
#   bash tests/test_notify_pull.sh
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"; T="$REPO/muxtelegram.py"
FIX="$REPO/tests/fixtures/prompts"
ST="$XDG_STATE_HOME/claude-watchdog"; SH="$XDG_STATE_HOME/muxtopus-notify"
HO="$HOME/.code/handovers"; SC="$HOME/.code/schedules"
NLOG="$ST/notify.log"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"

setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
pass() { "$W" --once >/dev/null 2>&1; }
poll() { python3 "$T" poll; }
screen() { if [ -n "${1:-}" ]; then cp "$1" "$HOME/fake-screen"; else printf '● done.\n\n────\n❯ \n────\n' > "$HOME/fake-screen"; fi; sleep 0.8; }
keys() { cat "$HOME/fake-claude.keys" 2>/dev/null; }
texts() { sb_calls sendMessage | jq -r .text; }
last_text() { sb_calls sendMessage | tail -1 | jq -r .text; }
UID_N=0
say() {  # say TEXT [CHAT]
  UID_N=$(( UID_N + 1 ))
  sb_update "$(jq -cn --arg t "$1" --argjson c "${2:-4242}" --argjson u "$UID_N" \
    '{update_id:$u, message:{message_id:(500+$u), from:{id:$c}, chat:{id:$c, type:"private"}, text:$t}}')"
}
press() {
  UID_N=$(( UID_N + 1 ))
  sb_update "$(jq -cn --arg d "$1" --argjson u "$UID_N" --argjson m "${2:-1001}" \
    '{update_id:$u, callback_query:{id:("q"+($u|tostring)), from:{id:4242}, message:{message_id:$m, chat:{id:4242}, text:"x"}, data:$d}}')"
}
kb_of_last() { sb_calls sendMessage | jq -c 'select(.reply_markup) | .reply_markup | fromjson' | tail -1; }
cb_of() { kb_of_last | jq -r --arg l "$1" '.inline_keyboard[][] | select(.text|startswith($l)) | .callback_data'; }

for k in WAITING QUESTIONS TROUBLE DONE; do setkey "MUXTOPUS_NOTIFY_$k" off; done
screen
tmux new-session -d -s claude -n '➥lane-a' -x 100 -y 40 "cd $HOME && claude"
for i in $(seq 50); do ls "$HOME/.claude/sessions/"*.json >/dev/null 2>&1 && break; sleep 0.1; done
PANE="$(tmux list-panes -t claude -F '#{pane_id}' | head -1)"
"$W" --on >/dev/null
# the schedule: one stalled, one blocked for 3h, one plain waiting
printf 'type: bogus\nat: now\ncwd: %s\nstatus: pending\n---\nx\n' "$HOME" > "$SC/bad.md"
printf '# STATUS: lane-x\nrunning\n' > "$HO/STATUS-lane-x.md"
printf 'type: work\nat: now\nafter: lane-x\ncwd: %s\nstatus: pending\n---\ncarry on\n' "$HOME" > "$SC/held.md"
printf 'type: work\nat: 23:59\ncwd: %s\nstatus: pending\n---\nlater\n' "$HOME" > "$SC/later.md"
printf '# Q\n\n## 1. Which clock\n(a) host\n' > "$HO/QUESTIONS-lane-q.md"
screen "$FIX/rm-dangerous.txt"; pass; pass
sed -i "s/^held.md\t.*/held.md\t$(( $(date +%s) - 3*3600 ))/" "$ST/notify/blocked.tsv"

echo "== every push switch off: nothing was pushed"
check "status.tsv says waiting" grep -q "	waiting	" "$ST/status.tsv"
check "no push at all" [ "$(sb_ncalls sendMessage)" = 0 ]

echo "== setMyCommands: once, and again only when the list changes"
poll; poll; poll
check "registered once over three polls" [ "$(sb_ncalls setMyCommands)" = 1 ]
echo stale > "$SH/commands.sha"
poll
check "registered again when the stored hash differs" [ "$(sb_ncalls setMyCommands)" = 2 ]
poll
check "and not again after that" [ "$(sb_ncalls setMyCommands)" = 2 ]

echo "== a command from a wrong chat is dropped"
say /status 999; poll
check "no reply" [ "$(sb_ncalls sendMessage)" = 0 ]
check "logged" grep -q "dropped a message from chat 999" "$NLOG"

echo "== /status: the numbers are the sandbox's"
say /status; poll
st="$(last_text)"
w="$(awk -F'\t' '$6=="waiting"' "$ST/status.tsv" | grep -c .)"
pend="$(grep -c . "$ST/sched-why.tsv")"
blk="$(awk -F'\t' '$2=="blocked"' "$ST/sched-why.tsv" | grep -c .)"
stl="$(awk -F'\t' '$2=="stalled"' "$ST/sched-why.tsv" | grep -c .)"
check "sessions: $w needs you" grep -q "^sessions: $w needs you$" <<<"$st"
check "schedule: $pend pending · $blk blocked · $stl stalled" grep -q "^schedule: $pend pending · $blk blocked · $stl stalled$" <<<"$st"
check "handovers: 1 open · questions: 1 unanswered" grep -q "^handovers: 1 open · questions: 1 unanswered$" <<<"$st"
check "the heartbeat age" grep -q "^watchdog: scanned [0-9]*s ago$" <<<"$st"
check "the first command of a burst says the latency" grep -q "within one watchdog pass" <<<"$st"
check "buttons carry the counts" [ "$(kb_of_last | jq -c '[.inline_keyboard[][] .text]')" = "[\"Needs you ($w)\",\"Questions (1)\",\"Blocked ($blk)\",\"Refresh\"]" ]
blocked_btn="$(cb_of Blocked)"; refresh_btn="$(cb_of Refresh)"
smid="$(( 1000 + $(sb_ncalls sendMessage) ))"
say /status; poll
check "the second command does not repeat the latency note" bash -c '! grep -q "within one watchdog pass" <<<"$1"' _ "$(last_text)"

echo "== /pending with every switch OFF re-issues the prompt; the old button is refused"
say /pending; poll
old_yes="$(sb_calls sendMessage | jq -r 'select(.text|test("needs you")) | .reply_markup | fromjson | .inline_keyboard[0][0].callback_data' | tail -1)"
check "a prompt message with buttons" [ -f "$SH/pending/$old_yes.json" ]
check "the fork half says not yet" grep -q "Answering a fork from the phone: not yet" <<<"$(texts)"
check "trouble lists the stalled entry with its why" grep -q "stalled: bad.md -- STALLED: type must be plan or work" <<<"$(texts)"
check "trouble lists the long-blocked entry" grep -q "blocked: held.md -- blocked: waiting for lane-x" <<<"$(texts)"
say /pending; poll
new_yes="$(sb_calls sendMessage | jq -r 'select(.text|test("needs you")) | .reply_markup | fromjson | .inline_keyboard[0][0].callback_data' | tail -1)"
check "a NEW id" bash -c '[ -n "$1" ] && [ "$1" != "$2" ]' _ "$new_yes" "$old_yes"
check "the old id is retired" [ ! -f "$SH/pending/$old_yes.json" ]
check "the old message edited: superseded" grep -q "superseded" <<<"$(sb_calls editMessageText | jq -r .text)"
press "$old_yes"; poll; sleep 0.5
check "the OLD button types nothing" [ -z "$(keys)" ]
check "and is answered as used" grep -q "unknown id" "$NLOG"
press "$new_yes"; poll; sleep 1
check "the NEW button works: the pane got 1" [ "$(keys)" = 1 ]
: > "$HOME/fake-claude.keys"

echo "== /questions: not yet"
say /questions; poll
check "lists the file" grep -q "personal · lane-q · 1 fork(s)" <<<"$(last_text)"
check "and says not yet" grep -q "not yet" <<<"$(last_text)"

echo "== /blocked and /windows"
say /blocked; poll
check "/blocked gives each entry's why" grep -q "held.md · blocked" <<<"$(last_text)"
check "/blocked includes a plain wait" grep -q "later.md · waiting" <<<"$(last_text)"
screen "$FIX/trust-folder.txt"; pass; pass
say /windows; poll
check "/windows: a line per session" grep -q "personal · ➥lane-a · needs you" <<<"$(texts)"
check "/windows: the needs-you row brings its buttons" grep -q "Do you trust the files" <<<"$(sb_calls sendMessage | tail -1 | jq -r .text)"
say /help; poll
check "/help" grep -q "^/mute 2h" <<<"$(last_text)"
say /frobnicate; poll
check "unknown command" grep -q "unknown command /frobnicate" <<<"$(last_text)"

echo "== the /status buttons"
press "$blocked_btn" "$smid"; poll
check "Blocked (n) sends the blocked list" grep -q "not launching:" <<<"$(last_text)"
n_edit="$(sb_ncalls editMessageText)"
press "$refresh_btn" "$smid"; poll
check "Refresh edits the status message in place" [ "$(sb_calls editMessageText | tail -1 | jq -r .message_id)" = "$smid" ]
check "with a fresh keyboard" [ "$(sb_calls editMessageText | tail -1 | jq -r '.reply_markup | fromjson | .inline_keyboard[0] | length')" = 4 ]

echo "== /mute suppresses a push, not a pull"
screen; pass; pass
say "/mute 2h"; poll
check "mute acknowledged" grep -q "pushes muted until" <<<"$(last_text)"
check "the mute file holds a future time" [ "$(cat "$SH/mute")" -gt "$(date +%s)" ]
setkey MUXTOPUS_NOTIFY_WAITING on
setkey MUXTOPUS_NOTIFY_TROUBLE on
n="$(sb_ncalls sendMessage)"
screen "$FIX/edit-file.txt"; pass; pass
check "muted: the waiting push is not sent" [ "$(sb_ncalls sendMessage)" = "$n" ]
check "muted: the trouble push is not sent either" bash -c '! grep -q "^personal · stalled: bad.md" <<<"$1"' _ "$(texts)"
check "muted: logged" grep -q "muted: personal · needs you" "$NLOG"
check "muted: the key is recorded, so unmute is no flood" grep -q "^waiting:$PANE	" "$ST/notify/sent.tsv"
say /pending; poll
check "muted: a pull still answers with the prompt" [ "$(sb_ncalls sendMessage)" -gt "$n" ]
check "... and it is the prompt" grep -q "make this edit" <<<"$(texts | tail -40)"
say /status; poll
check "/status says pushes are muted" grep -q "pushes muted until" <<<"$(last_text)"
say /unmute; poll
check "unmuted" [ ! -f "$SH/mute" ]

sb_done
