#!/usr/bin/env bash
# Phase 3: muxtelegram -- the phone answers a prompt.
# Sandbox tmux (-L mxnotify) + fake claude + fake Bot API; the watchdog issues
# the buttons, scripted callbacks come back through getUpdates, and the fake
# claude records every key that reaches its pane.
#   bash tests/test_notify_inbound.sh
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"; T="$REPO/muxtelegram.py"
FIX="$REPO/tests/fixtures/prompts"
ST="$XDG_STATE_HOME/claude-watchdog"; SH="$XDG_STATE_HOME/muxtopus-notify"
NLOG="$ST/notify.log"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"

setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
pass() { "$W" --once >/dev/null 2>&1; }
poll() { python3 "$T" poll; }
screen() { if [ -n "${1:-}" ]; then cp "$1" "$HOME/fake-screen"; else printf '● done.\n\n────\n❯ \n────\n' > "$HOME/fake-screen"; fi; sleep 0.8; }
keys() { cat "$HOME/fake-claude.keys" 2>/dev/null; }
last_kb() { sb_calls sendMessage | jq -c 'select(.reply_markup) | .reply_markup | fromjson' | tail -1; }
cb_of() { last_kb | jq -r --arg l "$1" '.inline_keyboard[][] | select(.text==$l) | .callback_data'; }
mid_of_last() { sb_calls sendMessage | grep -c '' | awk '{print 1000 + $1}'; }   # fake ids count up from 1001
UID_N=0
press() {  # press DATA [CHAT] [FROM]
  UID_N=$(( UID_N + 1 ))
  sb_update "$(jq -cn --arg d "$1" --argjson c "${2:-4242}" --argjson f "${3:-4242}" --argjson u "$UID_N" \
    '{update_id:$u, callback_query:{id:("q"+($u|tostring)), from:{id:$f}, message:{message_id:1001, chat:{id:$c}, text:"personal · needs you"}, data:$d}}')"
}
waiting_cycle() { screen "$1"; pass; pass; }

screen
tmux new-session -d -s claude -n '➥lane-a' -x 100 -y 40 "cd $HOME && claude"
for i in $(seq 50); do ls "$HOME/.claude/sessions/"*.json >/dev/null 2>&1 && break; sleep 0.1; done
PANE="$(tmux list-panes -t claude -F '#{pane_id}' | head -1)"
"$W" --on >/dev/null
pass

echo "== the waiting message carries Yes / No / More"
waiting_cycle "$FIX/rm-dangerous.txt"
kb="$(last_kb)"
check "three buttons" [ "$(jq -c '[.inline_keyboard[][] .text]' <<<"$kb")" = '["Yes","No","More"]' ]
check "callback data is an opaque id (< 64 bytes)" bash -c '[ ${#1} -le 64 ] && [[ "$1" =~ ^[0-9a-f]+$ ]]' _ "$(cb_of Yes)"
check "one pending per button" [ "$(ls "$SH/pending" | wc -l)" = 3 ]
check "the pending records the pane and the prompt sha" [ "$(jq -r .pane "$SH/pending/$(cb_of Yes).json")" = "$PANE" ]
check "sent.tsv keeps the message_id" grep -q "^waiting:$PANE	.*	[0-9][0-9]*$" "$ST/notify/sent.tsv"

echo "== a press from the WRONG chat is dropped and logged"
press "$(cb_of Yes)" 999 999; poll; sleep 0.5
check "no key reached the pane" [ -z "$(keys)" ]
check "logged as dropped" grep -q "dropped a callback from chat 999" "$NLOG"
check "not even answered" [ "$(sb_ncalls answerCallbackQuery)" = 0 ]
press "$(cb_of Yes)" 4242 777; poll; sleep 0.5
check "right chat, wrong sender: dropped" [ -z "$(keys)" ]

