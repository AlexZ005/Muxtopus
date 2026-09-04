#!/usr/bin/env bash
# claude-watchdog.sh -- notice a Claude window that stopped at a usage limit,
# and prompt it to carry on once the limit has reset.
#
#   claude-watchdog.sh --once        one pass, act if due
#   claude-watchdog.sh --dry-run     one pass, print what it WOULD do
#   claude-watchdog.sh --daemon      poll forever (the systemd unit uses this)
#   claude-watchdog.sh --status      print the state table it publishes
#   claude-watchdog.sh --on|--off    enable/disable acting (the dashboard's 'w')
#   claude-watchdog.sh --install     install + start the systemd user service
#   claude-watchdog.sh --uninstall   stop and remove it
#
# WHY THIS EXISTS. `autoContinueAtUsageLimit` is set in ~/.claude/settings.json
# and does NOT resume after the 5-hour session limit -- measured twice on this
# machine, the second time under clean conditions: a session started fresh on
# 2.1.260 with the setting armed at launch hit the limit at 09:42, the limit
# reset at 12:40, and it was still idle at 13:39. In both cases the transcript
# records the limit as a `<synthetic>` assistant message with `read=0` and the
# turn marked done -- the CLI ENDS the turn rather than parking it, so there is
# nothing left for auto-continue to resume. `/loop` has the same hole from the
# other side: a refused turn never reaches the call that schedules the next
# wakeup, so one refusal kills the loop permanently.
#
# So the only thing that reliably restarts the work is something OUTSIDE Claude
# Code. That is this.
#
# IT COSTS NO TOKENS TO WATCH. Everything here is bash reading local files and
# tmux panes; nothing calls the API. The only tokens spent are the ones your
# session spends when it is prompted to continue -- which is the whole point.
set -uo pipefail

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/claude-watchdog"
ENABLED="$STATE_DIR/enabled"
STATUS="$STATE_DIR/status.tsv"
PROMPTED="$STATE_DIR/prompted"
LOG="$STATE_DIR/log"
MSGFILE="$STATE_DIR/message"

DEFAULT_MSG="The usage limit has reset. Continue from where you left off."
INTERVAL="${WATCHDOG_INTERVAL:-30}"
# A window is only prompted once per (session, reset) pair, so the grace is
# just insurance against a clock edge, not a retry cadence.
GRACE=20

mkdir -p "$STATE_DIR"
[ -f "$MSGFILE" ] || printf '%s\n' "$DEFAULT_MSG" > "$MSGFILE"

MODE="--once"; DRY=0
case "${1:---once}" in
  --once)    MODE=once ;;
  --dry-run) MODE=once; DRY=1 ;;
  --daemon)  MODE=daemon ;;
  --status)  [ -f "$STATUS" ] && cat "$STATUS"; exit 0 ;;
  --on)      : > "$ENABLED"; echo "watchdog enabled"; exit 0 ;;
  --off)     rm -f "$ENABLED"; echo "watchdog disabled"; exit 0 ;;
  --install|--uninstall) MODE="${1#--}" ;;
  -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/claude-watchdog.service"
SELF="$(readlink -f "$0")"

if [ "$MODE" = uninstall ]; then
  systemctl --user disable --now claude-watchdog.service 2>/dev/null
  rm -f "$UNIT"; systemctl --user daemon-reload 2>/dev/null
  echo "removed $UNIT"; exit 0
fi

if [ "$MODE" = install ]; then
  # A USER service, and it only survives logout because apply-logind.sh turned
  # lingering on -- without that the manager stops with your last session and
  # takes this with it, which is the same failure it exists to work around.
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT" <<UNITEOF
[Unit]
Description=Prompt Claude Code windows to continue after a usage limit resets
After=default.target

[Service]
Type=simple
ExecStart=$SELF --daemon
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNITEOF
  systemctl --user daemon-reload
  systemctl --user enable --now claude-watchdog.service >/dev/null 2>&1
  # Armed on install: watching without acting is not what anyone wants from
  # it. Turn it off any time with 'w' on the dashboard, or --off here.
  : > "$ENABLED"
  if systemctl --user is-active --quiet claude-watchdog.service; then
    echo "installed and running: $UNIT"
    echo "armed -- press w on the dashboard to disarm"
  else
    echo "installed but NOT running; check: systemctl --user status claude-watchdog" >&2
    exit 1
  fi
  if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
    echo "WARNING: lingering is off, so this dies at logout -- run apply-logind.sh" >&2
  fi
  exit 0
fi

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# Reset times are printed as a wall clock with no date ("resets 12:40pm"), so
# the day has to be inferred. Today's occurrence is right in the ordinary case
# (limit at 09:42, resets 12:40). A limit hit late at night names a time that
# already passed today, and there the answer is tomorrow -- 6h is comfortably
# past any real gap between hitting a limit and its reset, and comfortably
# short of the ~12h a late-night wrap would show.
reset_epoch() {
  local hhmm="$1" e now
  hhmm="$(sed -E 's/([ap]m)$/ \1/I' <<<"$hhmm")"     # 12:40pm -> 12:40 pm
  e="$(date -d "today $hhmm" +%s 2>/dev/null)" || return 1
  now="$(date +%s)"
  if [ -n "$e" ] && [ "$e" -lt $(( now - 21600 )) ]; then
    e="$(date -d "tomorrow $hhmm" +%s 2>/dev/null)"
  fi
  printf '%s' "$e"
}

