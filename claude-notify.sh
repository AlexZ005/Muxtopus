#!/usr/bin/env bash
# claude-notify.sh -- send a short message to the phone.
#
#   claude-notify.sh "Title" "body text"
#   claude-notify.sh --buttons 'Yes=id1|No=id2' "Title" "body"
#                                    an inline keyboard (telegram; '||' starts
#                                    a new row); prints the sent message_id
#   claude-notify.sh --edit MSGID [--buttons ...] "Title" "body"
#   claude-notify.sh --reply-to MSGID "Title" "body"
#   claude-notify.sh --setup         the interactive guide (Settings opens it)
#   claude-notify.sh --test
#   claude-notify.sh --status        which backend is configured, last send
#   claude-notify.sh --telegram-chat TOKEN   which chats have messaged a bot
#
# CONFIG lives OUTSIDE this repo, at ~/.config/claude-notify.conf, because it
# holds tokens. --setup writes it; by hand, one backend:
#
#   # ntfy -- no account, no token; the topic name IS the address, so pick
#   # something unguessable. Install the ntfy app and subscribe to it.
#   BACKEND=ntfy
#   NTFY_TOPIC=deck-a7f3k2-alerts
#   NTFY_SERVER=https://ntfy.sh          # optional, self-host if you prefer
#
#   # Pushbullet
#   BACKEND=pushbullet
#   PUSHBULLET_TOKEN=o.xxxxxxxx
#
#   # Telegram -- the only backend whose buttons can answer back
#   BACKEND=telegram
#   TELEGRAM_TOKEN=123456:ABC...
#   TELEGRAM_CHAT=987654321
#
# Unconfigured is NOT an error: the caller is a background service and a
# missing phone is not a reason to fail a scrape. It logs and returns 0.
#
# TELEGRAM_API (default https://api.telegram.org) and PUSHBULLET_API are
# overridable from the environment, which is what lets every test run against
# tests/fake_telegram.py instead of the real bot.
set -uo pipefail

# mux_json: the real jq when the machine has one, libjq via the `jq` python
# wheel when it does not, and muxjson.py after that. THE TELEGRAM FILTERS ARE
# THE ONES muxjson CANNOT DO -- test(), rindex(), `as $i`, unique_by(), string
# interpolation -- so on a machine with neither jq nor the wheel this backend
# says so (tg_needs_jq) instead of failing silently, which is what it did when
# jq was an unchecked hard dependency.
. "$(dirname "$(readlink -f "$0")")/profile.sh"

CONF="${CLAUDE_NOTIFY_CONF:-$HOME/.config/claude-notify.conf}"
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/claude-watchdog/notify.log"
# ONE PER MACHINE, not per account: getUpdates has a single consumer, and the
# two accounts' daemons share one bot. muxtelegram.py keeps its offset, lock
# and pending actions here; the setup guide takes the same lock while it waits.
NOTIFY_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/muxtopus-notify"
mkdir -p "$(dirname "$LOG")"