echo "== the right chat: Yes -> the pane receives 1"
press "$(cb_of Yes)"; poll; sleep 1
check "the pane received 1" [ "$(keys)" = 1 ]
check "the press was answered" [ "$(sb_ncalls answerCallbackQuery)" = 1 ]
check "the message was edited to say so" grep -q "Yes sent from the phone" <<<"$(sb_calls editMessageText | jq -r .text)"
check "the whole group is consumed" [ "$(ls "$SH/pending" | wc -l)" = 0 ]
check "notify.log has the line" grep -q "Yes sent to $PANE" "$NLOG"
: > "$HOME/fake-claude.keys"

echo "== a second press of the same (used) button does nothing"
press "$(cb_of No)"; poll; sleep 0.5
check "no Escape typed" [ -z "$(keys)" ]
check "answered as expired or used" grep -q "unknown id" "$NLOG"

echo "== No -> Escape; More -> the lines above, and the group survives More"
screen; pass
waiting_cycle "$FIX/edit-file.txt"
more="$(cb_of More)"; no="$(cb_of No)"
n="$(sb_ncalls sendMessage)"
press "$more"; poll
check "More replied" [ "$(sb_ncalls sendMessage)" = $(( n + 1 )) ]
check "as a reply to the message" [ "$(sb_calls sendMessage | tail -1 | jq -r .reply_to_message_id)" = 1001 ]
check "More keeps the buttons alive" [ -f "$SH/pending/$no.json" ]
press "$no"; poll; sleep 1
check "No typed Escape" grep -qx "\$'\\\\E'" <<<"$(keys)"
: > "$HOME/fake-claude.keys"

echo "== a stale prompt_sha: not sent, the message edited"
screen; pass
waiting_cycle "$FIX/rm-dangerous.txt"
yes="$(cb_of Yes)"
screen "$FIX/trust-folder.txt"               # a DIFFERENT prompt now, same pane
press "$yes"; poll; sleep 0.5
check "nothing typed into the pane" [ -z "$(keys)" ]
check "edited: already answered at the machine" grep -q "already answered at the machine" <<<"$(sb_calls editMessageText | jq -r .text | tail -3)"
screen; pass

echo "== a prompt whose option 1 changes a policy: no Yes button, and a forged yes is refused"
waiting_cycle "$FIX/plan-approval.txt"
check "only No and More" [ "$(last_kb | jq -c '[.inline_keyboard[][] .text]')" = '["No","More"]' ]
forged="$(cb_of No)"
jq '.action="yes"' "$SH/pending/$forged.json" > "$SH/x.json" && mv "$SH/x.json" "$SH/pending/$forged.json"
press "$forged"; poll; sleep 0.5
check "the forged yes typed nothing" [ -z "$(keys)" ]
check "and says why" grep -q "not a plain yes" "$NLOG"
screen; pass

echo "== an expired id"
waiting_cycle "$FIX/rm-dangerous.txt"
yes="$(cb_of Yes)"
jq '.created -= 90000' "$SH/pending/$yes.json" > "$SH/x.json" && mv "$SH/x.json" "$SH/pending/$yes.json"
press "$yes"; poll; sleep 0.5
check "expired: nothing typed" [ -z "$(keys)" ]
check "expired: logged" grep -q "expired id $yes" "$NLOG"
check "expired: the message says so" grep -q "expired" <<<"$(sb_calls editMessageText | jq -r .text | tail -2)"
check "expired: the group is gone" [ ! -f "$SH/pending/$yes.json" ]

echo "== the prompt clears at the machine: the message loses its buttons"
screen; pass; pass
waiting_cycle "$FIX/rm-dangerous.txt"
yes="$(cb_of Yes)"
screen; pass
check "retired when it left the screen" [ ! -f "$SH/pending/$yes.json" ]
check "edited: answered at the machine" grep -q "answered at the machine" <<<"$(sb_calls editMessageText | jq -r .text | tail -2)"

