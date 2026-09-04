#!/usr/bin/env bash
# claude-watchdog.sh -- notice a Claude window that stopped at a usage limit,
# and prompt it to carry on once the limit has reset.
#
#   claude-watchdog.sh --once        one pass, act if due
#   claude-watchdog.sh --dry-run     one pass, print what it WOULD do
#   claude-watchdog.sh --daemon      poll forever (the systemd unit uses this)
#   claude-watchdog.sh --status      print the state table it publishes
#   claude-watchdog.sh --on|--off    enable/disable acting (the dashboard's 'w')
#   claude-watchdog.sh --optout ID   never prompt that session (dashboard: space)
#   claude-watchdog.sh --optin ID    undo it
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
# Per-session opt-out, one session id per line. ABSENT MEANS ENABLED, so a
# session that has never been touched is covered without anyone opting in.
OPTOUT="$STATE_DIR/optout"
TOKDIR="$STATE_DIR/tokens"
REPOS="$STATE_DIR/repos.tsv"
REPOS_AT="$STATE_DIR/repos.at"
# Working trees change far more slowly than sessions do, and each one costs a
# git fork, so the repo sweep runs on its own slower clock.
REPO_EVERY=120

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
  --optout)  [ -n "${2:-}" ] || { echo "need a session id" >&2; exit 2; }
             grep -qxF "$2" "$OPTOUT" 2>/dev/null || printf '%s\n' "$2" >> "$OPTOUT"
             echo "watchdog will leave $2 alone"; exit 0 ;;
  --optin)   [ -n "${2:-}" ] || { echo "need a session id" >&2; exit 2; }
             if [ -f "$OPTOUT" ]; then grep -vxF "$2" "$OPTOUT" > "$OPTOUT.tmp" || true
                                       mv "$OPTOUT.tmp" "$OPTOUT"; fi
             echo "watchdog will resume $2"; exit 0 ;;
  --install|--uninstall) MODE="${1#--}" ;;
  -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
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
  # RESTART, not just enable: a running daemon is a bash loop holding the copy
  # of this script it parsed at start, so `enable --now` on an already-active
  # unit would leave an edited watchdog unused. Same reason deck-status has R.
  systemctl --user restart claude-watchdog.service >/dev/null 2>&1
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

