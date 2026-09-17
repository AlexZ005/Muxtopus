#!/usr/bin/env bash
# Phase 1: claude-notify.sh --setup, --buttons, --edit, a swappable API base.
# Everything against tests/fake_telegram.py in a sandbox HOME.
#   bash tests/test_notify_setup.sh
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
N="$REPO/claude-notify.sh"
export NOTIFY_SETUP_WAIT=20 NOTIFY_SETUP_POLL=0.5 NOTIFY_SETUP_CLOSE=0

echo "== unconfigured"
out="$("$N" "T" "B" 2>&1)"; rc=$?
check "unconfigured send exits 0" [ "$rc" = 0 ]
check "and says why" grep -q "no notification backend" <<<"$out"
"$N" --status >/dev/null 2>&1; check "--status unconfigured exits 1" [ $? = 1 ]
check "nothing reached the API" [ ! -s "$FAKE/calls.jsonl" ]

echo "== the guide: a bad token, then a good one, then waiting for START"
# Script the /start to arrive while the guide is already polling.
( sleep 2; sb_update '{"message":{"message_id":1,"from":{"id":4242},"chat":{"id":4242,"type":"private","first_name":"Alex"},"text":"/start"}}'
  # and the press of the test button, once it has been sent
  for i in $(seq 60); do
    cb="$(sb_calls sendMessage | jq -r '.reply_markup // empty | fromjson | .inline_keyboard[0][0].callback_data' 2>/dev/null | tail -1)"
    [ -n "$cb" ] && break; sleep 0.3
  done
  sb_update "$(jq -cn --arg cb "$cb" '{callback_query:{id:"q1",from:{id:4242},message:{message_id:1001,chat:{id:4242}},data:$cb}}')"
) & presser=$!
out="$("$N" --setup 2>&1 <<'EOF'
1
999:BAD
111:GOOD
y
1
EOF
)"; rc=$?
wait "$presser"
check "guide exits 0" [ "$rc" = 0 ]
check "bad token refused with Telegram's words" grep -q "refused that token: Unauthorized" <<<"$out"
check "good token echoes the bot" grep -q '@muxfake_bot' <<<"$out"
check "it waited, then found the chat" grep -q "found you: Alex (chat 4242)" <<<"$out"
check "conf written" grep -qx "TELEGRAM_CHAT=4242" "$CLAUDE_NOTIFY_CONF"
check "conf is 0600" [ "$(stat -c %a "$CLAUDE_NOTIFY_CONF")" = 600 ]
kb="$(sb_calls sendMessage | tail -1 | jq -r '.reply_markup // empty')"
check "test message has a keyboard" [ "$(jq -r '.inline_keyboard[0][0].text' <<<"$kb")" = "It works" ]
check "the press was seen" grep -q "buttons work end to end" <<<"$out"
check "the press was answered" [ "$(sb_ncalls answerCallbackQuery)" = 1 ]
check "the test message was edited" grep -q "the phone answered" <<<"$(sb_calls editMessageText)"
check "offset remembered for the poller" [ -s "$XDG_STATE_HOME/muxtopus-notify/offset" ]
check "the privacy sentence is said" grep -q "passes through Telegram's servers" <<<"$out"
# The list itself lives in muxtelegram.COMMANDS; asking that module what it
# is keeps this a test of "--setup registers the menu" rather than one more
# copy of the list to update whenever a command is added.
WANT_CMDS="$(python3 -c 'import sys; sys.path.insert(0, "'"$REPO"'"); import muxtelegram; print(" ".join(c for c, _ in muxtelegram.COMMANDS))')"
check "the bot's menu was registered" [ "$(sb_calls setMyCommands | jq -r '.commands | fromjson | map(.command) | join(" ")')" = "$WANT_CMDS" ]
check "tell me: no switch written" bash -c '! grep -q "NOTIFY_WAITING=off" <<<"$1"' _ "$out"
check "no token in the notify log" bash -c '! grep -q GOOD "$1"' _ "$XDG_STATE_HOME/claude-watchdog/notify.log"

echo "== only when I ask: every push switch off, pull still offered"
rm -f "$CLAUDE_NOTIFY_CONF"
( sleep 1; sb_update '{"message":{"message_id":2,"from":{"id":4242},"chat":{"id":4242,"type":"private","first_name":"Alex"},"text":"/start"}}' ) & starter=$!
out="$(NOTIFY_SETUP_WAIT=3 "$N" --setup 2>&1 <<'EOF'
1
111:GOOD
y
2
EOF
)"
wait "$starter"
for k in WAITING QUESTIONS TROUBLE DONE; do
  check "pull: MUXTOPUS_NOTIFY_$k=off named (the store has no row for it until notify-dash)" grep -q "MUXTOPUS_NOTIFY_$k=off" <<<"$out"
done
check "pull: the menu is still registered" grep -q "menu now offers /status" <<<"$out"
rm -f "$CLAUDE_NOTIFY_CONF".bak-*
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"; chmod 600 "$CLAUDE_NOTIFY_CONF"