echo "== re-issue supersedes: a new message for the same pane retires the old id"
waiting_cycle "$FIX/rm-dangerous.txt"
old="$(cb_of Yes)"
python3 "$T" prompt-message --pane "$PANE" --sha "$(jq -r .prompt_sha "$SH/pending/$old.json")" --yes 1 --more 1 --title "t" --body "b" >/dev/null
check "the old id is gone" [ ! -f "$SH/pending/$old.json" ]
check "the old message says superseded" grep -q "superseded" <<<"$(sb_calls editMessageText | jq -r .text | tail -2)"
press "$old"; poll; sleep 0.5
check "the old button types nothing" [ -z "$(keys)" ]
screen; pass

echo "== a fork callback whose message is gone is refused (answering forks: test_notify_forks.sh)"
mkdir -p "$SH/pending" "$SH/groups"
printf '{"id":"abcdef01","group":"g1","kind":"fork","action":"opt-a","target":"fork:x#1","created":%s}' "$(date +%s)" > "$SH/pending/abcdef01.json"
press abcdef01; poll
check "answered: expired or already used" [ "$(sb_calls answerCallbackQuery | tail -1 | jq -r .text)" = "expired or already used" ]

echo "== INBOUND off: no buttons"
setkey MUXTOPUS_NOTIFY_INBOUND off
waiting_cycle "$FIX/rm-dangerous.txt"
check "no keyboard on the new message" [ "$(sb_calls sendMessage | tail -1 | jq -r '.reply_markup // "none"')" = none ]
setkey MUXTOPUS_NOTIFY_INBOUND on
screen; pass

echo "== two daemons, one lock: every update handled exactly once"
mkdir -p "$HOME/.claude-work/sessions"
setkey WATCHDOG_INTERVAL 1
waiting_cycle "$FIX/edit-file.txt"
more="$(cb_of More)"
: > "$FAKE/calls.jsonl"
"$W" --daemon >/dev/null 2>&1 & d1=$!; SB_PIDS+=("$d1")
"$W" --profile work --daemon >/dev/null 2>&1 & d2=$!; SB_PIDS+=("$d2")
for i in 1 2 3 4 5 6 7 8; do press "$more"; sleep 0.3; done
for i in $(seq 60); do [ "$(sb_ncalls answerCallbackQuery)" -ge 8 ] && break; sleep 0.25; done
sleep 3
check "8 presses -> 8 answers" [ "$(sb_ncalls answerCallbackQuery)" = 8 ]
check "8 presses -> 8 replies, none twice" [ "$(sb_calls sendMessage | jq -r 'select(.reply_to_message_id) | .reply_to_message_id' | grep -c '')" = 8 ]
check "both daemons polled" [ "$(sb_ncalls getUpdates)" -ge 4 ]
ids="$(grep -o 'update [0-9]* read by the [a-z]* watchdog' "$NLOG" | awk '$2>=UIDMIN' UIDMIN="$(( UID_N - 7 ))")"
check "each of the 8 updates read exactly once" [ "$(awk '{print $2}' <<<"$ids" | sort | uniq -d | grep -c .)" = 0 ] 
check "... and all 8 were read" [ "$(awk '{print $2}' <<<"$ids" | sort -u | grep -c .)" = 8 ]
echo "  (read by: $(awk '{print $6}' <<<"$ids" | sort | uniq -c | paste -sd' '))"
check "8 distinct queries answered" [ "$(sb_calls answerCallbackQuery | jq -r .callback_query_id | sort -u | grep -c '')" = 8 ]
kill "$d1" "$d2"; wait "$d1" "$d2" 2>/dev/null
check "daemons stopped by pid" bash -c '! kill -0 "$1" 2>/dev/null && ! kill -0 "$2" 2>/dev/null' _ "$d1" "$d2"
check "no token in notify.log" bash -c '! grep -q "111:GOOD" "$1"' _ "$NLOG"

sb_done
