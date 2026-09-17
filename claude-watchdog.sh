#!/usr/bin/env bash
# claude-watchdog.sh -- notice a Claude window that stopped at a usage limit,
# and prompt it to carry on once the limit has reset.
#
#   claude-watchdog.sh --once        one pass, act if due
#   claude-watchdog.sh --dry-run     one pass, print what it WOULD do
#   claude-watchdog.sh --daemon      poll forever (the systemd unit uses this)
#   claude-watchdog.sh --status      print the state table it publishes
#   claude-watchdog.sh --tree        the window tree this scheduler keeps
#   claude-watchdog.sh --check [NAME] resolve schedule entries; launch nothing
#                                    (NAME is a file, a basename or a slug;
#                                     add --body to see the exact paste)
#   claude-watchdog.sh --on|--off    enable/disable acting (the dashboard's 'w')
#   claude-watchdog.sh --optout ID   never prompt that session (dashboard: space)
#   claude-watchdog.sh --optin ID    undo it
#   claude-watchdog.sh --profile work ...   drive a second account
#   claude-watchdog.sh --reload      make the running daemon re-read everything
#   claude-watchdog.sh --install     install + start the systemd user service
#   claude-watchdog.sh --uninstall   stop and remove it
#
# SETTINGS come from ~/.config/muxtopus/config and, for a named account,
# ~/.config/muxtopus/profiles/<name>.conf -- the WATCHDOG_* keys listed in
# profile.sh. The daemon notices an edit to either file within one interval
# and re-executes itself; --reload (or systemctl --user reload) does it now.
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

# THE ACCOUNT PROFILE. One watchdog per Claude account: this instance watches
# exactly one config dir, keeps its own state, and drives its own tmux session.
# Two independent stacks beat one daemon reasoning about two accounts, because
# every figure it judges a session against -- the session budget, the weekly
# budget, the reset time -- is PER ACCOUNT, so a shared daemon would carry two
# of everything anyway and could still hand one account's reset time to the
# other account's window.
#
# Selected by --profile NAME, else inherited from CLAUDE_CONFIG_DIR, else the
# default account, whose paths are byte-identical to what they always were.
# The arguments as given, kept for the daemon to re-exec itself with.
_ARGV=("$@")
. "$(dirname "$(readlink -f "$0")")/profile.sh"
if [ "${1:-}" = "--profile" ]; then
  [ -n "${2:-}" ] || { echo "--profile needs a name" >&2; exit 2; }
  mux_use_profile "$2"; shift 2
fi
mux_export_config_dir
mux_tmux_env

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/claude-watchdog$MUX_SUFFIX"
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
USAGE="$STATE_DIR/usage.tsv"
# SESSION MONITORING is a SEPARATE power from the restart flag, and a separate
# switch. Restarting a window that already stopped cannot lose anything;
# telling a working window to wrap up changes what it is doing, so it is opt-in
# on its own and defaults to off.
MONITOR="$STATE_DIR/monitor"
# One file per session holding the single line to hand it. The hook inside the
# session reads it and DELETES it, so a directive lands exactly once.
DIRECTIVES="$STATE_DIR/directives"
# What we have already said, so a band speaks once per limit window:
#   sid <TAB> band <TAB> reset_epoch <TAB> when
WOUND="$STATE_DIR/wound"
# Per-session exemption from WIND-DOWNS, kept apart from the restart opt-out
# above because they are different powers: a lane can be safe to restart after
# a limit and still be one you never want interrupted mid-turn. ABSENT MEANS
# ENABLED, so a new session is covered without opting in.
MON_OPTOUT="$STATE_DIR/monitor-optout"
# SCHEDULED WINDOWS live outside the state dir on purpose: they are the user's
# hand-editable orders, not this daemon's bookkeeping. One .md per window to
# open; templates/ holds prompt bodies. The dashboard renders the folder and
# marks what it cannot parse as corrupted; this side simply skips those.
SCHEDULES="$MUX_SCHEDULES"
# HANDOFFS LIVE OUTSIDE THE REPO, one folder per account. They used to be
# written as STATUS-<window>.md into the working tree, which put a scratch file
# under version control and -- once a second account works the same tree --
# lets two windows of the same name overwrite each other's handoff. A finished
# one is MOVED to done/ by handover.sh rather than deleted, so the record of
# what a lane did outlives the lane.
HANDOVERS="$MUX_HANDOVERS"
REPOS_AT="$STATE_DIR/repos.at"
# WHY EACH PENDING ENTRY IS NOT RUNNING, republished every pass:
#   file <TAB> verdict <TAB> reason <TAB> when
# verdict is due | waiting | blocked | stalled. It exists because the only
# answer this scheduler could give to "why has that not fired" used to be
# silence -- see sched_due. The dashboard renders it; the log carries the
# CHANGES, so a stall is one line rather than one line every thirty seconds.
SCHED_WHY="$STATE_DIR/sched-why.tsv"
# THE WINDOW TREE, one row per window this scheduler has opened:
#   slug <TAB> parent <TAB> window-id <TAB> pane-id <TAB> launched-at <TAB> file
#
# TMUX HAS NO WINDOW HIERARCHY. Windows are a flat, indexed list per session:
# there is no parent to set and nothing to collapse. So a tree has to be DATA
# kept beside the session plus a VIEW that renders it -- this file is the data,
# the dashboard is the view, and the flat list gets the cheap half of the
# benefit by keeping a subtree contiguous (see subtree_last_index).
#
# It is also the answer to "what did that window then DO": the pane id is here,
# so the dashboard can sample the pane and the handover file rather than the
# scheduler having to follow the work it started.
TREE="$STATE_DIR/tree.tsv"
# PROOF OF LIFE, rewritten every pass:
#   epoch <TAB> sessions <TAB> pending <TAB> interval
# The log only records CHANGES, which is right for a log and useless for "is it
# alive": measured on this box, the last line was four days old while the daemon
# was polling every 30 seconds, and liveness had to be inferred from the mtimes
# of files it happens to rewrite. So it says so directly, and the dashboard
# renders it as "scanned 12s ago".
HEARTBEAT="$STATE_DIR/heartbeat"
# ...and the log gets one line an hour anyway, because the file above is the
# CURRENT answer and a log is the only thing that can answer "was it running at
# 4am". 0 turns it off.
HEARTBEAT_LOG_MIN="${WATCHDOG_HEARTBEAT_LOG:-60}"
# A row whose window is long gone stops being interesting; one whose window is
# gone but recent is still an answer to "has that finished yet".
TREE_KEEP=$(( 14 * 86400 ))
# The last time a missing usage reading made us ask for a probe. Bounded, or a
# permanently broken usage cache would start a throwaway session every pass.
SCHED_PROBE_AT="$STATE_DIR/sched-probe.at"
SCHED_PROBE_EVERY=900
# Working trees change far more slowly than sessions do, and each one costs a
# git fork, so the repo sweep runs on its own slower clock.
REPO_EVERY=120

DEFAULT_MSG="The usage limit has reset. Continue from where you left off."
INTERVAL="${WATCHDOG_INTERVAL:-30}"
# Minutes between /usage probes. Each one starts a throwaway claude process.
USAGE_EVERY="${WATCHDOG_USAGE_EVERY:-60}"
# A window is only prompted once per (session, reset) pair, so the grace is
# just insurance against a clock edge, not a retry cadence.
GRACE=20

# The bands, as a percentage of the 5-hour session budget.
SOFT_PCT="${WATCHDOG_SOFT_PCT:-65}"
HARD_PCT="${WATCHDOG_HARD_PCT:-85}"
# Above this context a window is cheaper to RESTART from a handoff than to
# carry, because every request re-reads the whole of it. It is also the test
# for whether a wind-down buys anything, which is why the hard band asks.
FRESH_CTX="${WATCHDOG_FRESH_CTX:-150000}"
# Below this weekly figure /low-priority is on the table: it continues NOW
# against the weekly budget instead of idling until the session resets.
LOWPRI_WEEK="${WATCHDOG_LOWPRI_WEEK:-40}"
# HOW OLD A BUDGET READING MAY BE and still decide anything. The session bucket
# refills over five hours, so a percentage read three hours ago says nothing
# useful about now -- and "the budget reads fresh" is a gate that OPENS a
# window, so it must not open on a figure that predates the work. The reset
# EPOCH is exempt: it is an absolute moment, and it stays true however old the
# row that carries it is.
USAGE_STALE="${WATCHDOG_USAGE_STALE:-180}"
# HOW LONG A LANE MAY SIT BEFORE NOTHING IS GOING TO TOUCH IT. A scheduled
# window that is idle this long with an OPEN handover and no pending entry
# naming it is reported as `stranded` rather than `idle`. MEASURED this week:
# four lanes sat at `idle 3d` with open handovers and nothing anywhere said so;
# `idle` is a fact about the last turn, `stranded` is a fact about the future.
# 0 turns it off.
STRANDED_MIN="${WATCHDOG_STRANDED:-120}"

mkdir -p "$STATE_DIR"
[ -f "$MSGFILE" ] || printf '%s\n' "$DEFAULT_MSG" > "$MSGFILE"

MODE="--once"; DRY=0
case "${1:---once}" in
  --once)    MODE=once ;;
  --dry-run) MODE=once; DRY=1 ;;
  --daemon)  MODE=daemon ;;
  --status)  [ -f "$ENABLED" ] && r=on || r=off
             [ -f "$MONITOR" ] && m=on || m=off
             hb="-"
             if [ -f "$STATE_DIR/heartbeat" ]; then
               hb="$(awk -F'\t' -v n="$(date +%s)" '{printf "%ds ago", n-$1}' "$STATE_DIR/heartbeat")"
             fi
             echo "# account=$MUX_LABEL restart=$r monitor=$m soft=$SOFT_PCT% hard=$HARD_PCT% interval=${INTERVAL}s usage-every=${USAGE_EVERY}m scanned=$hb"
             [ -f "$STATUS" ] && cat "$STATUS"; exit 0 ;;
  --on)      : > "$ENABLED"; echo "watchdog enabled"; exit 0 ;;
  --off)     rm -f "$ENABLED"; echo "watchdog disabled"; exit 0 ;;
  --reload)  # SIGHUP makes the daemon re-exec (see the daemon loop). Sent to
             # the unit's main pid directly rather than via `systemctl reload`
             # so it also works on a unit installed before ExecReload existed.
             pid="$(systemctl --user show -p MainPID --value "$MUX_UNIT" 2>/dev/null)"
             pidf="${XDG_RUNTIME_DIR:-/tmp}/muxtopus-wd$MUX_SUFFIX.pid"
             if [ "${pid:-0}" -gt 0 ] 2>/dev/null; then :
             elif [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null; then pid="$(cat "$pidf")"
             else echo "watchdog ($MUX_LABEL) is not running" >&2; exit 1; fi
             kill -HUP "$pid" && echo "watchdog ($MUX_LABEL) reloading (pid $pid)"; exit $? ;;
  --monitor-on)  mkdir -p "$DIRECTIVES"; : > "$MONITOR"
                 echo "session monitoring enabled"; exit 0 ;;
  --monitor-off) rm -f "$MONITOR"; echo "session monitoring disabled"; exit 0 ;;
  --monitor-optout) [ -n "${2:-}" ] || { echo "need a session id" >&2; exit 2; }
             grep -qxF "$2" "$MON_OPTOUT" 2>/dev/null || printf '%s\n' "$2" >> "$MON_OPTOUT"
             echo "will not wind down $2"; exit 0 ;;
  --monitor-optin) [ -n "${2:-}" ] || { echo "need a session id" >&2; exit 2; }
             if [ -f "$MON_OPTOUT" ]; then grep -vxF "$2" "$MON_OPTOUT" > "$MON_OPTOUT.tmp" || true
                                           mv "$MON_OPTOUT.tmp" "$MON_OPTOUT"; fi
             echo "may wind down $2"; exit 0 ;;
  --monitor)     if [ -f "$MONITOR" ]; then echo on; else echo off; fi; exit 0 ;;
  --optout)  [ -n "${2:-}" ] || { echo "need a session id" >&2; exit 2; }
             grep -qxF "$2" "$OPTOUT" 2>/dev/null || printf '%s\n' "$2" >> "$OPTOUT"
             echo "watchdog will leave $2 alone"; exit 0 ;;
  --optin)   [ -n "${2:-}" ] || { echo "need a session id" >&2; exit 2; }
             if [ -f "$OPTOUT" ]; then grep -vxF "$2" "$OPTOUT" > "$OPTOUT.tmp" || true
                                       mv "$OPTOUT.tmp" "$OPTOUT"; fi
             echo "watchdog will resume $2"; exit 0 ;;
  --tree)    MODE=tree ;;
  --check)   MODE=check; CHECK_ARG="${2:-}"; CHECK_BODY=""
             case "${2:-}" in --body) CHECK_ARG=""; CHECK_BODY=1 ;; esac
             case "${3:-}" in --body) CHECK_BODY=1 ;; esac ;;
  --install|--uninstall) MODE="${1#--}" ;;
  -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac

UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/claude-watchdog$MUX_SUFFIX.service"
SELF="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SELF")"

if [ "$MODE" = uninstall ]; then
  systemctl --user disable --now "claude-watchdog$MUX_SUFFIX.service" 2>/dev/null
  rm -f "$UNIT"; systemctl --user daemon-reload 2>/dev/null
  echo "removed $UNIT"; exit 0
fi

if [ "$MODE" = install ]; then
  # A USER service, and it only survives logout because apply-logind.sh turned
  # lingering on -- without that the manager stops with your last session and
  # takes this with it, which is the same failure it exists to work around.
  mkdir -p "$UNIT_DIR"
  # BOTH LINES ARE CONDITIONAL, and neither is cosmetic. --profile rejects an
  # empty name, so `--profile "" --daemon` would exit 2 and leave the default
  # account with a unit that restarts forever and never runs; and the default
  # account must be handed no CLAUDE_CONFIG_DIR at all, because setting it is
  # what sends a logged-in machine to the login screen (see profile.sh).
  cat > "$UNIT" <<UNITEOF
[Unit]
Description=Prompt Claude Code windows ($MUX_LABEL) to continue after a usage limit resets
After=default.target

[Service]
Type=simple
${MUX_PROFILE:+Environment=CLAUDE_CONFIG_DIR=$MUX_CONFIG_DIR}
ExecStart=$SELF ${MUX_PROFILE:+--profile "$MUX_PROFILE"} --daemon
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNITEOF
  systemctl --user daemon-reload
  systemctl --user enable --now "claude-watchdog$MUX_SUFFIX.service" >/dev/null 2>&1
  # RESTART, not just enable: a running daemon is a bash loop holding the copy
  # of this script it parsed at start, so `enable --now` on an already-active
  # unit would leave an edited watchdog unused. Same reason deck-status has R.
  systemctl --user restart "claude-watchdog$MUX_SUFFIX.service" >/dev/null 2>&1
  # Armed on install: watching without acting is not what anyone wants from
  # it. Turn it off any time with 'w' on the dashboard, or --off here.
  : > "$ENABLED"
  if systemctl --user is-active --quiet "claude-watchdog$MUX_SUFFIX.service"; then
    echo "installed and running: $UNIT  (account: $MUX_LABEL)"
    echo "armed -- press w on the dashboard to disarm"
  else
    echo "installed but NOT running; check: systemctl --user status claude-watchdog$MUX_SUFFIX" >&2
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
  for f in "$MUX_CONFIG_DIR"/projects/*/"$sid".jsonl; do
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

# WHEN THIS SESSION LAST TOOK A TURN, as an epoch.
#
# NOT the transcript mtime, which this used to read and which is wrong by
# hours: Claude Code keeps appending bookkeeping records long after the work
# stops -- last-prompt, ai-title, mode, permission-mode, atis-latch,
# bridge-session -- and none of them carries a timestamp. MEASURED on a window
# that finished at 12:28 UTC: mtime said 20:06, so the dashboard called it idle
# for 31 seconds when it had been idle for four and a half hours, which is
# exactly backwards from what the column is for.
#
# So read the last record that IS a turn. The tail is bounded because these
# files reach tens of MB, and 200 lines is far more than the handful of
# trailing metadata records.
last_turn_epoch() {
  local f="$1" ts
  ts="$(tail -n 200 "$f" 2>/dev/null |
        jq -r 'select(.type=="assistant" or .type=="user") | .timestamp // empty' 2>/dev/null |
        tail -1)"
  [ -n "$ts" ] || return 1
  date -d "$ts" +%s 2>/dev/null
}

# One field out of the usage cache. Cheap -- eight lines, and the watchdog
# already keeps it warm on its own hourly clock.
usage_val() {
  awk -F'\t' -v k="$1" '$1==k{print $2; exit}' "$USAGE" 2>/dev/null
}

# Which band a session is in: 0 none, 1 soft, 2 hard.
#
# The WEEK escalates rather than setting the band by itself, because the two
# budgets mean different things: the session bucket refills in five hours, the
# weekly one will not refill tonight. So a nearly-spent week turns a soft band
# hard and gives an otherwise-quiet session a nudge -- but it never winds down
# a session that has barely started, which would spend a checkpoint turn to
# save a bucket that is about to refill anyway.
band_for() {
  local s="${1%%.*}" w="${2%%.*}" b=0
  case "$s" in ''|*[!0-9]*) s=0 ;; esac
  case "$w" in ''|*[!0-9]*) w=0 ;; esac
  [ "$s" -ge "$SOFT_PCT" ] && b=1
  [ "$s" -ge "$HARD_PCT" ] && b=2
  if [ "$w" -ge "$HARD_PCT" ]; then
    [ "$b" -eq 1 ] && b=2
    [ "$b" -eq 0 ] && b=1
  fi
  printf '%s' "$b"
}

# The last time this session was wound down, as an epoch.
last_wound() {
  awk -F'\t' -v s="$1" '$1==s{v=$4} END{print (v?v:"-")}' "$WOUND" 2>/dev/null || echo -
}

# Hand a WORKING session one line about its budget, at most once per band per
# limit window. The session is never told why -- it reads as an instruction,
# not as a negotiation -- and this ledger is the only place the reason is
# recorded, which is the whole point of deciding out here.
wind_down() {
  local sid="$1" name="$2" ctx="$3" st="$4" oo="$5" spct="$6" wpct="$7" key="$8" now="$9"
  [ -f "$MONITOR" ] || return 0
  # A dry run reports; it never speaks to a session.
  [ "$DRY" = 1 ] && return 0
  grep -qxF "$sid" "$MON_OPTOUT" 2>/dev/null && return 0
  # Only a session that is DOING something can be wound down. An idle one has
  # already stopped, and typing at it would start work rather than end it.
  [ "$st" = "working" ] || return 0

  local b; b="$(band_for "$spct" "$wpct")"
  [ "$b" = 0 ] && return 0

  # THE HARD BAND ONLY FIRES WHEN IT BUYS SOMETHING. A wind-down costs a
  # checkpoint turn, and that is only worth paying when the resume will be a
  # FRESH window -- a big context being the whole reason to restart rather than
  # continue -- or when /low-priority is not available to carry this session
  # through the limit. Otherwise the cheapest correct thing is to let it reach
  # the banner and continue from there, which costs nothing at all.
  if [ "$b" = 2 ]; then
    local wi="${wpct%%.*}"
    case "$wi" in ''|*[!0-9]*) wi=0 ;; esac
    if [ "${ctx:-0}" -le "$FRESH_CTX" ] && [ "$wi" -lt "$LOWPRI_WEEK" ]; then
      return 0
    fi
  fi

  # QUANTIZE THE WINDOW KEY. session_reset_at is re-derived from a wall clock
  # the panel rounds, and it drifts a minute between scrapes -- usage.log shows
  # "resets 10:39" four times then "10:40". An unrounded key makes that jitter
  # look like a NEW limit window, so the same band fires again: MEASURED, one
  # session took the soft nudge twice on keys 60 seconds apart. Rounding to a
  # quarter hour is stable against that and cannot merge two real windows,
  # which are five hours apart.
  local qkey=$(( ( ${key:-0} + 450 ) / 900 * 900 ))
  if awk -F'\t' -v s="$sid" -v b="$b" -v k="$qkey" \
       '$1==s && $2==b && $3==k{f=1} END{exit !f}' "$WOUND" 2>/dev/null; then
    return 0
  fi

  local msg reset
  reset="$(usage_val session_reset)"
  if [ "$b" = 2 ]; then
    msg="Budget checkpoint: land the step you are on now and commit it, then write a handoff to $HANDOVERS/STATUS-$(lane_slug_of "$name").md saying what is done, what is next and anything half-finished. Then stop. The budget resets at ${reset:-the top of the hour}; do not start what you cannot finish before then."
  else
    msg="Budget note: this window is past the halfway mark. Stop spawning subagents unless a task genuinely needs one, and prefer targeted greps and partial reads over whole files."
  fi

  mkdir -p "$DIRECTIVES"
  printf '%s\n' "$msg" > "$DIRECTIVES/$sid"
  printf '%s\t%s\t%s\t%s\n' "$sid" "$b" "$qkey" "$now" >> "$WOUND"
  log "wound down ${sid:0:8} in $name band=$b session=${spct}% week=${wpct}% ctx=$ctx"
  wound="$now"
}

# ------------------------------------------------------------- schedules
# One header field. Values may contain colons (a Windows path, a time), so
# take everything after the first "key: " rather than splitting on the colon.
sched_field() {
  awk -v k="$2" '/^---$/{exit} index($0, k": ")==1{print substr($0, length(k)+3); exit}' "$1"
}

# Everything after the first --- line: the prompt body.
sched_body() {
  awk 'p{print} /^---$/{p=1}' "$1"
}

# THE LANE SLUG OF A LIVE WINDOW: its tmux name with the depth markers off.
#
# A scheduled window is named ➥<slug>, and the slug -- not the display name --
# is what every handover path is built from. Without this a wind-down would ask
# for STATUS-➥ 27-storage.md while the footer of the same window told the worker
# STATUS-27-storage.md: the same divergence as the derived-slug bug below, one
# layer down, and unfired only because no scheduled window has been wound down
# yet.
lane_slug_of() {
  local n="${1//➥/}"
  printf '%s' "$n"
}

# THE SLUG IS THE LANE'S NAME, and it is the same string in four places: the
# tmux window, the handover file, the `handover.sh done <slug>` the worker is
# told to run at the end, and the tree below. One string, or those four
# disagree.
#
# MEASURED, first run of the day: `title: 27-storage wave 2` derived the slug
# 27-storage-wave-2, while the lane's own brief told the same worker to use
# `handover.sh path 27-storage`. Two handover files for one lane, nothing
# watching the one that was written, and no warning anywhere. So:
#
#   * an explicit `slug:` field WINS over the title, which is how you pin a
#     lane's name when its title reads like a sentence;
#   * a derived slug that is not its source character for character is
#     REPORTED (sched_slug_warn) rather than adopted in silence;
#   * and the resolved slug is rendered INTO the pasted body, so the worker
#     reads the same answer the tooling computed instead of guessing.
sched_sanitise() {
  local s
  s="$(printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '-')"
  printf '%s' "${s:0:22}"
}

sched_slug() {
  local f="$1" s
  s="$(sched_field "$f" slug)"
  [ -n "$s" ] || s="$(sched_field "$f" title)"
  [ -n "$s" ] || s="$(basename "$f" .md)"
  sched_sanitise "$s"
}

# Empty when the slug is exactly what was written down; otherwise the sentence
# that says why it is not. Not fatal -- a name that sanitises is still a name --
# but it is the difference between a lane the tooling can follow and two files
# nobody reconciles, so it is said out loud in the log, in --check and in the
# dashboard rather than left to be rediscovered.
sched_slug_warn() {
  local f="$1" raw src slug
  raw="$(sched_field "$f" slug)"; src="slug"
  if [ -z "$raw" ]; then raw="$(sched_field "$f" title)"; src="title"; fi
  [ -n "$raw" ] || return 0
  slug="$(sched_sanitise "$raw")"
  [ "$slug" = "$raw" ] && return 0
  if [ "${#raw}" -gt 22 ] && [ "${raw:0:22}" = "$slug" ]; then
    printf 'the %s is %s characters, so the slug is TRUNCATED to "%s" -- set slug: to pin it' \
      "$src" "${#raw}" "$slug"
  else
    printf 'the %s "%s" is not a slug; it becomes "%s" -- set slug: to pin it' \
      "$src" "$raw" "$slug"
  fi
}

# How old the usage cache is, in minutes. -1 when there is no readable stamp,
# which is a different answer from "old" and is treated as one.
usage_age_min() {
  local at now
  at="$(usage_val at)"
  case "$at" in ''|*[!0-9]*) printf -- '-1'; return 0 ;; esac
  now="$(date +%s)"
  printf '%s' $(( (now - at) / 60 ))
}

# Is this item due, and WHY.
#
#   0  due       -- SCHED_WHY_TXT says which gate fired
#   1  waiting   -- SCHED_WHY_TXT says what it is waiting for
#   2  stalled   -- it cannot be evaluated at all, and that is now SAID
#
# `at: reset` HAS TWO GATES, and they mean materially different things. The
# README used to describe them as one sentence, which cost a round of guessing
# about why a window opened:
#
#   1. THE BUDGET READS FRESH (session_pct <= 10). A rolling window that has
#      just rolled has no reset time at all -- the documented trap -- so a
#      barely-touched budget is due on its own account. It fires when the
#      account is idle, whether or not anything ever hit a limit.
#   2. THE WINDOW ROLLED OVER (now >= session_reset_at + GRACE). It fires when
#      the five hours are up, whatever the budget then reads.
#
# Both of today's launches went through this and each took a DIFFERENT gate --
# the first the reset epoch (10:10 had passed), the second the fresh budget
# (4%). Which one fired is now in the log line, so a launch is explicable
# afterwards instead of being reconstructed.
#
# AND A MISSING READING IS NOT A "NO". sched_due used to coerce an empty
# session_pct to 100, which fails gate 1, while an empty session_reset_at
# fails gate 2 -- so an unreadable usage.tsv made every `at: reset` entry
# PERMANENTLY undue, with no log line and no error. That is the worst failure a
# scheduler can have and it is what verdict 2 exists to end.
SCHED_WHY_TXT=""
# Set alongside verdict 2 when a fresh /usage reading is what would unblock it.
SCHED_WANT_PROBE=0
sched_due() {
  local at="$1" now="$2" e sp age hhmm
  SCHED_WHY_TXT=""; SCHED_WANT_PROBE=0
  if [ "$at" = reset ]; then
    sp="$(usage_val session_pct)"; sp="${sp%%.*}"
    e="$(usage_val session_reset_at)"
    age="$(usage_age_min)"
    case "$sp" in ''|*[!0-9]*) sp="" ;; esac
    case "$e" in ''|*[!0-9]*) e="" ;; esac
    hhmm="-"; [ -n "$e" ] && hhmm="$(date -d "@$e" '+%H:%M' 2>/dev/null)"

    # CAN GATE 1 SEE ANYTHING AT ALL? A blind gate is not a closed one, and
    # the difference is the whole of observation 3: an absent reading used to
    # be coerced into "not due" and was then indistinguishable from a budget
    # that is genuinely still full.
    local blind=""
    if [ -z "$sp" ]; then
      blind="$USAGE carries no session_pct"
    elif [ "$age" -lt 0 ]; then
      blind="$USAGE carries no readable timestamp, so its ${sp}% cannot be trusted"
    elif [ "$age" -gt "$USAGE_STALE" ]; then
      blind="the ${sp}% reading is ${age}m old, past the ${USAGE_STALE}m limit"
    fi

    if [ -z "$blind" ] && [ "$sp" -le 10 ]; then
      SCHED_WHY_TXT="due: the budget reads fresh (${sp}%, read ${age}m ago)"
      return 0
    fi
    if [ -n "$e" ] && [ "$now" -ge $(( e + GRACE )) ]; then
      SCHED_WHY_TXT="due: the session window rolled over at $hhmm"
      return 0
    fi

    # Neither gate fired. A blind gate 1 is worth a probe whatever happens
    # next: it is the only thing that can make this entry due before the reset.
    [ -n "$blind" ] && SCHED_WANT_PROBE=1

    # STALLED IS RESERVED FOR "no future moment can make this due". With a
    # reset epoch ahead the entry has a definite appointment, so a stale
    # budget only costs it the earlier of two gates -- worth saying, not worth
    # calling a stall.
    if [ -n "$blind" ] && [ -z "$e" ]; then
      SCHED_WHY_TXT="STALLED: neither gate can fire -- $blind, and there is no session_reset_at either; asking for a fresh /usage probe"
      return 2
    fi
    if [ -z "$e" ]; then
      SCHED_WHY_TXT="waiting: the budget is ${sp}% (fires at 10%); there is no session_reset_at, so only the fresh-budget gate can fire"
      return 1
    fi
    if [ -n "$blind" ]; then
      SCHED_WHY_TXT="waiting: the reset at $hhmm has not passed, and the fresh-budget gate is blind ($blind); a probe has been asked for"
      return 1
    fi
    SCHED_WHY_TXT="waiting: the budget is ${sp}% (fires at 10%) and the reset at $hhmm has not passed"
    return 1
  fi
  e="$(date -d "$at" +%s 2>/dev/null)"
  case "$e" in
    ''|*[!0-9]*) SCHED_WHY_TXT="STALLED: at: \"$at\" is not a time date -d understands"; return 2 ;;
  esac
  if [ "$now" -ge "$e" ]; then
    SCHED_WHY_TXT="due: the time $at passed"
    return 0
  fi
  SCHED_WHY_TXT="waiting: until $at, $(( (e - now + 59) / 60 ))m away"
  return 1
}

# ARE THIS ENTRY'S DEPENDENCIES FINISHED?
#
# `after: <slug>` holds an entry until that lane is done, and `after: a, b, c`
# holds it until ALL of them are. It exists because the release entry once
# depended on a PR merge landing first and there was no way to say so -- the
# only options were to launch it too early or to sit watching for the moment to
# launch it by hand. The LIST is what an orchestrator needs: "integrate the
# four lanes" is one entry waiting on four, not four entries waiting in a
# chain, and a chain would also serialise work that ran in parallel.
#
# FINISHED MEANS ONE OF TWO THINGS, in this order:
#   * its handover has been marked done (moved into done/ by handover.sh) --
#     the lane said so itself, which is the strong signal; or
#   * a window the tree knows about has EXITED without leaving an open
#     handover -- the work is over whether or not it went well.
# An open handover means the lane is still running: that file is written early
# and lives until `handover.sh done` moves it.
#
# There is deliberately NO TIMEOUT. A dependency that gives up and runs anyway
# is worse than one that waits, and a wait is now visible in three places
# (--check, the WHY line in the dashboard, and a log line when the verdict
# changes) rather than being the silence it would once have been.

# A duration in seconds as one short human figure, and the same for a file's age.
dur_hm() {
  local d="${1:-0}"
  case "$d" in ''|*[!0-9-]*) d=0 ;; esac
  [ "$d" -lt 0 ] && d=0
  if   [ "$d" -lt 3600 ];   then printf '%dm' $(( d / 60 ))
  elif [ "$d" -lt 172800 ]; then printf '%dh' $(( d / 3600 ))
  else                           printf '%dd' $(( d / 86400 )); fi
}
ago_hm() {
  local t n
  t="$(stat -c %Y "$1" 2>/dev/null)" || { printf '?'; return 0; }
  n="$(date +%s)"
  dur_hm $(( n - ${t:-0} ))
}

# ONE dependency, judged. The short reason goes to stdout; the verdict is the
# exit code: 0 finished, 1 still holding.
sched_dep_state() {
  local dep="$1" wid
  if [ -f "$HANDOVERS/done/STATUS-$dep.md" ]; then
    printf 'its handover is in done/'; return 0
  fi
  if [ -f "$HANDOVERS/STATUS-$dep.md" ]; then
    printf 'handover open %s ago, not marked done (handover.sh done %s)' \
      "$(ago_hm "$HANDOVERS/STATUS-$dep.md")" "$dep"
    return 1
  fi
  wid="$(tree_field "$dep" 3)"
  if [ -n "$wid" ]; then
    if tree_live_windows | grep -qxF "$wid"; then
      printf 'its window %s is still open and it has written no handover' "$wid"; return 1
    fi
    printf 'its window %s has exited' "$wid"; return 0
  fi
  printf 'nothing by that name has launched, and there is no handover for it'
  return 1
}

# The slugs in an `after:` field. Comma or space separated, because both read
# naturally in a header line and neither can occur inside a slug.
sched_after_deps() {
  local list="${1//,/ }"
  printf '%s\n' $list
}

# The whole field, judged. 0 every named lane is finished, 1 at least one is
# still holding, 2 it can never resolve.
#
# The sentence names the FIRST lane still holding and how many are left, rather
# than all of them: that is the one to look at, and a verdict that lists four
# reasons is a verdict nobody reads. --check prints the per-lane breakdown when
# there is more than one.
sched_after_ok() {
  local list="$1" self="${2:-}" dep reason rc n=0 held=0 first="" firstwhy="" last=""
  SCHED_WHY_TXT=""
  [ -n "$list" ] || return 0
  local -a deps=()
  while IFS= read -r dep; do [ -n "$dep" ] && deps+=("$dep"); done < <(sched_after_deps "$list")
  n=${#deps[@]}
  [ "$n" -gt 0 ] || return 0
  # SELF-REFERENCE IN ANY POSITION, checked before anything is evaluated: an
  # entry that waits for itself can never fire, and finding that out from the
  # third slug of a list is no different from finding it out from the first.
  for dep in "${deps[@]}"; do
    if [ "$dep" = "$self" ]; then
      SCHED_WHY_TXT="STALLED: after: names this entry's own slug ($dep), which can never finish first"
      return 2
    fi
  done
  for dep in "${deps[@]}"; do
    reason="$(sched_dep_state "$dep")"; rc=$?
    last="$reason"
    [ "$rc" = 0 ] && continue
    held=$(( held + 1 ))
    [ -n "$first" ] || { first="$dep"; firstwhy="$reason"; }
  done
  if [ "$held" = 0 ]; then
    if [ "$n" = 1 ]; then SCHED_WHY_TXT="after ${deps[0]}: finished ($last)"
    else SCHED_WHY_TXT="after: all $n finished (${deps[*]})"; fi
    return 0
  fi
  if [ "$n" = 1 ]; then
    SCHED_WHY_TXT="blocked: waiting for $first -- $firstwhy"
  else
    SCHED_WHY_TXT="blocked: waiting for $held of $n -- next: $first, $firstwhy"
  fi
  return 1
}

# WHICH LANES ANY PENDING ENTRY WOULD TOUCH, as one space-delimited set built
# at most once per pass. Cheap because the answer is the same for every session
# in a pass, and a pass that never asks never pays for it.
#
# Three ways an entry names a lane: it IS that lane (its slug), it is the
# `resume-<lane>.md` the dashboard's "Schedule ➥resume" writes, or its `after:`
# is waiting for it. The basename goes in as well as the slug because a resume
# entry's SLUG is truncated to 22 characters while its filename is not --
# `resume-sched-options-core` keeps its name and loses its slug.
SCHED_NAMED=""
sched_named_slugs() {
  local f st b
  SCHED_NAMED=" "
  [ -d "$SCHEDULES" ] || return 0
  for f in "$SCHEDULES"/*.md; do
    [ -f "$f" ] || continue
    case "$f" in */README.md) continue ;; esac
    st="$(sched_field "$f" status)"
    [ "$st" = pending ] || continue
    b="$(basename "$f" .md)"
    SCHED_NAMED="$SCHED_NAMED$(sched_slug "$f") $b $(sched_after_deps "$(sched_field "$f" after)" | paste -sd' ' -) "
  done
  return 0
}