TESTING=0
_ENV_TG_API="${TELEGRAM_API:-}"; _ENV_PB_API="${PUSHBULLET_API:-}"
BACKEND=""; NTFY_TOPIC=""; NTFY_SERVER="https://ntfy.sh"
PUSHBULLET_TOKEN=""; TELEGRAM_TOKEN=""; TELEGRAM_CHAT=""; TELEGRAM_API=""
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"
# The environment wins over the file, so a test can never be pointed back at
# the real servers by a conf it did not write.
TELEGRAM_API="${_ENV_TG_API:-${TELEGRAM_API:-https://api.telegram.org}}"; TELEGRAM_API="${TELEGRAM_API%/}"
PUSHBULLET_API="${_ENV_PB_API:-https://api.pushbullet.com}"; PUSHBULLET_API="${PUSHBULLET_API%/}"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# One Bot API call, the reply on stdout. The token is in the URL, so nothing
# here ever echoes the URL -- curl's own errors name the host, not the path.
tg() {
  local tok="$1" method="$2"; shift 2
  curl -sS -m 20 -X POST "$TELEGRAM_API/bot$tok/$method" "$@" 2>&1
}
# CAN THIS MACHINE READ TELEGRAM'S JSON AT ALL? The filters below are the ones
# muxjson.py deliberately does not implement -- test(), rindex(), `as $i`,
# unique_by(), string interpolation -- so this backend needs either the real jq
# or the `jq` python wheel. Said ONCE, plainly, instead of every call quietly
# returning empty: before this, a machine without jq had Telegram fail with no
# message anywhere, which is the failure mode the whole mux_json work exists to
# end. Checked lazily so the answer costs nothing when jq is installed.
tg_needs_jq() {
  mux_have_jq && return 1
  mux_resolve_python
  "$MUX_PYTHON" -c 'import jq' 2>/dev/null && return 1
  log "telegram: needs jq (or: $MUX_PYTHON -m pip install jq) -- its API replies"
  log "  use filters muxtopus's own JSON reader does not implement"
  echo "claude-notify: telegram needs jq, or the jq python wheel" >&2
  echo "  install one:  sudo <pkg manager> install jq" >&2
  echo "            or: $MUX_PYTHON -m pip install jq" >&2
  return 0
}

tg_ok() { [ "$(mux_json -r '.ok // false' <<<"$1" 2>/dev/null)" = true ]; }
tg_why() {
  local w; w="$(mux_json -r '.description // empty' <<<"$1" 2>/dev/null)"
  printf '%s' "${w:-$1}"
}

# 'Label=data|Label=data||Next row=data' -> an inline_keyboard. The data is
# everything after the LAST '=', so a label may carry one; Telegram caps it at
# 64 bytes, which is why callers pass an opaque id rather than meaning.
buttons_json() {
  mux_json -cn --arg b "$1" '{inline_keyboard: ($b | split("||") | map(
      split("|") | map(select(test("=")) | rindex("=") as $i
        | {text: .[:$i], callback_data: .[$i+1:]}))
      | map(select(length > 0)))}'
}

# ------------------------------------------------------------------ --setup
# The guide parses every API reply, so it is the first thing that would fail.
# THE GUIDE. Plain `read`, curl and jq, so it runs in a bare tmux window with
# nothing installed. Every wait has an end, and giving up writes nothing.
SETUP_WAIT="${NOTIFY_SETUP_WAIT:-180}"
SETUP_POLL="${NOTIFY_SETUP_POLL:-2}"
setup_wait_txt() { if [ "$SETUP_WAIT" -ge 60 ]; then printf '%dm' $(( SETUP_WAIT / 60 )); else printf '%ds' "$SETUP_WAIT"; fi; }