transcript_of() {
  local sid="$1" f
  for f in "$HOME"/.claude/projects/*/"$sid".jsonl; do
    [ -f "$f" ] && { printf '%s' "$f"; return 0; }
  done
  return 1
}

# The tail is bounded because these files reach tens of MB; the last usage
# record is all we need and it is always near the end. A partial first line
# from the -c cut simply fails to match.
#
# The LAST record is not always the useful one: a usage-limit refusal is
# written as a synthetic message with every counter at zero, so a limited
# window would report a context of 0 -- exactly the window you most want to
# see the size of. Take the last NON-ZERO reading instead.
context_tokens() {
  local f="$1" v
  v="$(tail -c 400000 "$f" 2>/dev/null | grep '"usage"' | tail -20 \
       | jq -r '(.message.usage.cache_read_input_tokens // 0)
                + (.message.usage.cache_creation_input_tokens // 0)' 2>/dev/null \
       | grep -v '^0$' | tail -1)"
  printf '%s' "${v:-0}"
}

pass() {
  local enabled=0; [ -f "$ENABLED" ] && enabled=1
  local msg; msg="$(head -1 "$MSGFILE" 2>/dev/null)"; msg="${msg:-$DEFAULT_MSG}"
  local now; now="$(date +%s)"
  local tmp="$STATUS.tmp"; : > "$tmp"

  local f pid sid pane paneid ver st cwd tr ctx name text reset epoch state acted
  for f in "$HOME"/.claude/sessions/*.json; do
    [ -f "$f" ] || continue
    pid="$(jq -r '.pid // empty' "$f" 2>/dev/null)"; [ -n "$pid" ] || continue
    kill -0 "$pid" 2>/dev/null || continue          # stale record, process gone
    sid="$(jq -r '.sessionId // empty' "$f")"
    pane="$(jq -r '.tmux // empty' "$f")"
    ver="$(jq -r '.version // "?"' "$f")"
    st="$(jq -r '.status // "?"' "$f")"
    [ -n "$sid" ] || continue

    paneid="${pane##*.}"                            # claude:@1.%1 -> %1
    ctx=0; tr="$(transcript_of "$sid")" && ctx="$(context_tokens "$tr")"
    ctx="${ctx:-0}"

    name="-"; text=""
    if [ -n "$paneid" ]; then
      name="$(tmux display-message -p -t "$paneid" '#{window_name}' 2>/dev/null || echo -)"
      text="$(tmux capture-pane -p -t "$paneid" 2>/dev/null || true)"
    fi

    state="idle"; reset="-"; epoch=""
    # "esc to interrupt" is the TUI's own marker for a turn in flight. Never
    # type into a window that is working -- the keystrokes would land in
    # whatever prompt it is composing.
    if grep -q "esc to interrupt" <<<"$text"; then
      state="working"
    elif grep -q "hit your session limit" <<<"$text"; then
      reset="$(grep -oE 'resets [0-9]{1,2}:[0-9]{2} ?[ap]m' <<<"$text" | tail -1 | awk '{print $2 $3}')"
      if [ -n "$reset" ]; then
        epoch="$(reset_epoch "$reset")"
        if [ -n "$epoch" ] && [ "$now" -ge $(( epoch + GRACE )) ]; then
          state="due"
        else
          state="limited"
        fi
      else
        state="limited"
      fi
    fi

    acted=""
    if [ "$state" = "due" ]; then
      if grep -qx "$sid	$epoch" "$PROMPTED" 2>/dev/null; then
        acted="already-prompted"; state="limited"
      elif [ "$enabled" != 1 ]; then
        acted="watchdog-off"
      elif [ "$DRY" = 1 ]; then
        acted="WOULD-PROMPT"
      else
        tmux send-keys -t "$paneid" "$msg" 2>/dev/null
        sleep 1
        tmux send-keys -t "$paneid" Enter 2>/dev/null
        printf '%s\t%s\n' "$sid" "$epoch" >> "$PROMPTED"
        acted="prompted"
        log "prompted ${sid:0:8} in $name (pane $paneid) after reset $reset"
        state="working"
      fi
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "${sid:0:8}" "$name" "$paneid" "$ver" "$ctx" "$state" "$reset" "$acted" >> "$tmp"
  done

  mv "$tmp" "$STATUS"
  if [ "$DRY" = 1 ]; then
    { printf 'SESSION\tWINDOW\tPANE\tVER\tCONTEXT\tSTATE\tRESET\tACTION\n'; cat "$STATUS"; } \
      | column -t -s $'\t'
  fi
  return 0
}

if [ "$MODE" = daemon ]; then
  log "watchdog started (interval ${INTERVAL}s)"
  while :; do pass; sleep "$INTERVAL"; done
else
  pass
fi