# Is some pending entry going to touch this lane? Its own slug, the resume
# entry written for it, or an after: that names it.
sched_names_slug() {
  local slug="$1" r
  [ -n "$SCHED_NAMED" ] || sched_named_slugs
  case "$SCHED_NAMED" in *" $slug "*|*" resume-$slug "*) return 0 ;; esac
  r="$(sched_sanitise "resume-$slug")"
  case "$SCHED_NAMED" in *" $r "*) return 0 ;; esac
  return 1
}

# Record a verdict for one entry, and LOG IT ONLY WHEN IT CHANGES.
#
# Every pass republishes the whole table for the dashboard; the log gets a line
# the first time an entry starts saying something new. That is the difference
# between a stall you can see and a stall nobody ever hears about -- and
# between one log line and 2,880 a day.
sched_note() {
  local f="$1" verdict="$2" why="$3" b prev
  b="$(basename "$f")"
  prev="$(awk -F'\t' -v b="$b" '$1==b{v=$2"|"$3} END{print v}' "$SCHED_WHY" 2>/dev/null)"
  printf '%s\t%s\t%s\t%s\n' "$b" "$verdict" "$why" "$(date +%s)" >> "$SCHED_WHY.tmp"
  [ "$prev" = "$verdict|$why" ] && return 0
  case "$verdict" in
    stalled|blocked) log "schedule $b: $why" ;;
  esac
  return 0
}