ask() {
  # ask "prompt" -> $REPLY. A closed stdin is a person who left: say so, write nothing.
  printf '%s ' "$1"
  if ! IFS= read -r REPLY; then
    echo; echo "input closed -- nothing written."; exit 1
  fi
  REPLY="${REPLY#"${REPLY%%[![:space:]]*}"}"; REPLY="${REPLY%"${REPLY##*[![:space:]]}"}"
}

# Hold the one-poller lock while the guide reads updates, so a running daemon
# does not eat the /start or the button press it is waiting for.
setup_lock() {
  mkdir -p "$NOTIFY_DIR"
  exec 9>"$NOTIFY_DIR/lock"
  flock -w 40 9 || echo "(the watchdog is holding the notify lock; carrying on anyway)"
}
setup_unlock() { exec 9>&-; }

# Confirm every update up to $1 (Telegram forgets them) and remember the offset.
setup_confirm() {
  local tok="$1" last="$2"
  [ -n "$last" ] && [ "$last" != null ] || return 0
  tg "$tok" getUpdates --data-urlencode "offset=$(( last + 1 ))" \
     --data-urlencode "timeout=0" >/dev/null
  printf '%s\n' "$(( last + 1 ))" > "$NOTIFY_DIR/offset"
}

setup_write_conf() {
  # umask 077 for the file AND its backup: both hold a token.
  local stamp; stamp="$(date '+%Y%m%d-%H%M%S')"
  ( umask 077
    mkdir -p "$(dirname "$CONF")"
    if [ -f "$CONF" ]; then cp -p "$CONF" "$CONF.bak-$stamp"; chmod 600 "$CONF.bak-$stamp"
                            echo "kept the old file as $CONF.bak-$stamp"; fi
    cat > "$CONF.tmp"
    chmod 600 "$CONF.tmp"
    mv "$CONF.tmp" "$CONF" )
}

setup_inbound_key() {
  # The switches live in the settings store, not in this file: the conf holds
  # secrets per machine, a switch is a preference per account.
  local k="$1" v="$2" why
  why="$(cd "$(dirname "$(readlink -f "$0")")" && "${MUX_PYTHON:-python3}" -c '
import sys, muxsettings
k = sys.argv[1]
if k not in muxsettings.DASHBOARD_KEYS:
    print("no-key"); sys.exit(0)
print(muxsettings.put(k, sys.argv[2]) or "ok")' "$k" "$v" 2>&1)"
  case "$why" in
    ok) echo "saved: $k=$v (Settings ▸ Notifications shows it)" ;;
    *)  [ "$v" = on ] && return 0     # on is the default: nothing to write
        echo "could not save it for you${why:+ ($why)}; add this line to"
        echo "  ${MUXTOPUS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/muxtopus/config}:"
        echo "  $k=off" ;;
  esac
}

setup_telegram() {
  local tok r me name user i n chats pick chat last
  cat <<'EOF'

Telegram needs a bot of your own. In the Telegram app:
  1. Open a chat with @BotFather.
  2. Send /newbot.
  3. Give it a display name -- anything, e.g. "Deck muxtopus".
  4. Give it a username ending in "bot", e.g. deck_mux_bot.
  5. BotFather answers with a token like 123456789:AAH4...
  6. Copy that token and paste it here.
EOF
  for i in 1 2 3; do
    ask "token (empty to give up):"
    tok="$REPLY"
    [ -n "$tok" ] || { echo "nothing written."; exit 1; }
    case "$tok" in
      *[!0-9A-Za-z:_-]*|:*|*:) echo "that does not look like a bot token (digits:letters)."; continue ;;
    esac
    r="$(tg "$tok" getMe)"
    if tg_ok "$r"; then
      name="$(mux_json -r '.result.first_name // ""' <<<"$r")"
      user="$(mux_json -r '.result.username // ""' <<<"$r")"
      echo "token accepted: \"$name\" (@$user)"
      break
    fi
    echo "Telegram refused that token: $(tg_why "$r")"
    tok=""
  done
  [ -n "$tok" ] || { echo "three refusals -- nothing written."; exit 1; }

  echo
  echo "Now open https://t.me/$user in Telegram and press START (or send it anything)."
  echo "A bot cannot write to you until you have written to it. Waiting up to $(setup_wait_txt)..."
  setup_lock
  chats=""; last=""
  local until=$(( SECONDS + SETUP_WAIT ))
  while [ "$SECONDS" -lt "$until" ]; do
    r="$(tg "$tok" getUpdates --data-urlencode "timeout=0")"
    if tg_ok "$r"; then
      last="$(mux_json -r '[.result[].update_id] | max // empty' <<<"$r")"
      chats="$(mux_json -r '[.result[] | (.message // .edited_message // .my_chat_member // empty) | .chat
                  | {id, label: (.first_name // .title // .username // "")}] | unique_by(.id)[]
                  | "\(.id)\t\(.label)"' <<<"$r")"
      [ -n "$chats" ] && break
    fi
    printf '.'
    sleep "$SETUP_POLL"
  done
  echo
  if [ -z "$chats" ]; then
    setup_unlock
    echo "no message reached the bot in $(setup_wait_txt) -- nothing written. Run the guide again when ready."
    exit 1
  fi
  setup_confirm "$tok" "$last"
  setup_unlock
  n="$(grep -c '' <<<"$chats")"
  if [ "$n" = 1 ]; then
    chat="${chats%%	*}"
    echo "found you: ${chats#*	} (chat $chat)"
  else
    echo "several chats have written to this bot:"
    i=0
    while IFS=$'\t' read -r cid label; do i=$(( i + 1 )); printf '  %d) %s  (%s)\n' "$i" "$label" "$cid"; done <<<"$chats"
    while :; do
      ask "which one? [1-$n]:"
      case "$REPLY" in ''|*[!0-9]*) continue ;; esac
      [ "$REPLY" -ge 1 ] && [ "$REPLY" -le "$n" ] && break
    done
    pick="$(sed -n "${REPLY}p" <<<"$chats")"; chat="${pick%%	*}"
  fi

  cat <<'EOF'

Privacy: a "needs you" message quotes the prompt box on the screen, so that
text passes through Telegram's servers (Settings ▸ Notifications turns it off).
EOF
  ask "Let the buttons answer prompts and questions from the phone? [Y/n]"
  local inbound=on pull=""
  case "$REPLY" in n|N|no|No|NO) inbound=off ;; esac
  if [ "$inbound" = on ]; then
    cat <<'EOF'