echo "== /mute holds a push back, never an edit"
mkdir -p "$XDG_STATE_HOME/muxtopus-notify"
echo $(( $(date +%s) + 600 )) > "$XDG_STATE_HOME/muxtopus-notify/mute"
n="$(sb_ncalls sendMessage)"
"$N" "Muted" "push" >/dev/null
check "muted: the push is not sent" [ "$(sb_ncalls sendMessage)" = "$n" ]
check "muted: logged" grep -q "MUTED: Muted" "$XDG_STATE_HOME/claude-watchdog/notify.log"
"$N" --edit 1001 "T" "an edit" >/dev/null
check "muted: an edit still goes" grep -q "an edit" <<<"$(sb_calls editMessageText | jq -r .text)"
echo 1 > "$XDG_STATE_HOME/muxtopus-notify/mute"
"$N" "Unmuted" "push" >/dev/null
check "a mute in the past holds nothing" [ "$(sb_ncalls sendMessage)" = $(( n + 1 )) ]
rm -f "$XDG_STATE_HOME/muxtopus-notify/mute"

echo "== reconfigure keeps a .bak"
# The server line is NOT optional here: the default is the real ntfy.sh.
out="$("$N" --setup 2>&1 <<EOF
r
2
sandbox-topic
$TELEGRAM_API
EOF
)"; rc=$?
check "reconfigure exits 0" [ "$rc" = 0 ]
check "a .bak-<stamp> kept" bash -c 'ls "$1".bak-* >/dev/null 2>&1' _ "$CLAUDE_NOTIFY_CONF"
check ".bak is 0600 too" [ "$(stat -c %a "$(ls "$CLAUDE_NOTIFY_CONF".bak-* | head -1)")" = 600 ]
check "the .bak holds the old telegram conf" grep -qx "BACKEND=telegram" "$(ls "$CLAUDE_NOTIFY_CONF".bak-* | head -1)"
check "the guide's own test went to the fake ntfy" [ "$(sb_calls ntfy | tail -1 | jq -r ._body)" = "Notifications are working." ]

echo "== ntfy path still sends; buttons degrade to a sentence"
: > "$FAKE/calls.jsonl"
"$N" --buttons 'Yes=a|No=b' "Title" "Body"; rc=$?
check "ntfy exits 0" [ "$rc" = 0 ]
check "ntfy got the title" [ "$(sb_calls ntfy | jq -r .title)" = Title ]
check "ntfy body says answer at the machine" grep -q "answer at the machine" <<<"$(sb_calls ntfy | jq -r ._body)"

echo "== pushbullet path still sends"
printf 'BACKEND=pushbullet\nPUSHBULLET_TOKEN=o.sandbox\n' > "$CLAUDE_NOTIFY_CONF"
: > "$FAKE/calls.jsonl"
"$N" "PB" "body"; check "pushbullet exits 0" [ $? = 0 ]
check "pushbullet got a note" [ "$(sb_calls pushbullet | jq -r .type)" = note ]

echo "== telegram: --buttons, --edit, --reply-to, message_id on stdout"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"
: > "$FAKE/calls.jsonl"
mid="$("$N" --buttons 'Yes=p1|No=p2||More=p3' "T" "body")"
check "prints the message_id" grep -qx "[0-9][0-9]*" <<<"$mid"
kb="$(sb_calls sendMessage | tail -1 | jq -r .reply_markup)"
check "two rows, data after the last =" [ "$(jq -c '.inline_keyboard | map(map(.callback_data))' <<<"$kb")" = '[["p1","p2"],["p3"]]' ]
"$N" --edit "$mid" "T" "done" >/dev/null
check "--edit calls editMessageText on that id" [ "$(sb_calls editMessageText | tail -1 | jq -r .message_id)" = "$mid" ]
"$N" --reply-to "$mid" "T" "more" >/dev/null
check "--reply-to sets reply_to_message_id" [ "$(sb_calls sendMessage | tail -1 | jq -r .reply_to_message_id)" = "$mid" ]
long="$(printf 'é%.0s' $(seq 5000))"
"$N" "T" "$long" >/dev/null
check "a long body is cut by characters" [ "$(sb_calls sendMessage | tail -1 | jq -r '.text | length')" -le 4000 ]
out="$("$N" --status)"
check "--status names the last send" grep -q "last sent: " <<<"$out"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=403\n' > "$CLAUDE_NOTIFY_CONF"
out="$("$N" --test 2>&1)"
check "--test shows Telegram's refusal" grep -q "can't initiate conversation" <<<"$out"

echo "== the environment beats a conf that names the real API"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\nTELEGRAM_API=https://api.telegram.org\n' > "$CLAUDE_NOTIFY_CONF"
: > "$FAKE/calls.jsonl"
"$N" "T" "b" >/dev/null
check "still the fake" [ "$(sb_ncalls sendMessage)" = 1 ]

sb_done