# A stalled `at: reset` entry is the one case where a probe is worth starting
# on its own: the entry is waiting on a number the cache does not have, and
# without one it waits forever. Bounded by its own clock so a permanently
# broken usage read costs one probe per quarter hour, not one per pass.
sched_request_probe() {
  local last=0 now
  [ -x "$SCRIPT_DIR/claude-usage.sh" ] || return 0
  [ -f "$MUX_CONFIG_DIR/.credentials.json" ] || return 0
  [ -f "$SCHED_PROBE_AT" ] && read -r last < "$SCHED_PROBE_AT" 2>/dev/null
  now="$(date +%s)"
  [ $(( now - ${last:-0} )) -lt "$SCHED_PROBE_EVERY" ] && return 0
  printf '%s\n' "$now" > "$SCHED_PROBE_AT"
  log "schedule: asking for a /usage probe -- an 'at: reset' entry has no readable budget"
  # In the FOREGROUND, like the hourly probe at the end of a pass: a probe is
  # about four seconds against a thirty second interval, and a backgrounded one
  # would have to be reaped by a loop that is already waiting on its own sleep.
  if [ -n "$MUX_PROFILE" ]; then
    "$SCRIPT_DIR/claude-usage.sh" --profile "$MUX_PROFILE" --ensure 1 >/dev/null 2>&1
  else
    "$SCRIPT_DIR/claude-usage.sh" --ensure 1 >/dev/null 2>&1
  fi
  return 0
}

# Rewrite the status (and stamp launched:) in place. Only the header is
# touched; sed stops caring after the fact because both lines sit before ---.
sched_mark() {
  local f="$1" st="$2"
  sed -i -e "s/^status: .*/status: $st/" \
         -e "s/^launched:.*/launched: $(date '+%Y-%m-%d %H:%M')/" "$f" 2>/dev/null
}

# ---------------------------------------------------------------- the tree
# One column of one row. Column 2 is the parent, 3 the window id, 4 the pane.
tree_field() {
  awk -F'\t' -v s="$1" -v c="$2" '$1==s{v=$c} END{print v}' "$TREE" 2>/dev/null
}

# Every window id tmux currently has, one per line -- asked once per caller
# rather than once per row, because this runs inside a 30s loop.
tree_live_windows() {
  tmux list-windows -a -F '#{window_id}' 2>/dev/null
}

# Record a launch, replacing any earlier row for the same slug: a lane that is
# resumed is the same lane in a new window, not a second entry. Rows for
# windows that are both gone and old are dropped on the way past, which is the
# only pruning this file needs.
tree_record() {
  local slug="$1" parent="$2" wid="$3" pane="$4" f="$5" now live
  now="$(date +%s)"
  live="$(tree_live_windows | paste -sd, -)"
  if [ -f "$TREE" ]; then
    awk -F'\t' -v OFS='\t' -v s="$slug" -v now="$now" -v keep="$TREE_KEEP" \
        -v live=",$live," '
      $1==s { next }
      { if (index(live, "," $3 ",") > 0 || (now - $5) < keep) print }
    ' "$TREE" > "$TREE.tmp" 2>/dev/null
  else
    : > "$TREE.tmp"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$slug" "$parent" "$wid" "$pane" "$now" "$(basename "$f")" >> "$TREE.tmp"
  mv "$TREE.tmp" "$TREE"
}

# FILL IN A PARENT ON A ROW THAT ALREADY EXISTS. Only ever writes an EMPTY
# parent: one already recorded -- by a launch, or by a hand editing the file --
# is never overwritten, so this can run every pass without fighting anybody.
tree_set_parent() {
  local slug="$1" parent="$2"
  [ -f "$TREE" ] || return 1
  awk -F'\t' -v OFS='\t' -v s="$slug" -v p="$parent" \
      '$1==s && $2==""{$2=p} {print}' "$TREE" > "$TREE.tmp" 2>/dev/null || return 1
  mv "$TREE.tmp" "$TREE"
}

# ADOPT A WINDOW BY NAME, as a root. `window:` names the window a lane is
# launched from, and that is its parent whether or not this scheduler opened
# it: the commonest parent on this machine is v113-orchestrator, a hand-made
# orchestrator window that spawned five lanes. Requiring the scheduler to have
# opened the target left every one of those five a root, tree.tsv held nothing
# but roots, and the dashboard's fold keys had no subtree to fold -- the
# feature looked broken because the data said there was no tree.
tree_adopt_name() {
  local name="$1" row wid pane
  [ -n "$name" ] || return 1
  [ -n "$(tree_field "$name" 1)" ] && return 0
  row="$(tmux list-windows -t "$MUX_TMUX" \
           -F $'#{window_name}\t#{window_id}\t#{pane_id}' 2>/dev/null \
         | awk -F'\t' -v n="$name" '$1==n{print $2 "\t" $3; exit}')"
  [ -n "$row" ] || return 1
  wid="${row%%	*}"; pane="${row##*	}"
  [ -n "$wid" ] || return 1
  tree_record "$name" "" "$wid" "$pane" "(adopted)"
}

# How deep a slug sits, counting ancestors. Bounded, so a row that somehow
# names itself as its own parent cannot hang the daemon.
tree_depth() {
  local s="$1" d=0 p
  while [ "$d" -lt 8 ]; do
    p="$(tree_field "$s" 2)"
    [ -n "$p" ] || break
    d=$(( d + 1 )); s="$p"
  done
  printf '%s' "$d"
}

# A slug and every descendant of it, one per line.
tree_family() {
  printf '%s\n' "$1"
  awk -F'\t' -v root="$1" '
    { slug[NR]=$1; par[$1]=$2 }
    END {
      for (i = 1; i <= NR; i++) {
        s = slug[i]; p = par[s]; n = 0
        while (p != "" && n < 8) {
          if (p == root) { print s; break }
          p = par[p]; n++
        }
      }
    }' "$TREE" 2>/dev/null
}

# The highest window index in a subtree, so a new child is inserted AFTER its
# siblings rather than between them. Contiguity in the flat list is most of the
# visual benefit of a tree for almost none of the code -- and it is the only
# part tmux itself can be made to honour.
subtree_last_index() {
  local root="$1" map s wid idx best=""
  map="$(tmux list-windows -t "$MUX_TMUX" -F '#{window_id} #{window_index}' 2>/dev/null)"
  [ -n "$map" ] || return 0
  while IFS= read -r s; do
    [ -n "$s" ] || continue
    wid="$(tree_field "$s" 3)"
    [ -n "$wid" ] || continue
    idx="$(awk -v w="$wid" '$1==w{print $2; exit}' <<<"$map")"
    [ -n "$idx" ] || continue
    if [ -z "$best" ] || [ "$idx" -gt "$best" ]; then best="$idx"; fi
  done < <(tree_family "$root")
  printf '%s' "$best"
}

# ADOPT WINDOWS THE TREE DOES NOT KNOW. A ➥ window can predate this file, be
# renamed by hand, or belong to a lane resumed some other way -- and a tree that
# only knows what it opened itself would draw half a session. An adopted window
# is a ROOT: its parentage is genuinely unknown, and inventing one would be
# worse than saying so.
tree_adopt() {
  local wid name pane slug known
  tmux has-session -t "=$MUX_TMUX" 2>/dev/null || return 0
  while IFS=$'\t' read -r wid name pane; do
    case "$name" in ➥*) ;; *) continue ;; esac
    known="$(awk -F'\t' -v w="$wid" '$3==w{f=1} END{print f}' "$TREE" 2>/dev/null)"
    [ -n "$known" ] && continue
    slug="${name//➥/}"
    [ -n "$slug" ] || continue
    tree_record "$slug" "" "$wid" "$pane" "(adopted)"
  done < <(tmux list-windows -t "$MUX_TMUX" \
             -F $'#{window_id}\t#{window_name}\t#{pane_id}' 2>/dev/null)
  return 0
}

# The tree as text, for --tree and for a reader with no dashboard.
tree_print() {
  local live; live="$(tree_live_windows | paste -sd, -)"
  awk -F'\t' -v live=",$live," '
    { par[$1]=$2; wid[$1]=$3; pane[$1]=$4; at[$1]=$5; src[$1]=$6; order[++n]=$1 }
    function draw(s, depth,   i, pad) {
      pad = ""
      for (i = 0; i < depth; i++) pad = pad "  "
      # ASCII, deliberately: gawk escapes non-ASCII bytes in a POSIX locale,
      # and this daemon must NOT set a UTF-8 one -- the tr -c in
      # sched_sanitise counts BYTES, so a locale change would silently
      # change every slug. (An apostrophe here would end this awk program.)
      printf "%s%s%s\t%s\t%s\t%s\n", pad, (depth ? "+- " : ""), s, wid[s],
             (index(live, "," wid[s] ",") > 0 ? "open" : "closed"),
             strftime("%m-%d %H:%M", at[s])
      for (i = 1; i <= n; i++) if (par[order[i]] == s) draw(order[i], depth + 1)
    }
    END { for (i = 1; i <= n; i++) if (par[order[i]] == "" ) draw(order[i], 0) }
  ' "$TREE" 2>/dev/null
}