What should reach the phone?
  1) tell me     -- prompts, questions, trouble and finished lanes, as they happen
  2) only when I ask -- no pushes at all; the bot answers /status, /pending and the rest
EOF
    ask "[1]:"
    case "$REPLY" in 2|o*|O*) pull=1 ;; esac
  fi

  printf '# Written by claude-notify.sh --setup, %s. Holds a SECRET: keep it 0600.\nBACKEND=telegram\nTELEGRAM_TOKEN=%s\nTELEGRAM_CHAT=%s\n' \
    "$(date '+%Y-%m-%d %H:%M')" "$tok" "$chat" | setup_write_conf
  echo "wrote $CONF (mode 600)"
  setup_inbound_key MUXTOPUS_NOTIFY_INBOUND "$inbound"
  if [ -n "$pull" ]; then
    for k in MUXTOPUS_NOTIFY_WAITING MUXTOPUS_NOTIFY_QUESTIONS MUXTOPUS_NOTIFY_TROUBLE MUXTOPUS_NOTIFY_DONE; do
      setup_inbound_key "$k" off
    done
  fi
  TELEGRAM_TOKEN="$tok"; TELEGRAM_CHAT="$chat"
  # The bot's menu button: /status, /pending, ... (muxtelegram re-registers
  # whenever the list changes; this makes it appear before the first poll).
  if [ "$inbound" = on ] && ( cd "$(dirname "$(readlink -f "$0")")" && "${MUX_PYTHON:-python3}" muxtelegram.py commands --force ) >/dev/null 2>&1; then
    echo "the bot's menu now offers /status, /pending, /questions, /blocked, /windows, /mute."
  fi

  local cb mid ok=""
  cb="setup-$(date +%s)-$RANDOM"
  if [ "$inbound" = on ]; then
    r="$(tg "$tok" sendMessage --data-urlencode "chat_id=$chat" \
          --data-urlencode "text=Muxtopus: notifications are set up on ${HOSTNAME:-this machine}. Press the button to prove the phone can answer." \
          --data-urlencode "reply_markup=$(buttons_json "It works=$cb")")"
  else
    r="$(tg "$tok" sendMessage --data-urlencode "chat_id=$chat" \
          --data-urlencode "text=Muxtopus: notifications are set up on ${HOSTNAME:-this machine}.")"
  fi
  if ! tg_ok "$r"; then
    echo "the test message FAILED: $(tg_why "$r")"
    log "setup: test FAILED via telegram: $(tg_why "$r")"
    exit 1
  fi
  log "setup: telegram configured, test sent"
  echo "test message sent."
  if [ "$inbound" = on ]; then
    mid="$(mux_json -r '.result.message_id' <<<"$r")"
    echo "Press \"It works\" under it in Telegram. Waiting up to $(setup_wait_txt)..."
    setup_lock
    until=$(( SECONDS + SETUP_WAIT ))
    while [ "$SECONDS" -lt "$until" ]; do
      r="$(tg "$tok" getUpdates --data-urlencode "timeout=0")"
      if tg_ok "$r"; then
        last="$(mux_json -r '[.result[].update_id] | max // empty' <<<"$r")"
        local qid
        qid="$(mux_json -r --arg cb "$cb" --arg c "$chat" '.result[] | .callback_query // empty
                | select(.data == $cb and ((.message.chat.id|tostring) == $c)) | .id' <<<"$r" | head -1)"
        setup_confirm "$tok" "$last"
        if [ -n "$qid" ]; then
          tg "$tok" answerCallbackQuery --data-urlencode "callback_query_id=$qid" \
             --data-urlencode "text=inbound works" >/dev/null
          tg "$tok" editMessageText --data-urlencode "chat_id=$chat" --data-urlencode "message_id=$mid" \
             --data-urlencode "text=Muxtopus: notifications are set up on ${HOSTNAME:-this machine}. ✓ the phone answered at $(date '+%H:%M')." >/dev/null
          ok=1; break
        fi
      fi
      printf '.'
      sleep "$SETUP_POLL"
    done
    setup_unlock
    echo
    if [ -n "$ok" ]; then
      echo "the press arrived: buttons work end to end."
      log "setup: inbound proven"
    else
      echo "no press arrived. Sending works; answering does not yet -- is another copy of this guide open?"
    fi
  fi
}

