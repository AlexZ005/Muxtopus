#!/usr/bin/env bash
# claude-notify.sh -- send a short message to the phone.
#
#   claude-notify.sh "Title" "body text"
#   claude-notify.sh --test
#   claude-notify.sh --status        which backend is configured
#
# CONFIG lives OUTSIDE this repo, at ~/.config/claude-notify.conf, because it
# holds tokens. Create it with one backend:
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
#   # Telegram
#   BACKEND=telegram
#   TELEGRAM_TOKEN=123456:ABC...
#   TELEGRAM_CHAT=987654321
#
# Unconfigured is NOT an error: the caller is a background service and a
# missing phone is not a reason to fail a scrape. It logs and returns 0.
set -uo pipefail

CONF="${CLAUDE_NOTIFY_CONF:-$HOME/.config/claude-notify.conf}"
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/claude-watchdog/notify.log"
mkdir -p "$(dirname "$LOG")"

BACKEND=""; NTFY_TOPIC=""; NTFY_SERVER="https://ntfy.sh"
PUSHBULLET_TOKEN=""; TELEGRAM_TOKEN=""; TELEGRAM_CHAT=""
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

case "${1:-}" in
  --status)
    if [ -z "$BACKEND" ]; then
      echo "no backend configured — create $CONF (see the header of $0)"
      exit 1
    fi
    echo "backend: $BACKEND"
    exit 0 ;;
  --test) set -- "Deck" "Notifications are working." ;;
  -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
esac

TITLE="${1:-Deck}"
BODY="${2:-}"

if [ -z "$BACKEND" ]; then
  log "SKIPPED (no backend): $TITLE — $BODY"
  echo "no notification backend configured; see $CONF" >&2
  exit 0
fi

rc=1
case "$BACKEND" in
  ntfy)
    [ -n "$NTFY_TOPIC" ] || { log "ntfy: NTFY_TOPIC unset"; exit 0; }
    curl -fsS -m 15 -H "Title: $TITLE" -d "$BODY" \
      "${NTFY_SERVER%/}/$NTFY_TOPIC" >/dev/null 2>&1 && rc=0 ;;
  pushbullet)
    [ -n "$PUSHBULLET_TOKEN" ] || { log "pushbullet: token unset"; exit 0; }
    curl -fsS -m 15 -H "Access-Token: $PUSHBULLET_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$(jq -n --arg t "$TITLE" --arg b "$BODY" \
            '{type:"note",title:$t,body:$b}')" \
      https://api.pushbullet.com/v2/pushes >/dev/null 2>&1 && rc=0 ;;
  telegram)
    [ -n "$TELEGRAM_TOKEN" ] && [ -n "$TELEGRAM_CHAT" ] || {
      log "telegram: token or chat unset"; exit 0; }
    curl -fsS -m 15 -X POST \
      "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" \
      --data-urlencode "chat_id=$TELEGRAM_CHAT" \
      --data-urlencode "text=$TITLE
$BODY" >/dev/null 2>&1 && rc=0 ;;
  *)
    log "unknown BACKEND=$BACKEND"; echo "unknown BACKEND: $BACKEND" >&2; exit 0 ;;
esac

if [ "$rc" = 0 ]; then log "sent via $BACKEND: $TITLE — $BODY"
else                   log "FAILED via $BACKEND: $TITLE — $BODY"; fi
exit 0