# THE PARENT OF A NEW WINDOW, as a slug.
#
# An explicit `parent:` wins -- that is how a hand says it, and how the
# dashboard records it when one window schedules another. Otherwise it is
# DERIVED from `window:`: the target a new window is inserted after is, in
# practice, the window it was launched from, and taking it as the parent is
# what makes the tree fill itself in without anyone maintaining it.
#
# ANY LIVE WINDOW COUNTS, not only one this scheduler opened. That earlier
# restriction meant `window: v113-orchestrator` -- an orchestrator opened by
# hand, which is how every lane on this machine was actually launched -- left
# the lane a root, and a tree whose every node is a root is a flat list. The
# named window is adopted as a root on the way past, so the child has something
# to hang from. A window that is not there at all still yields no parent.
sched_parent() {
  local f="$1" p win
  p="$(sched_field "$f" parent)"
  if [ -n "$p" ]; then sched_sanitise "$p"; return 0; fi
  win="$(sched_field "$f" window)"
  win="${win//➥/}"
  [ -n "$win" ] || return 0
  [ -n "$(tree_field "$win" 1)" ] || tree_adopt_name "$win" >/dev/null 2>&1
  [ -n "$(tree_field "$win" 1)" ] && printf '%s' "$win"
  return 0
}

# RE-ASK THE SCHEDULE FILES WHO THE PARENTS ARE, once a pass.
#
# tree_adopt records a window it finds in tmux as a root, because a bare sweep
# of tmux cannot know parentage -- and a lane launched before its parent was
# adoptable was recorded as a root too. Either way the row is then "known" and
# nothing ever revisits it, so a stranding is permanent. This re-derives the
# parent from the entry that launched the lane and fills it in, and only when
# the row's parent is still empty.
tree_reparent() {
  local f slug parent
  [ -d "$SCHEDULES" ] || return 0
  for f in "$SCHEDULES"/*.md; do
    [ -f "$f" ] || continue
    case "$f" in */README.md) continue ;; esac
    slug="$(sched_slug "$f")"
    [ -n "$slug" ] || continue
    [ -n "$(tree_field "$slug" 1)" ] || continue   # not a window we know
    [ -n "$(tree_field "$slug" 2)" ] && continue   # already has a parent
    parent="$(sched_parent "$f")"
    [ -n "$parent" ] || continue
    [ "$parent" = "$slug" ] && continue            # self-parenting is a cycle
    tree_set_parent "$slug" "$parent" \
      && log "tree: $slug adopted under $parent (from $(basename "$f"))"
  done
  return 0
}

# The window name for a slug at a given depth. THE MARKER CARRIES THE DEPTH,
# because the name is the only per-window string tmux will show: one arrow for
# a scheduled window (unchanged), two for its child, three for anything below
# that. Capped, or a deep chain eats the name it is supposed to label.
tree_wname() {
  local slug="$1" depth="${2:-0}" m="➥"
  [ "$depth" -ge 1 ] && m="➥➥"
  [ "$depth" -ge 2 ] && m="➥➥➥"
  printf '%s%s' "$m" "$slug"
}

# `effort:` PINS THE REASONING EFFORT of the window's session -- the same knob
# as `effortLevel` in settings.json, handed to `claude --effort` at launch.
#
# THE LIST IS WHAT THE INSTALLED CLI ACCEPTS, read from `claude --help` on this
# machine (2.1.x: low, medium, high, xhigh, max), not what the plan guessed. An
# unknown value is DROPPED with a log line rather than passed through, because
# claude exits on an invalid --effort and the window would then never reach a
# prompt: the entry would be marked error for a typo in an optional field.
# Absent means no flag at all, which is the account default.
SCHED_EFFORTS="low medium high xhigh max"
sched_effort_ok() {
  case " $SCHED_EFFORTS " in *" $1 "*) return 0 ;; esac
  return 1
}

# `permission-mode:` PINS THE PERMISSION MODE of the window's session.
#
# WHY IT HAS TO BE AT LAUNCH. A scheduled window is unattended by definition,
# but the launcher passed no mode, so it inherited `defaultMode` from
# settings.json -- `auto` on this machine -- and an auto-mode window that meets
# a decision it will not take on its own simply STOPS, silently, which is
# exactly how four lanes sat idle for 3 days (MEASURED 2026-09-16). It cannot
# be fixed afterwards either: shift+tab cycles auto -> manual -> accept edits ->
# plan -> auto, and bypassPermissions is NOT in that cycle (pressed four times
# on a live lane to check). Launch is the only way in.
#
# THE LIST IS WHAT THE INSTALLED CLI ACCEPTS, read from `claude --help` on this
# machine, not guessed. Unknown is DROPPED with a log line, like effort: claude
# exits on an invalid --permission-mode and the window would never reach a
# prompt. Absent means no flag at all -- the account's own setting, unchanged.
#
# CASE IS FOLDED, deliberately: these are the only camelCase values in an
# otherwise all-lowercase header format, and `bypasspermissions` dropped for
# its spelling would relaunch the very failure this field exists to prevent --
# a window that stops and nobody notices. The canonical spelling is what is
# passed, and the fold is logged so the file can be corrected.
SCHED_PERM_MODES="acceptEdits auto bypassPermissions manual dontAsk plan"
# Echoes the canonical spelling of $1 and returns 0, or returns 1.
sched_perm_canon() {
  local want m
  want="$(printf '%s' "$1" | tr 'A-Z' 'a-z')"
  for m in $SCHED_PERM_MODES; do
    if [ "$(printf '%s' "$m" | tr 'A-Z' 'a-z')" = "$want" ]; then printf '%s' "$m"; return 0; fi
  done
  return 1
}

# THE SUBSTITUTABLE PART OF THE PASTE, exactly as written and before any
# placeholder is resolved: the template (plan only), the body, and the work
# footer. Split out from sched_compose because two things need it -- the
# composer, which substitutes over it, and the placeholder report, which has to
# see what was WRITTEN rather than what came out.
#
# The footer is itself written in placeholders. It says the same bytes it
# always did, but it now says them through the same table the body uses, so
# there is one definition of "the handover file" rather than two.
sched_raw() {
  local f="$1" footer="${2:-1}" type tmpl
  type="$(sched_field "$f" type)"
  tmpl="$(sched_field "$f" template)"
  if [ "$type" = plan ] && [ -n "$tmpl" ] && [ -f "$SCHEDULES/templates/$tmpl.md" ]; then
    cat "$SCHEDULES/templates/$tmpl.md"
    echo
  fi
  sched_body "$f"
  if [ "$type" = work ] && [ "$footer" = 1 ]; then
    echo
    echo "Work in phases, one commit per phase. When done -- or when asked to stop -- write {{HANDOVER}} saying what is done, what is next, and anything half-finished. When the whole item is finished, run: ~/.code/scripts/handover.sh done {{SLUG}}"
  fi
}

# THE PLACEHOLDER TABLE. Every name this scheduler resolves, and nothing else.
#
# The values are only knowable at PASTE time: a sentence written into an entry
# (or into a template shared by twenty of them) cannot name the slug, because
# the slug does not exist until the entry does. So the body carries {{SLUG}}
# and this resolves it the moment the window opens -- which is also why the
# substitution lives in the composer and not in whatever wrote the file.
#
# Pattern quoted, replacement not: quoting the pattern is what stops bash
# treating a placeholder as a glob, and the replacements are paths that must go
# in verbatim.
SCHED_PLACEHOLDERS="SLUG WINDOW HANDOVER QUESTIONS SCHEDULES CWD PARENT"
sched_subst() {
  local txt="$1" slug="$2" wname="$3" cwd="$4" parent="$5"
  txt="${txt//"{{SLUG}}"/$slug}"
  txt="${txt//"{{WINDOW}}"/$wname}"
  txt="${txt//"{{HANDOVER}}"/$HANDOVERS/STATUS-$slug.md}"
  txt="${txt//"{{QUESTIONS}}"/$HANDOVERS/QUESTIONS-$slug.md}"
  txt="${txt//"{{SCHEDULES}}"/$SCHEDULES}"
  txt="${txt//"{{CWD}}"/$cwd}"
  txt="${txt//"{{PARENT}}"/$parent}"
  printf '%s' "$txt"
}

# Every {{NAME}} a HUMAN wrote into an entry, one per line, deduplicated. The
# footer is left out on purpose: its two placeholders are this scheduler's own
# and would otherwise be reported on every work item as if the author had
# chosen them.
sched_placeholders() {
  sched_raw "$1" 0 | grep -o '{{[A-Za-z0-9_]\{1,\}}}' 2>/dev/null | sort -u
}

# Empty when every placeholder in the entry is one of the above; otherwise the
# sentence that says which are not.
#
# AN UNKNOWN PLACEHOLDER IS LEFT ALONE, never blanked: a body that meant to say
# {{PORT}} literally still says it, and one that meant a real substitution gets
# a warning instead of a silently empty sentence. Same rule as the slug -- said
# out loud in the log, in --check and on the dashboard row, rather than
# rediscovered by reading a pane.
sched_placeholder_warn() {
  local f="$1" p unknown=""
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    case " $SCHED_PLACEHOLDERS " in *" ${p:2:${#p}-4} "*) continue ;; esac
    unknown="$unknown $p"
  done < <(sched_placeholders "$f")
  [ -n "$unknown" ] || return 0
  printf 'the body contains%s, which this scheduler does not resolve -- it is pasted as literal text (the table is: %s)' \
    "$unknown" "$(printf '{{%s}} ' $SCHED_PLACEHOLDERS | sed 's/ $//')"
}