setup_ntfy() {
  local topic server
  echo
  echo "ntfy needs no account: the topic name IS the address, so it must be unguessable."
  echo "Install the ntfy app and subscribe to the topic you choose here."
  local sugg; sugg="muxtopus-$(tr -dc 'a-z0-9' </dev/urandom 2>/dev/null | head -c 10)"
  ask "topic [$sugg]:"; topic="${REPLY:-$sugg}"
  ask "server [https://ntfy.sh]:"; server="${REPLY:-https://ntfy.sh}"
  printf '# Written by claude-notify.sh --setup, %s.\nBACKEND=ntfy\nNTFY_TOPIC=%s\nNTFY_SERVER=%s\n' \
    "$(date '+%Y-%m-%d %H:%M')" "$topic" "$server" | setup_write_conf
  echo "wrote $CONF"
  BACKEND=ntfy; NTFY_TOPIC="$topic"; NTFY_SERVER="$server"
}

setup_pushbullet() {
  local token
  echo
  echo "Pushbullet: pushbullet.com ▸ Settings ▸ Account ▸ Create Access Token."
  ask "access token (empty to give up):"; token="$REPLY"
  [ -n "$token" ] || { echo "nothing written."; exit 1; }
  ask "send a test push once saved? [Y/n]"
  printf '# Written by claude-notify.sh --setup, %s. Holds a SECRET: keep it 0600.\nBACKEND=pushbullet\nPUSHBULLET_TOKEN=%s\n' \
    "$(date '+%Y-%m-%d %H:%M')" "$token" | setup_write_conf
  echo "wrote $CONF (mode 600)"
  BACKEND=pushbullet; PUSHBULLET_TOKEN="$token"
  case "$REPLY" in n|N|no) SKIP_TEST=1 ;; esac
}