# Lifetime tokens for a session, scanned INCREMENTALLY: the byte offset and the
# running totals are cached, so only bytes appended since the last poll are
# read. The first sight of a session costs one full scan (~1-2s on a 15 MB
# transcript); every poll after it reads a few KB.
#
# Transcripts are append-only whole lines, so the previous size is a line
# boundary. A poll that lands mid-write starts mid-line, and that one record is
# skipped -- worth knowing, not worth a lock.
#
# SPENT is input + cache writes + output: the parts billed at or above full
# rate. Cache READS are counted separately because they are ~10% of the price,
# and lumping them in makes an efficient long session look ruinous.
token_totals() {
  local sid="$1" f="$2" cache="$TOKDIR/$sid"
  local off=0 spent=0 rd=0 size add_s add_r
  mkdir -p "$TOKDIR"
  [ -f "$cache" ] && read -r off spent rd < "$cache" 2>/dev/null
  off="${off:-0}"; spent="${spent:-0}"; rd="${rd:-0}"
  size="$(stat -c %s "$f" 2>/dev/null || echo 0)"
  if [ "$size" -lt "$off" ]; then off=0; spent=0; rd=0; fi   # replaced/truncated
  if [ "$size" -gt "$off" ]; then
    read -r add_s add_r < <(
      tail -c +$(( off + 1 )) "$f" 2>/dev/null | grep '"usage"' \
        | jq -r '[ (.message.usage.input_tokens // 0)
                  + (.message.usage.cache_creation_input_tokens // 0)
                  + (.message.usage.output_tokens // 0),
                  (.message.usage.cache_read_input_tokens // 0) ] | @tsv' 2>/dev/null \
        | awk -F'\t' '{a+=$1; b+=$2} END{printf "%d %d", a+0, b+0}')
    spent=$(( spent + ${add_s:-0} )); rd=$(( rd + ${add_r:-0} ))
    printf '%s %s %s\n' "$size" "$spent" "$rd" > "$cache"
  fi
  printf '%s %s' "$spent" "$rd"
}

# Last time we prompted this session, as an epoch. The prompted file is the
# dedupe ledger and now carries the moment too, so one file answers both
# "have we already handled this limit" and "when did it last get restarted".
last_resumed() {
  awk -F'\t' -v s="$1" '$1==s && $3!="" {v=$3} END{print (v?v:"-")}' "$PROMPTED" 2>/dev/null || echo -
}

model_of() {
  local f="$1" m
  m="$(tail -c 400000 "$f" 2>/dev/null | grep '"usage"' | tail -5 \
       | jq -r '.message.model // empty' 2>/dev/null \
       | grep -v '^<' | tail -1)"
  # claude-opus-4-8 -> opus-4-8; the vendor prefix is the same on every row.
  printf '%s' "${m#claude-}"
}

# Uncommitted work, published for the dashboard because that process must not
# fork per frame. Only DIRTY repos are listed, so the common answer is an empty
# file. -uno skips untracked scanning, which is the slow half of git status and
# not what "work I could lose" means here -- an untracked scratch file is noise,
# a modified tracked file is not.
sweep_repos() {
  local last=0 now d n name
  [ -f "$REPOS_AT" ] && read -r last < "$REPOS_AT" 2>/dev/null
  now="$(date +%s)"
  [ $(( now - ${last:-0} )) -lt "$REPO_EVERY" ] && return 0
  : > "$REPOS.tmp"
  for d in "$HOME"/.code/*/ "$HOME"/.code/*/*/; do
    [ -e "$d/.git" ] || continue
    n="$(git -C "$d" status --porcelain -uno 2>/dev/null | wc -l)"
    [ "${n:-0}" -gt 0 ] || continue
    name="${d%/}"; name="${name##*/}"
    printf '%s\t%s\t%s\n' "${d%/}" "$name" "$n" >> "$REPOS.tmp"
  done
  mv "$REPOS.tmp" "$REPOS"
  printf '%s\n' "$now" > "$REPOS_AT"
}

pass() {
  local enabled=0; [ -f "$ENABLED" ] && enabled=1
  local msg; msg="$(head -1 "$MSGFILE" 2>/dev/null)"; msg="${msg:-$DEFAULT_MSG}"
  local now; now="$(date +%s)"
  local tmp="$STATUS.tmp"; : > "$tmp"

  local f pid sid pane paneid ver st cwd tr ctx name text reset epoch state acted
  local spent rd resumed model optout idle
  for f in "$HOME"/.claude/sessions/*.json; do
    [ -f "$f" ] || continue
    pid="$(jq -r '.pid // empty' "$f" 2>/dev/null)"; [ -n "$pid" ] || continue
    kill -0 "$pid" 2>/dev/null || continue          # stale record, process gone
    sid="$(jq -r '.sessionId // empty' "$f")"
    pane="$(jq -r '.tmux // empty' "$f")"
    ver="$(jq -r '.version // "?"' "$f")"
    st="$(jq -r '.status // "?"' "$f")"
    [ -n "$sid" ] || continue
    # claude-usage.sh's throwaway probe lives in its own tmux session. It is a
    # real claude process, so it would otherwise be listed and -- worse -- be
    # eligible for a restart prompt, turning a read-only measurement into a
    # session that spends tokens.
    case "$pane" in cc-usage:*) continue ;; esac

    paneid="${pane##*.}"                            # claude:@1.%1 -> %1
    ctx=0; spent=0; rd=0; model="-"
    if tr="$(transcript_of "$sid")"; then
      ctx="$(context_tokens "$tr")"
      read -r spent rd < <(token_totals "$sid" "$tr")
      model="$(model_of "$tr")"
    fi
    ctx="${ctx:-0}"; spent="${spent:-0}"; rd="${rd:-0}"; model="${model:--}"
    # Seconds since this session last wrote a turn. The transcript's mtime is
    # the cheapest honest answer, and it separates "quiet because it finished"
    # from "quiet because it stalled" at a glance.
    idle=-1
    [ -n "${tr:-}" ] && [ -f "${tr:-}" ] && \
      idle=$(( now - $(stat -c %Y "$tr" 2>/dev/null || echo "$now") ))
    resumed="$(last_resumed "$sid")"
    optout=0; grep -qxF "$sid" "$OPTOUT" 2>/dev/null && optout=1

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
      if awk -F'\t' -v s="$sid" -v e="$epoch" '$1==s && $2==e{f=1} END{exit !f}' \
           "$PROMPTED" 2>/dev/null; then
        acted="already-prompted"; state="limited"
      elif [ "$optout" = 1 ]; then
        acted="opted-out"
      elif [ "$enabled" != 1 ]; then
        acted="watchdog-off"
      elif [ "$DRY" = 1 ]; then
        acted="WOULD-PROMPT"
      else
        tmux send-keys -t "$paneid" "$msg" 2>/dev/null
        sleep 1
        tmux send-keys -t "$paneid" Enter 2>/dev/null
        printf '%s\t%s\t%s\n' "$sid" "$epoch" "$now" >> "$PROMPTED"
        acted="prompted"; resumed="$now"
        log "prompted ${sid:0:8} in $name (pane $paneid) after reset $reset"
        state="working"
      fi
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s	%s\n' \
      "$sid" "$name" "$paneid" "$ver" "$ctx" "$state" "$reset" "$acted" \
      "$resumed" "$spent" "$rd" "$optout" "$model" "$idle" >> "$tmp"
  done

  mv "$tmp" "$STATUS"
  sweep_repos
  if [ "$DRY" = 1 ]; then
    { printf 'SESSION\tWINDOW\tPANE\tVER\tCONTEXT\tSTATE\tRESET\tACTION\tRESUMED\tSPENT\tCACHED\tOPTOUT\tMODEL\tIDLE\n'
      awk -F'\t' 'BEGIN{OFS="\t"} {$1=substr($1,1,8);
        if ($9!="-" && $9!="") $9=strftime("%m-%d %H:%M",$9); print}' "$STATUS"
    } | column -t -s $'\t'
  fi
  return 0
}

if [ "$MODE" = daemon ]; then
  log "watchdog started (interval ${INTERVAL}s)"
  while :; do pass; sleep "$INTERVAL"; done
else
  pass
fi