# EXACTLY WHAT GETS PASTED, on stdout. One function, so --check reports the
# real thing rather than a description of it that can drift from it.
#
# A plan leads with its template (the contracts live there); a work item is
# followed by the checkpoint footer so every scheduled window is resumable by
# construction. Both lead with the window's own identity -- see sched_slug.
#
# THE IDENTITY LINES ARE NOT SUBSTITUTED. They are built from the resolved
# values out here, so a {{SLUG}} in them would be a placeholder resolving to
# the thing it was already printed from; and a body that contains the literal
# text "{{SLUG}}" -- a brief explaining this feature, say -- must not have the
# header rewritten under it.
sched_compose() {
  local f="$1" slug="$2" wname="$3" parent="${4-}" rest
  [ $# -ge 4 ] || parent="$(sched_parent "$f")"
  echo "[muxtopus] This window is $wname. Its lane slug is: $slug"
  echo "[muxtopus] Its handover file is: $HANDOVERS/STATUS-$slug.md"
  echo "[muxtopus] Use that slug verbatim with handover.sh (path/write/done). If anything"
  echo "[muxtopus] below names a different one, THIS one wins -- a second handover file is"
  echo "[muxtopus] not watched by anything."
  echo
  # The X sentinel keeps the trailing newlines a command substitution would
  # otherwise eat, so the paste is byte-identical to what the files hold.
  rest="$( sched_raw "$f"; printf X )"
  rest="${rest%X}"
  sched_subst "$rest" "$slug" "$wname" "$(sched_field "$f" cwd)" "$parent"
}

# Open the window, get claude to a prompt, paste the body, press Enter.
# `watchdog: off` / `monitor: off`: the only value that means anything is
# `off`, in any case. Anything else, or no line at all, is the default: covered.
sched_off() {
  local v; v="$(sched_field "$1" "$2")"
  [ "${v,,}" = off ]
}

# THE SESSION ID BEHIND A PANE WE JUST OPENED. The opt-out files are keyed by
# session id, and that id does not exist until claude mints it at startup and
# publishes it in sessions/<pid>.json, whose .tmux ends in the pane id. So an
# entry cannot carry one; the launcher looks it up once the prompt is up. It is
# normally there already by then -- the poll is for a slow first write.
sched_pane_sid() {
  local pane="$1" i f t sid
  for i in $(seq 1 10); do
    for f in "$MUX_CONFIG_DIR"/sessions/*.json; do
      [ -f "$f" ] || continue
      t="$(jq -r '.tmux // empty' "$f" 2>/dev/null)"
      [ "${t##*.}" = "$pane" ] || continue
      sid="$(jq -r '.sessionId // empty' "$f" 2>/dev/null)"
      [ -n "$sid" ] && { printf '%s' "$sid"; return 0; }
    done
    sleep 0.5
  done
  return 1
}

launch_schedule() {
  local f="$1" why="${2:-}"
  local type at title win cwd tmpl slug wname idx pane bodyf txt i ready did_trust warn model effort
  local parent depth wid wd_off mon_off sid

  # NO SESSION, NO LAUNCH -- AND NO ERROR. After a reboot this daemon is back
  # (an enabled user unit) long before anyone has run muxtopus, and an item that
  # comes due then must WAIT for the session rather than be failed for a
  # condition that clears the moment someone attaches. Said once in the log,
  # not once per pass.
  if ! tmux has-session -t "=$MUX_TMUX" 2>/dev/null; then
    if [ ! -f "$STATE_DIR/sched-waiting" ]; then
      log "schedule $(basename "$f"): due, but there is no tmux session '$MUX_TMUX' -- waiting for muxtopus"
      : > "$STATE_DIR/sched-waiting"
    fi
    return 1
  fi
  rm -f "$STATE_DIR/sched-waiting"
  type="$(sched_field "$f" type)"
  title="$(sched_field "$f" title)"
  win="$(sched_field "$f" window)"
  cwd="$(sched_field "$f" cwd)"
  tmpl="$(sched_field "$f" template)"
  # `model:` pins the window's model (an alias claude accepts: fable, opus,
  # sonnet, or a full id). Absent, the account's settings.json default applies.
  model="$(sched_field "$f" model)"
  case "$model" in *[!a-zA-Z0-9._\[\]-]*) log "schedule $(basename "$f"): ignoring odd model: \"$model\""; model="" ;; esac
  effort="$(sched_field "$f" effort)"
  if [ -n "$effort" ] && ! sched_effort_ok "$effort"; then
    log "schedule $(basename "$f"): ignoring odd effort: \"$effort\" (one of: $SCHED_EFFORTS)"
    effort=""
  fi
  pmode="$(sched_field "$f" permission-mode)"
  if [ -n "$pmode" ]; then
    if canon="$(sched_perm_canon "$pmode")"; then
      [ "$canon" = "$pmode" ] || log "schedule $(basename "$f"): permission-mode \"$pmode\" -> $canon"
      pmode="$canon"
    else
      log "schedule $(basename "$f"): ignoring odd permission-mode: \"$pmode\" (one of: $SCHED_PERM_MODES)"
      pmode=""
    fi
  fi

  wd_off=""; mon_off=""
  sched_off "$f" watchdog && wd_off=1
  sched_off "$f" monitor && mon_off=1

  slug="$(sched_slug "$f")"
  parent="$(sched_parent "$f")"
  depth=0
  [ -n "$parent" ] && depth=$(( $(tree_depth "$parent") + 1 ))
  wname="$(tree_wname "$slug" "$depth")"
  warn="$(sched_slug_warn "$f")"
  [ -n "$warn" ] && log "schedule $(basename "$f"): $warn"
  warn="$(sched_placeholder_warn "$f")"
  [ -n "$warn" ] && log "schedule $(basename "$f"): $warn"

  # Compose what gets pasted. A plan leads with its template (the contracts
  # live there); a work item is followed by the checkpoint footer so every
  # scheduled window is resumable by construction.
  #
  # AND EVERY BODY LEADS WITH ITS OWN IDENTITY. The slug is derived out here
  # and used out here -- for the window name, the handover path and the
  # `handover.sh done` in the footer -- so the one thing the worker must not
  # have to guess is what this lane is called. Rendering it into the paste is
  # what makes the brief and the tooling incapable of disagreeing; before this,
  # a brief that named its own lane silently won and wrote a second handover.
  bodyf="$STATE_DIR/sched-body.$$"
  sched_compose "$f" "$slug" "$wname" "$parent" > "$bodyf"

  # WHERE IT LANDS. A child goes after the LAST window of its parent's subtree,
  # which keeps a family contiguous in tmux's flat list as siblings accumulate;
  # anything else goes right after its `window:` target as before. Resolve the
  # INDEX either way -- matching -t by name errors on duplicates, and this
  # session's indices are sparse (0,1,7,8,9 today), so never assume contiguity.
  local -a targs=()
  if [ -n "$parent" ]; then
    idx="$(subtree_last_index "$parent")"
    [ -n "$idx" ] && targs=(-a -t "$MUX_TMUX:$idx")
  fi
  if [ ${#targs[@]} -eq 0 ] && [ -n "$win" ]; then
    idx="$(tmux list-windows -t "$MUX_TMUX" -F '#{window_index} #{window_name}' 2>/dev/null \
           | awk -v w="$win" '$2==w{print $1; exit}')"
    [ -n "$idx" ] && targs=(-a -t "$MUX_TMUX:$idx")
  fi

  # -t pins the SESSION for the no-window case too: without it a new window
  # lands in whichever session tmux last had current, which on a box running
  # two accounts is a coin toss -- and the wrong side of it starts the work
  # under the wrong credentials.
  [ ${#targs[@]} -eq 0 ] && targs=(-t "$MUX_TMUX:")
  # BOTH IDS. The pane is what gets typed into and sampled; the window id is
  # what the tree is keyed on, because it survives a rename and a reindex while
  # the name and the index do not.
  read -r pane wid < <(tmux new-window -d -P -F '#{pane_id} #{window_id}' \
          "${targs[@]}" -n "$wname" -c "$cwd" \
          "${MUX_TMUX_ENV[@]}" \
          "$HOME/.local/bin/claude" ${model:+--model "$model"} ${effort:+--effort "$effort"} \
            ${pmode:+--permission-mode "$pmode"} 2>/dev/null)
  if [ -z "$pane" ]; then
    sched_mark "$f" error
    log "schedule $(basename "$f"): could not open a tmux window"
    rm -f "$bodyf"; return 1
  fi

  # Wait for a prompt, answering the TRUST DIALOG on the way: trust is per
  # exact path in ~/.claude.json and none of the lane worktrees carry it, so
  # the dialog is the common case here, not an edge.
  ready=""; did_trust=""
  for i in $(seq 1 60); do
    sleep 0.5
    txt="$(tmux capture-pane -p -t "$pane" 2>/dev/null || true)"
    if [ -z "$did_trust" ] && grep -q "trust this folder" <<<"$txt"; then
      did_trust=1
      tmux send-keys -t "$pane" Down 2>/dev/null; sleep 0.4
      tmux send-keys -t "$pane" Enter 2>/dev/null; sleep 1
      continue
    fi
    grep -q '❯' <<<"$txt" && { ready=1; break; }
  done
  if [ -z "$ready" ]; then
    sched_mark "$f" error
    log "schedule $(basename "$f"): claude never reached a prompt in $wname"
    rm -f "$bodyf"; return 1
  fi

  # THE OPT-OUTS, BEFORE THE PASTE: the id exists once the prompt is up, and a
  # session that should be left alone must not be watched through its first
  # turn. Appended exactly as --optout / --monitor-optout do it. A pane no
  # session file names in time is left watched -- today's default, logged, and
  # never an error mark: the window itself is open and fine.
  if [ -n "$wd_off$mon_off" ]; then
    if sid="$(sched_pane_sid "$pane")"; then
      if [ -n "$wd_off" ]; then
        grep -qxF "$sid" "$OPTOUT" 2>/dev/null || printf '%s\n' "$sid" >> "$OPTOUT"
        log "schedule $(basename "$f"): session $sid opted out of the watchdog"
      fi
      if [ -n "$mon_off" ]; then
        grep -qxF "$sid" "$MON_OPTOUT" 2>/dev/null || printf '%s\n' "$sid" >> "$MON_OPTOUT"
        log "schedule $(basename "$f"): session $sid opted out of the monitor"
      fi
    else
      log "schedule $(basename "$f"): could not find the session id for $pane; left watched"
    fi
  fi

  # PASTE, never send-keys: a multi-line body through send-keys submits at
  # every newline. Bracketed paste (-p) hands the TUI one paste event.
  tmux load-buffer -b schedbody "$bodyf" 2>/dev/null
  tmux paste-buffer -d -b schedbody -p -t "$pane" 2>/dev/null
  sleep 1
  tmux send-keys -t "$pane" Enter 2>/dev/null
  rm -f "$bodyf"

  tree_record "$slug" "$parent" "$wid" "$pane" "$f"
  sched_mark "$f" launched
  # WHICH GATE FIRED IS PART OF THE RECORD. "due: the budget reads fresh (4%)"
  # and "due: the session window rolled over at 10:10" are different events,
  # and a launch that cannot be explained afterwards is a launch nobody trusts.
  log "schedule $(basename "$f"): launched $wname (win $wid pane $pane) type=$type slug=$slug${parent:+ parent=$parent}${model:+ model=$model}${effort:+ effort=$effort}${pmode:+ perm=$pmode}${wd_off:+ watchdog=off}${mon_off:+ monitor=off} -- ${why:-due}"
}

# ------------------------------------------------------------- --check
# RESOLVE ONE ENTRY AND PRINT EVERY DERIVED THING, WITHOUT LAUNCHING ANYTHING.
#
# This exists because there was no way to validate an entry before it fired.
# Both of today's were verified by hand-reimplementing the parser -- awk per
# field, the slug's tr, counting body lines after the --- -- and a malformed
# one is skipped in silence and simply never runs. Everything printed here is
# computed by the same functions the executor uses, sched_compose included, so
# what it reports and what happens cannot drift apart.
#
# Exit: 0 the entry is runnable, 1 it can never run, 2 it cannot be judged.
sched_resolve_file() {
  local a="$1"
  [ -f "$a" ] && { printf '%s' "$a"; return 0; }
  [ -f "$SCHEDULES/$a" ] && { printf '%s' "$SCHEDULES/$a"; return 0; }
  [ -f "$SCHEDULES/$a.md" ] && { printf '%s' "$SCHEDULES/$a.md"; return 0; }
  # ...or the SLUG of an entry, which is the name a lane is known by everywhere
  # else, and therefore the one a hand reaches for.
  local f
  for f in "$SCHEDULES"/*.md; do
    [ -f "$f" ] || continue
    case "$f" in */README.md) continue ;; esac
    [ "$(sched_slug "$f")" = "$a" ] && { printf '%s' "$f"; return 0; }
  done
  return 1
}

kv() { printf '  %-14s %s\n' "$1" "$2"; }