setup() {
  local SKIP_TEST=""
  echo "muxtopus -- phone notifications"
  # Checked FIRST: the guide reads every API reply, so a machine that cannot
  # parse them would walk the whole flow and fail at the end with nothing said.
  tg_needs_jq && return 1
  if [ -n "$BACKEND" ]; then
    echo "configured already: $BACKEND ($CONF)"
    ask "[t]est it, [r]econfigure, or [k]eep as is? [k]"
    case "$REPLY" in
      t|T|test) "$0" --test; exit 0 ;;
      r|R|reconfigure) ;;
      *) echo "kept."; exit 0 ;;
    esac
  fi
  echo
  echo "  1) Telegram     recommended: its buttons can answer a prompt from the phone"
  echo "  2) ntfy         no account; notifications only"
  echo "  3) Pushbullet   notifications only"
  ask "backend [1]:"
  case "${REPLY:-1}" in
    1|t*|T*) setup_telegram ;;
    2|n*|N*) setup_ntfy; "$0" --test ;;
    3|p*|P*) setup_pushbullet; [ -n "$SKIP_TEST" ] || "$0" --test ;;
    *) echo "no such backend -- nothing written."; exit 1 ;;
  esac
  echo
  echo "done -- this window closes in ${NOTIFY_SETUP_CLOSE:-5} s"
  sleep "${NOTIFY_SETUP_CLOSE:-5}"
  exit 0
}

# ------------------------------------------------------------------ options
BUTTONS=""; EDIT=""; REPLY_TO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --buttons)  BUTTONS="${2-}"; shift 2 ;;
    --edit)     EDIT="${2-}"; shift 2 ;;
    --reply-to) REPLY_TO="${2-}"; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
case "$EDIT$REPLY_TO" in *[!0-9]*) echo "--edit/--reply-to take a message id" >&2; exit 2 ;; esac

case "${1:-}" in
  --status)
    if [ -z "$BACKEND" ]; then
      echo "no backend configured — run $0 --setup (or see the header of $0)"
      exit 1
    fi
    echo "backend: $BACKEND"
    # The last good send and the last failure, from the log -- what "is it
    # working" actually asks.
    if [ -f "$LOG" ]; then
      l="$(grep -E '  (sent via|FAILED via)' "$LOG" | tail -1)"
      s="$(grep '  sent via' "$LOG" | tail -1)"
      [ -n "$s" ] && echo "last sent: ${s:0:19}"
      case "$l" in *"FAILED via"*) echo "last FAILED: ${l:0:19} ${l#*FAILED via }" ;; esac
    fi
    exit 0 ;;
  --setup) setup ;;
  --test) TESTING=1; set -- "Deck" "Notifications are working." ;;
  --telegram-chat)
    # The fiddly half of Telegram setup. A bot CANNOT open a conversation with
    # you, so it has no idea who you are until you message it first -- which is
    # also why the usual first failure is a 403 rather than a bad token.
    [ -n "${2:-}" ] || { echo "usage: $0 --telegram-chat <BOT_TOKEN>" >&2; exit 2; }
    r="$(tg "$2" getUpdates)"
    if ! tg_ok "$r"; then
      echo "Telegram refused that token: $(tg_why "$r")" >&2
      exit 1
    fi
    if [ "$(mux_json -r '.result | length' <<<"$r")" = 0 ]; then
      echo "Token is valid, but the bot has never heard from you." >&2
      echo "Open Telegram, find your bot, send it any message (/start will do)," >&2
      echo "then run this again." >&2
      exit 1
    fi
    echo "Chat id(s) that have messaged this bot:"
    mux_json -r '.result[] | (.message // .edited_message // empty) | .chat
           | "  TELEGRAM_CHAT=\(.id)    \(.type)  \(.first_name // .title // "")"' <<<"$r" | sort -u
    exit 0 ;;
  -h|--help) sed -n '2,39p' "$0"; exit 0 ;;
esac

TITLE="${1:-Deck}"
BODY="${2:-}"

if [ -z "$BACKEND" ]; then
  log "SKIPPED (no backend): $TITLE — $BODY"
  echo "no notification backend configured; see $CONF" >&2
  exit 0
fi

# A backend without buttons still has to say that the question has an answer
# somewhere -- otherwise a "needs you" reads as information, not as a request.
if [ -n "$BUTTONS" ] && [ "$BACKEND" != telegram ]; then
  BODY="$BODY