sched_check_one() {
  local f="$1" body="${2:-}"
  local type at title win cwd tmpl st slug wname warn now rc idx nlines nbytes rcout=0
  local parent depth after blocked pwarn resolved model effort
  type="$(sched_field "$f" type)"; at="$(sched_field "$f" at)"
  title="$(sched_field "$f" title)"; win="$(sched_field "$f" window)"
  cwd="$(sched_field "$f" cwd)"; tmpl="$(sched_field "$f" template)"
  st="$(sched_field "$f" status)"
  slug="$(sched_slug "$f")"; warn="$(sched_slug_warn "$f")"
  parent="$(sched_parent "$f")"; depth=0
  [ -n "$parent" ] && depth=$(( $(tree_depth "$parent") + 1 ))
  wname="$(tree_wname "$slug" "$depth")"
  now="$(date +%s)"

  echo "$(basename "$f")"
  kv type "${type:-(missing)}"
  kv at "${at:-(missing)}"
  kv title "${title:-(none)}"
  model="$(sched_field "$f" model)"
  kv model "${model:-(account default from settings.json)}"
  effort="$(sched_field "$f" effort)"
  if [ -z "$effort" ]; then
    kv effort "(account default -- no --effort flag is passed)"
  elif sched_effort_ok "$effort"; then
    kv effort "$effort   (claude --effort $effort)"
  else
    kv effort "$effort   -- not one of: $SCHED_EFFORTS; it is DROPPED and no flag is passed"
  fi
  pmode="$(sched_field "$f" permission-mode)"
  if [ -z "$pmode" ]; then
    kv permission "(the account's own defaultMode -- no --permission-mode flag is passed)"
  elif canon="$(sched_perm_canon "$pmode")"; then
    if [ "$canon" = "$pmode" ]; then kv permission "$pmode   (claude --permission-mode $pmode)"
    else kv permission "$pmode   -> $canon (claude --permission-mode $canon)"; fi
  else
    kv permission "$pmode   -- not one of: $SCHED_PERM_MODES; it is DROPPED and no flag is passed"
  fi
  if sched_off "$f" watchdog; then kv watchdog "opted out at launch"
  else kv watchdog "covered (default)"; fi
  if sched_off "$f" monitor; then kv monitor "opted out at launch"
  else kv monitor "covered (default)"; fi
  if [ -n "$(sched_field "$f" slug)" ]; then kv slug "$slug   (pinned by slug:)"
  elif [ -n "$title" ]; then kv slug "$slug   (derived from title: \"$title\")"
  else kv slug "$slug   (derived from the filename)"; fi
  kv "window name" "$wname"
  if [ -n "$parent" ]; then
    kv parent "$parent   (depth $depth -- this window is drawn under it)"
  else
    kv parent "(none -- a root window)"
  fi
  if [ -n "$cwd" ] && [ -d "$cwd" ]; then kv cwd "$cwd"
  else kv cwd "${cwd:-(missing)}   -- NOT A DIRECTORY"; rcout=1; fi
  if [ -n "$tmpl" ]; then
    if [ -f "$SCHEDULES/templates/$tmpl.md" ]; then kv template "$tmpl   ($SCHEDULES/templates/$tmpl.md)"
    else kv template "$tmpl   -- NOT IN templates/"; rcout=1; fi
    [ "$type" = plan ] || kv "" "(a template is only prepended for type: plan)"
  fi
  kv status "${st:-(missing)}"
  after="$(sched_field "$f" after)"
  blocked=""
  if [ -n "$after" ]; then
    sched_after_ok "$after" "$slug"; rc=$?
    [ "$rc" = 1 ] && blocked=1
    [ "$rc" = 2 ] && rcout=1
    kv after "$SCHED_WHY_TXT"
    # THE PER-LANE BREAKDOWN, only for a list: the verdict names the first lane
    # still holding, which is the one to act on, but "why is this still
    # blocked" is a question about all of them.
    local -a adeps=(); local d r drc
    while IFS= read -r d; do [ -n "$d" ] && adeps+=("$d"); done < <(sched_after_deps "$after")
    if [ "${#adeps[@]}" -gt 1 ] && [ "$rc" != 2 ]; then
      for d in "${adeps[@]}"; do
        r="$(sched_dep_state "$d")"; drc=$?
        if [ "$drc" = 0 ]; then kv "" "  $d: finished -- $r"
        else kv "" "  $d: HOLDING -- $r"; fi
      done
    fi
  fi
  if [ -f "$HANDOVERS/STATUS-$slug.md" ]; then
    kv handover "$HANDOVERS/STATUS-$slug.md   (open, $(date -r "$HANDOVERS/STATUS-$slug.md" '+%b %d %H:%M'))"
  elif [ -f "$HANDOVERS/done/STATUS-$slug.md" ]; then
    kv handover "$HANDOVERS/STATUS-$slug.md   (already done)"
  else
    kv handover "$HANDOVERS/STATUS-$slug.md   (not written yet)"
  fi
  kv "finish with" "handover.sh done $slug"

  # WHERE THE WINDOW LANDS, resolved against the live session exactly as the
  # launcher resolves it -- by INDEX, because -t by name errors on duplicates
  # and this session's indices are sparse.
  if ! tmux has-session -t "=$MUX_TMUX" 2>/dev/null; then
    kv "insert after" "(session '$MUX_TMUX' is not running -- the launch would WAIT for muxtopus)"
  elif [ -n "$parent" ] && [ -n "$(subtree_last_index "$parent")" ]; then
    kv "insert after" "$MUX_TMUX:$(subtree_last_index "$parent") -- the last window of $parent's subtree"
  elif [ -n "$win" ]; then
    idx="$(tmux list-windows -t "$MUX_TMUX" -F '#{window_index} #{window_name}' 2>/dev/null \
           | awk -v w="$win" '$2==w{print $1; exit}')"
    if [ -n "$idx" ]; then kv "insert after" "$win = $MUX_TMUX:$idx"
    else kv "insert after" "$win -- NO SUCH WINDOW, so it lands at the end"; fi
  else
    kv "insert after" "(no window: -- lands at the end of $MUX_TMUX)"
  fi

  nlines="$(sched_body "$f" | grep -c '' 2>/dev/null)"
  nbytes="$(sched_compose "$f" "$slug" "$wname" "$parent" | wc -c)"
  local parts="identity header"
  [ "$type" = plan ] && [ -n "$tmpl" ] && [ -f "$SCHEDULES/templates/$tmpl.md" ] && parts="$parts + template"
  parts="$parts + body"
  [ "$type" = work ] && parts="$parts + handover footer"
  kv body "${nlines:-0} lines; ${nbytes} bytes pasted in all ($parts)"
  if [ "$type" = work ] && [ -z "$(sched_body "$f")" ]; then
    kv "" "-- EMPTY BODY: a work item with nothing to paste is skipped"; rcout=1
  fi
  case "$type" in plan|work) ;; *) kv "" "-- type must be plan or work"; rcout=1 ;; esac

  [ -n "$warn" ] && printf '  %-14s %s\n' WARNING "$warn"
  pwarn="$(sched_placeholder_warn "$f")"
  [ -n "$pwarn" ] && printf '  %-14s %s\n' WARNING "$pwarn"
  resolved="$(sched_placeholders "$f" | paste -sd' ' -)"
  [ -n "$resolved" ] && kv placeholders "$resolved"

  sched_due "$at" "$now"; rc=$?
  case "$rc" in
    0) kv verdict "DUE NOW -- $SCHED_WHY_TXT" ;;
    1) kv verdict "not yet -- $SCHED_WHY_TXT" ;;
    2) kv verdict "$SCHED_WHY_TXT"; [ "$rcout" = 0 ] && rcout=2 ;;
  esac
  if [ -n "$blocked" ]; then
    kv "" "HELD by after: whatever the clock says above."
  fi
  if [ "$st" != pending ]; then
    kv "" "(status is '${st:-}' -- only a pending entry is ever looked at)"
  fi
  if [ "$rcout" = 1 ]; then
    kv "" "THIS ENTRY CAN NEVER RUN as written."
  fi
  if [ -n "$body" ]; then
    echo
    echo "--- what would be pasted -------------------------------------------"
    sched_compose "$f" "$slug" "$wname" "$parent"
    echo "--------------------------------------------------------------------"
  fi
  return "$rcout"
}

sched_check() {
  local a="${1:-}" body="${2:-}" f rc=0 one
  if [ -n "$a" ]; then
    f="$(sched_resolve_file "$a")" || {
      echo "no schedule entry matching '$a' in $SCHEDULES" >&2; return 2; }
    sched_check_one "$f" "$body"; return $?
  fi
  for f in "$SCHEDULES"/*.md; do
    [ -f "$f" ] || continue
    case "$f" in */README.md) continue ;; esac
    sched_check_one "$f" ""; one=$?
    [ "$one" -gt "$rc" ] && rc="$one"
    echo
  done
  return "$rc"
}

# One pass over the folder. Gated on the same master switch as the restart
# prompt -- opening a window spends tokens exactly the way re-prompting does --
# and a dry run reports without acting, like everywhere else in this file.
#
# EVERY PENDING ENTRY LEAVES A VERDICT behind, whether or not it ran. The three
# reasons an entry used to do nothing -- unparseable, undue, or waiting on a
# usage figure that never arrived -- were indistinguishable from outside, and
# the third one never resolved. Now each writes its sentence to SCHED_WHY, the
# dashboard renders it, and the log takes the changes.
check_schedules() {
  [ -f "$ENABLED" ] || return 0
  [ "$DRY" = 1 ] && return 0
  [ -d "$SCHEDULES" ] || return 0
  local f now st type at cwd rc probe=0 after dep_ok
  now="$(date +%s)"
  : > "$SCHED_WHY.tmp"
  for f in "$SCHEDULES"/*.md; do
    [ -f "$f" ] || continue
    case "$f" in */README.md) continue ;; esac
    st="$(sched_field "$f" status)"
    [ "$st" = pending ] || continue
    type="$(sched_field "$f" type)"
    at="$(sched_field "$f" at)"
    cwd="$(sched_field "$f" cwd)"
    case "$type" in
      plan|work) ;;
      *) sched_note "$f" stalled "STALLED: type must be plan or work, not \"${type:-}\""; continue ;;
    esac
    if [ -z "$cwd" ] || [ ! -d "$cwd" ]; then
      sched_note "$f" stalled "STALLED: cwd \"${cwd:-}\" is not a directory"; continue
    fi
    if [ "$type" = work ] && [ -z "$(sched_body "$f")" ]; then
      sched_note "$f" stalled "STALLED: a work item with an empty prompt body has nothing to paste"; continue
    fi

    # THE DEPENDENCY IS ASKED FIRST. An entry held behind another lane is not
    # "not yet due" -- the clock may well have passed -- and calling it due
    # would be a lie the log then repeats.
    after="$(sched_field "$f" after)"
    dep_ok=""
    if [ -n "$after" ]; then
      sched_after_ok "$after" "$(sched_slug "$f")"; rc=$?
      case "$rc" in
        2) sched_note "$f" stalled "$SCHED_WHY_TXT"; continue ;;
        1) sched_note "$f" blocked "$SCHED_WHY_TXT"; continue ;;
      esac
      dep_ok="$SCHED_WHY_TXT"
    fi

    sched_due "$at" "$now"; rc=$?
    case "$rc" in
      2) sched_note "$f" stalled "$SCHED_WHY_TXT"
         [ "$SCHED_WANT_PROBE" = 1 ] && probe=1
         continue ;;
      1) sched_note "$f" waiting "$SCHED_WHY_TXT"; continue ;;
    esac
    sched_note "$f" due "$SCHED_WHY_TXT${dep_ok:+; $dep_ok}"
    launch_schedule "$f" "$SCHED_WHY_TXT${dep_ok:+; $dep_ok}"
  done
  mv "$SCHED_WHY.tmp" "$SCHED_WHY" 2>/dev/null
  [ "$probe" = 1 ] && sched_request_probe
  return 0
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

# One line of proof that this is running, and an hourly one in the log.
heartbeat() {
  local sessions="${1:-0}" now pending=0 last=0
  now="$(date +%s)"
  pending="$(awk -F'\t' '$2=="waiting"||$2=="blocked"||$2=="stalled"{n++} END{print n+0}' \
             "$SCHED_WHY" 2>/dev/null)"
  printf '%s\t%s\t%s\t%s\n' "$now" "${sessions:-0}" "${pending:-0}" "$INTERVAL" > "$HEARTBEAT"
  [ "${HEARTBEAT_LOG_MIN:-0}" -gt 0 ] 2>/dev/null || return 0
  [ -f "$HEARTBEAT.log" ] && read -r last < "$HEARTBEAT.log" 2>/dev/null
  if [ $(( now - ${last:-0} )) -ge $(( HEARTBEAT_LOG_MIN * 60 )) ]; then
    printf '%s\n' "$now" > "$HEARTBEAT.log"
    log "alive: ${sessions:-0} session(s), ${pending:-0} pending schedule(s), polling every ${INTERVAL}s"
  fi
  return 0
}

pass() {
  local enabled=0; [ -f "$ENABLED" ] && enabled=1
  local msg; msg="$(head -1 "$MSGFILE" 2>/dev/null)"; msg="${msg:-$DEFAULT_MSG}"
  local now; now="$(date +%s)"
  local tmp="$STATUS.tmp"; : > "$tmp"

  local f pid sid pane paneid ver st kind cwd tr ctx name text reset epoch state acted
  local spent rd resumed model optout idle jobid cwd turn_at wound moptout
  local prev lane stranded
  # Rebuilt lazily, once per pass at most, by the stranded test below.
  SCHED_NAMED=""
  # Read once per pass, not once per session: every session is judged against
  # the same account-wide figures.
  local spct wpct rkey
  spct="$(usage_val session_pct)"; wpct="$(usage_val week_pct)"
  rkey="$(usage_val session_reset_at)"
  for f in "$MUX_CONFIG_DIR"/sessions/*.json; do
    [ -f "$f" ] || continue
    pid="$(jq -r '.pid // empty' "$f" 2>/dev/null)"; [ -n "$pid" ] || continue
    kill -0 "$pid" 2>/dev/null || continue          # stale record, process gone
    sid="$(jq -r '.sessionId // empty' "$f")"
    cwd="$(jq -r '.cwd // empty' "$f")"
    pane="$(jq -r '.tmux // empty' "$f")"
    ver="$(jq -r '.version // "?"' "$f")"
    st="$(jq -r '.status // "?"' "$f")"
    kind="$(jq -r '.kind // "?"' "$f")"
    [ -n "$sid" ] || continue
    # claude-usage.sh's throwaway probe lives in its own tmux session. It is a
    # real claude process, so it would otherwise be listed and -- worse -- be
    # eligible for a restart prompt, turning a read-only measurement into a
    # session that spends tokens.
    case "$pane" in cc-usage:*|cc-usage-*:*) continue ;; esac

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
    if [ -n "${tr:-}" ] && [ -f "${tr:-}" ]; then
      turn_at="$(last_turn_epoch "$tr")"
      [ -n "$turn_at" ] && idle=$(( now - turn_at ))
    fi
    resumed="$(last_resumed "$sid")"
    optout=0; grep -qxF "$sid" "$OPTOUT" 2>/dev/null && optout=1
    moptout=0; grep -qxF "$sid" "$MON_OPTOUT" 2>/dev/null && moptout=1

    name="-"; text=""; jobid=""
    if [ -n "$paneid" ]; then
      name="$(tmux display-message -p -t "$paneid" '#{window_name}' 2>/dev/null || echo -)"
      text="$(tmux capture-pane -p -t "$paneid" 2>/dev/null || true)"
    elif [ "$kind" = bg ]; then
      # A background job has no terminal at all: no pane to read a limit banner
      # from and none to type into, so it can never be restarted from here. It
      # does carry a descriptive name and a job id, which are the two things
      # that make it findable -- `claude attach <jobid>` is how you reach it.
      name="$(jq -r '.name // "(background)"' "$f")"
      [ ${#name} -gt 28 ] && name="${name:0:27}…"
      jobid="$(jq -r '.jobId // empty' "$f")"
    fi

    state="idle"; reset="-"; epoch=""
    # "esc to interrupt" is the TUI's own marker for a turn in flight. Never
    # type into a window that is working -- the keystrokes would land in
    # whatever prompt it is composing.
    if grep -q "esc to interrupt" <<<"$text"; then
      state="working"
    elif grep -q "hit your session limit" <<<"$text"; then
      # THE MINUTES ARE OPTIONAL. A limit that resets on the hour prints
      # "resets 7pm" with no ":00", and requiring H:MM here meant the reset
      # never parsed, the state never left "limited", and every window that hit
      # an on-the-hour limit sat parked for hours -- while off-hour ones
      # ("resets 12:40pm") resumed correctly, which is what hid it. That is the
      # exact failure this whole file exists to prevent.
      reset="$(grep -oiE 'resets [0-9]{1,2}(:[0-9]{2})? ?[ap]m' <<<"$text" | tail -1 | awk '{print $2 $3}')"
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

    wound="$(last_wound "$sid")"
    wind_down "$sid" "$name" "$ctx" "$state" "$optout" "$spct" "$wpct" "$rkey" "$now"

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

    # STRANDED: NOTHING IS EVER GOING TO TOUCH THIS WINDOW.
    #
    # `idle` is a fact about the last turn; it is the same word for a lane that
    # finished ten minutes ago and for one that stopped mid-phase three days
    # ago with its handover half-written. MEASURED this week: four lanes sat at
    # `idle 3d` with open handovers, no schedule entry naming any of them, and
    # nothing anywhere said so -- the dashboard's most important sentence was
    # one it could not say.
    #
    # All five conditions, because each one removes a lane that IS accounted
    # for: a ➥ name (it is a scheduled lane, not a window someone is sitting
    # in), idle (not working), idle for long enough, an OPEN handover (there is
    # unfinished work; a done handover means the lane finished), and no pending
    # entry naming it -- its slug, its resume entry, or an `after:` waiting on
    # it -- because such an entry IS the thing that will touch it.
    #
    # IT IS A FACT SHOWN TO A HUMAN, NOT A TRIGGER. It deliberately cannot
    # reach the due/prompt path: it is only ever derived FROM idle, and the
    # restart above only ever acts on `due`. Automatic resume is a separate,
    # opt-in decision that is NOT being built -- an unrequested turn is a turn,
    # and this week showed what four of them cost.
    prev="$(awk -F'\t' -v s="$sid" '$1==s{v=$6} END{print v}' "$STATUS" 2>/dev/null)"
    stranded=""; lane=""
    if [ "$state" = idle ] && [ "${STRANDED_MIN:-0}" -gt 0 ] 2>/dev/null \
       && [ "$idle" -ge $(( ${STRANDED_MIN:-0} * 60 )) ] 2>/dev/null; then
      case "$name" in
        ➥*) lane="$(lane_slug_of "$name")"
            if [ -n "$lane" ] && [ -f "$HANDOVERS/STATUS-$lane.md" ] \
               && [ ! -f "$HANDOVERS/done/STATUS-$lane.md" ] \
               && ! sched_names_slug "$lane"; then
              stranded=1
            fi ;;
      esac
    fi
    if [ -n "$stranded" ]; then
      state=stranded
      [ "$prev" = stranded ] || \
        log "stranded: $name idle $(dur_hm "$idle") with an open handover ($HANDOVERS/STATUS-$lane.md) and no pending schedule entry naming it"
    elif [ "$prev" = stranded ]; then
      log "no longer stranded: $name is now $state"
    fi

    # PID IS THE LAST COLUMN, and it is there for the dashboard rather than for
    # this daemon. A closed window's row is correct here only until the next
    # pass, so a session that ended a second after one lingered on screen for
    # most of the interval. Publishing the pid lets a reader check liveness
    # itself, against a /proc walk it is doing anyway, and drop the row on its
    # own frame. Appended, so an older reader keeps parsing the row it knows.
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$sid" "$name" "$paneid" "$ver" "$ctx" "$state" "$reset" "$acted" \
      "$resumed" "$spent" "$rd" "$optout" "$model" "$idle" "$jobid" \
      "${cwd:--}" "${wound:--}" "$moptout" "$pid" >> "$tmp"
  done

  mv "$tmp" "$STATUS"
  sweep_repos
  tree_adopt
  tree_reparent
  check_schedules
  heartbeat "$(grep -c '' "$STATUS" 2>/dev/null)"
  # Keep the limit figures warm on their own hourly clock. --ensure is a no-op
  # when the cache is young, so this costs nothing between the hours, and it is
  # also what catches a limit resetting EARLY: nobody is watching the dashboard
  # at 4am, and the good surprise is worth a notification.
  # NOT FOR AN ACCOUNT THAT HAS NOT LOGGED IN. The probe starts a real claude
  # process; with no credentials it sits on the login screen until the timeout
  # kills it, so an unattended second profile would spawn a doomed ~450 MB
  # session every hour forever. The credentials file is the marker because it is
  # what a login writes -- after-update.sh checks the same one.
  # NAMED, not inherited. The environment happens to be right here, but the
  # account these figures belong to is not a thing to leave to chance: the
  # numbers decide when a limited window is restarted.
  if [ -x "$SCRIPT_DIR/claude-usage.sh" ] && [ -f "$MUX_CONFIG_DIR/.credentials.json" ]; then
    if [ -n "$MUX_PROFILE" ]; then
      "$SCRIPT_DIR/claude-usage.sh" --profile "$MUX_PROFILE" --ensure "$USAGE_EVERY" >/dev/null 2>&1
    else
      "$SCRIPT_DIR/claude-usage.sh" --ensure "$USAGE_EVERY" >/dev/null 2>&1
    fi
  fi
  if [ "$DRY" = 1 ]; then
    { printf 'SESSION\tWINDOW\tPANE\tVER\tCONTEXT\tSTATE\tRESET\tACTION\tRESUMED\tSPENT\tCACHED\tOPTOUT\tMODEL\tIDLE\tJOB\tCWD\tWOUND\tMONOPTOUT\tPID\n'
      awk -F'\t' 'BEGIN{OFS="\t"} {$1=substr($1,1,8);
        if ($9!="-" && $9!="") $9=strftime("%m-%d %H:%M",$9); print}' "$STATUS"
    } | column -t -s $'\t'
  fi
  return 0
}

if [ "$MODE" = tree ]; then
  tree_adopt
  tree_reparent
  { printf 'WINDOW\tID\tSTATE\tOPENED\n'; tree_print; } | column -t -s $'\t'
  exit 0
fi

if [ "$MODE" = check ]; then
  sched_check "${CHECK_ARG:-}" "${CHECK_BODY:-}"
  exit $?
fi

if [ "$MODE" = daemon ]; then
  log "watchdog started for $MUX_LABEL (interval ${INTERVAL}s, soft $SOFT_PCT%, hard $HARD_PCT%)"
  # RELOAD BY RE-EXEC. A running daemon is a bash loop holding the values it
  # parsed at start, so a config edit -- or SIGHUP, from --reload or from
  # `systemctl --user reload` -- replaces the process with a fresh read of
  # everything: both config layers and this script itself. A pass in flight
  # completes first, because bash runs a trap between commands, never inside
  # one. The sleep is reaped before the exec so it cannot linger as a zombie
  # under the new process, which would not know it as a child.
  _SLEEP=""
  reload() {
    log "reloading: $1"
    [ -n "$_SLEEP" ] && { kill "$_SLEEP" 2>/dev/null; wait "$_SLEEP" 2>/dev/null; }
    exec "$SELF" "${_ARGV[@]}"
  }
  trap 'reload SIGHUP' HUP
  CONF_SEEN="$STATE_DIR/config.seen"; : > "$CONF_SEEN"
  while :; do
    pass
    # An edit to either file takes effect within one interval, without anyone
    # remembering to restart anything. -nt is a builtin: no fork when quiet.
    if [ "$MUX_CONFIG" -nt "$CONF_SEEN" ] || \
       { [ -n "${MUX_PROFILE_CONF:-}" ] && [ "$MUX_PROFILE_CONF" -nt "$CONF_SEEN" ]; }; then
      reload "config changed"
    fi
    # Sleep in the background and wait on it: a trap cannot interrupt a
    # foreground command, but it does return from `wait` at once.
    sleep "$INTERVAL" & _SLEEP=$!; wait "$_SLEEP"; _SLEEP=""
  done
else
  pass
fi