(answer at the machine)"
fi

# /mute from the phone (muxtelegram.py): PUSHES wait, asking does not. An edit
# or a reply is part of a conversation already under way, so it goes through.
if [ "$TESTING" = 0 ] && [ -z "$EDIT$REPLY_TO" ] && [ -f "$NOTIFY_DIR/mute" ]; then
  read -r _until < "$NOTIFY_DIR/mute" 2>/dev/null
  case "${_until:-}" in
    ''|*[!0-9]*) ;;
    *) if [ "$_until" -gt "$(date +%s)" ]; then log "MUTED: $TITLE"; exit 0; fi ;;
  esac
fi

rc=1; why=""
case "$BACKEND" in
  ntfy)
    [ -n "$NTFY_TOPIC" ] || { log "ntfy: NTFY_TOPIC unset"; exit 0; }
    curl -fsS -m 15 -H "Title: $TITLE" -d "$BODY" \
      "${NTFY_SERVER%/}/$NTFY_TOPIC" >/dev/null 2>&1 && rc=0 ;;
  pushbullet)
    [ -n "$PUSHBULLET_TOKEN" ] || { log "pushbullet: token unset"; exit 0; }
    curl -fsS -m 15 -H "Access-Token: $PUSHBULLET_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$(mux_json -n --arg t "$TITLE" --arg b "$BODY" \
            '{type:"note",title:$t,body:$b}')" \
      "$PUSHBULLET_API/v2/pushes" >/dev/null 2>&1 && rc=0 ;;
  telegram)
    [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT" ] || {
      log "telegram: token or chat unset"; exit 0; }
    tg_needs_jq && exit 0
    text="$TITLE
$BODY"
    # 4096 is Telegram's cap; cut by CHARACTERS (jq), never by bytes, or a
    # quoted prompt box ending in a multibyte glyph is refused as bad UTF-8.
    [ "${#text}" -gt 4000 ] && text="$(mux_json -Rrs '.[0:3990] + " …"' <<<"$text")"
    args=(--data-urlencode "chat_id=$TELEGRAM_CHAT" --data-urlencode "text=$text")
    [ -n "$BUTTONS" ] && args+=(--data-urlencode "reply_markup=$(buttons_json "$BUTTONS")")
    method=sendMessage
    if [ -n "$EDIT" ]; then
      method=editMessageText; args+=(--data-urlencode "message_id=$EDIT")
    elif [ -n "$REPLY_TO" ]; then
      args+=(--data-urlencode "reply_to_message_id=$REPLY_TO")
    fi
    # Read the reply rather than discarding it. Telegram answers a refusal with
    # HTTP 200 and ok:false, and the description is the only thing that tells
    # you WHICH mistake you made -- most often "bot can't initiate conversation
    # with a user", meaning nobody has messaged the bot yet.
    resp="$(tg "$TELEGRAM_TOKEN" "$method" "${args[@]}")"
    if tg_ok "$resp"; then
      rc=0
      [ "$TESTING" = 1 ] || mux_json -r '.result.message_id // empty' <<<"$resp"
    else
      why="$(tg_why "$resp")"
    fi ;;
  *)
    log "unknown BACKEND=$BACKEND"; echo "unknown BACKEND: $BACKEND" >&2; exit 0 ;;
esac

if [ "$rc" = 0 ]; then
  log "sent via $BACKEND${EDIT:+ (edit $EDIT)}: $TITLE — ${BODY%%$'\n'*}"
  [ "$TESTING" = 1 ] && echo "sent via $BACKEND — check your phone"
else
  log "FAILED via $BACKEND: ${why:-no detail} — $TITLE"
  # A background caller gets silence and a log line; a person running --test
  # gets the reason, because that is the only moment it can be acted on.
  [ "$TESTING" = 1 ] && echo "FAILED via $BACKEND: ${why:-no detail}" >&2
fi
exit 0
