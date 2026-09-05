#!/usr/bin/env bash
# claude-usage.sh -- read the usage limits that Claude Code only shows in its
# TUI, cache them, and hand them to anything that asks: the dashboard, a shell,
# or a Claude session reasoning about its own budget.
#
#   claude-usage.sh --refresh          scrape now (spawns a throwaway session)
#   claude-usage.sh --ensure 15        scrape only if the cache is older than 15m
#   claude-usage.sh                    print the three lines from cache
#   claude-usage.sh --brief            one line, for a prompt or a status bar
#   claude-usage.sh --json             everything, machine-readable
#   claude-usage.sh --raw              the captured pane, for tuning the parser
#
#   claude-usage.sh --session-pct      42          (bare values, for scripts)
#   claude-usage.sh --session-reset    18:40
#   claude-usage.sh --week-pct         61
#   claude-usage.sh --week-reset       Sep 08, 09:00
#   claude-usage.sh --model-pct        55
#   claude-usage.sh --age              minutes since the last successful scrape
#
# WHY A SCRAPE. There is no other route. `claude` has no usage subcommand (the
# full list was checked), no JSON output and no file holding live limit state --
# ~/.claude/stats-cache.json is historical daily totals and goes stale. /usage
# is a TUI command, so the only way to read it is to run a session and look at
# the pane. That is brittle by construction, which is why a failed parse says so
# instead of leaving yesterday's numbers on screen dressed as today's.
#
# WHAT IT COSTS. A throwaway session is started, sent /usage, captured and
# killed. No turn is taken, so no completion tokens; the process lives ~15s and
# is gone. It is never left resident, both to keep ~450 MB off the machine and
# so the watchdog can never mistake it for work worth restarting.
set -uo pipefail

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/claude-watchdog"
CACHE="$STATE_DIR/usage.tsv"
RAW="$STATE_DIR/usage.raw"
# Every reading is appended here, so "when did I ask and what did it say" has an
# answer after the fact -- the cache only ever holds the latest.
LOG="$STATE_DIR/usage.log"
# Touched when a limit resets EARLY; the dashboard shows a flourish and clears it.
HOORAY="$STATE_DIR/usage.hooray"
PROBE_SESSION="cc-usage"          # the watchdog skips this tmux session by name
CLAUDE="$HOME/.local/bin/claude"
mkdir -p "$STATE_DIR"

# Which model line to report. Default comes from settings.json ("fable[1m]" ->
# "fable") so the row is labelled with whatever this machine actually runs.
MODEL_KEY="${CLAUDE_USAGE_MODEL:-$(jq -r '.model // "opus"' "$HOME/.claude/settings.json" 2>/dev/null | sed 's/\[.*//')}"
MODEL_KEY="${MODEL_KEY:-opus}"

get() { awk -F'\t' -v k="$1" '$1==k{print $2; f=1} END{if(!f) print ""}' "$CACHE" 2>/dev/null; }

# "10:39pm" -> "22:39". The comma in "Sep 5, 4:59pm" makes date(1) refuse the
# whole string, so it goes before the am/pm is split off. Anything unparseable
# is returned VERBATIM rather than blanked: a stamp we cannot normalise is still
# more use on screen than an empty field.
norm() {
  local s="$1" fmt="$2" out
  [ -n "$s" ] || return 0
  out="$(date -d "$(tr -d ',' <<<"$s" | sed -E 's/([ap]m)/ \1/I')" "+$fmt" 2>/dev/null)"
  printf '%s' "${out:-$s}"
}
to24()   { norm "$1" '%H:%M'; }
todate() { norm "$1" '%b %d, %H:%M'; }

scrape() {
  command -v tmux >/dev/null 2>&1 || { echo "tmux not available" >&2; return 1; }
  [ -x "$CLAUDE" ] || { echo "claude not found at $CLAUDE" >&2; return 1; }

  tmux kill-session -t "$PROBE_SESSION" 2>/dev/null
  # $HOME is already a trusted folder here, so the probe starts straight at a
  # prompt. A fresh directory would stop on the trust dialog and hang.
  tmux new-session -d -s "$PROBE_SESSION" -x 200 -y 50 -c "$HOME" \
    "$CLAUDE" 2>/dev/null || { echo "could not start probe session" >&2; return 1; }

  local i txt=""
  for i in $(seq 1 40); do          # up to ~20s for the TUI to be ready
    sleep 0.5
    txt="$(tmux capture-pane -p -t "$PROBE_SESSION" 2>/dev/null || true)"
    grep -q '❯\|Welcome\|/help' <<<"$txt" && break
  done

  tmux send-keys -t "$PROBE_SESSION" "/usage" 2>/dev/null
  sleep 1
  tmux send-keys -t "$PROBE_SESSION" Enter 2>/dev/null

  local seen=""
  for i in $(seq 1 30); do          # up to ~15s for the panel to render
    sleep 0.5
    txt="$(tmux capture-pane -p -S -200 -t "$PROBE_SESSION" 2>/dev/null || true)"
    # Specifically the PANEL heading. A looser test matches the startup banner
    # ("You've used 94% of your session limit"), which is on screen before
    # /usage has rendered anything, so the capture would fire far too early.
    if grep -q 'Current session' <<<"$txt"; then
      seen=1
      # one more beat so a half-drawn panel is not what gets parsed
      sleep 1.5
      txt="$(tmux capture-pane -p -S -200 -t "$PROBE_SESSION" 2>/dev/null || true)"
      break
    fi
  done

  printf '%s\n' "$txt" > "$RAW"
  tmux kill-session -t "$PROBE_SESSION" 2>/dev/null
  [ -n "$seen" ] || { echo "no usage panel appeared (see $RAW)" >&2; return 1; }
  parse
}

# The panel puts each bucket over THREE lines -- a heading, a bar ending in
# "NN% used", then "Resets ...". So this is a small state machine keyed on the
# headings rather than a per-line grep; the first version looked for the
# percentage on the heading line, where it never is.
#
#     Current session
#     ██████████  94% used
#     Resets 10:39pm (Europe/Bucharest)
#     Current week (all models)      <- must be tested BEFORE the generic
#     Current week (Fable)              "Current week (" that follows it
#
# Colour codes are stripped first: capture-pane -p emits them.
parse() {
  local plain kv sp sr wp wr mp mn
  plain="$(sed -e 's/\x1b\[[0-9;]*[A-Za-z]//g' "$RAW")"

  kv="$(awk '
    /Current session/             { mode="session"; next }
    /Current week \(all models\)/ { mode="week";    next }
    /Current week \(/             { mode="model"
                                    m=$0; sub(/.*\(/,"",m); sub(/\).*/,"",m)
                                    print "model_name\t" m; next }
    mode != "" && match($0, /[0-9]+(\.[0-9]+)?% used/) {
      s=substr($0, RSTART, RLENGTH); sub(/% used/,"",s)
      print mode "_pct\t" s; next }
    mode != "" && match($0, /Resets[^(]*/) {
      s=substr($0, RSTART, RLENGTH); sub(/^Resets[ \t]*/,"",s)
      gsub(/[ \t]+$/,"",s)
      print mode "_reset\t" s; mode=""; next }
  ' <<<"$plain")"

  fld() { awk -F'\t' -v k="$1" '$1==k{print $2; exit}' <<<"$kv"; }
  sp="$(fld session_pct)";  sr="$(fld session_reset)"
  wp="$(fld week_pct)";     wr="$(fld week_reset)"
  mp="$(fld model_pct)";    mn="$(fld model_name)"

  # Read the PREVIOUS reading before overwriting it: an early reset is only
  # visible as a change between two readings.
  local prev_pct prev_at prev_due now
  prev_pct="$(get session_pct)"; prev_due="$(get session_reset_at)"
  now="$(date +%s)"

  local due=""
  [ -n "${sr:-}" ] && due="$(date -d "$(tr -d ',' <<<"$sr" | sed -E 's/([ap]m)/ \1/I')" +%s 2>/dev/null)"
  # A reset time that has already passed names TOMORROW -- the same rule the
  # watchdog uses on the limit banner, and for the same reason.
  [ -n "$due" ] && [ "$due" -lt $(( now - 21600 )) ] && due=$(( due + 86400 ))

  {
    printf 'at\t%s\n' "$now"
    printf 'session_pct\t%s\n'      "${sp:-}"
    printf 'session_reset\t%s\n'    "$(to24 "${sr:-}")"
    printf 'session_reset_at\t%s\n' "${due:-}"
    printf 'week_pct\t%s\n'         "${wp:-}"
    printf 'week_reset\t%s\n'       "$(todate "${wr:-}")"
    printf 'model\t%s\n'            "${mn:-$MODEL_KEY}"
    printf 'model_pct\t%s\n'        "${mp:-}"
  } > "$CACHE.tmp" && mv "$CACHE.tmp" "$CACHE"

  check_early_reset "${prev_pct:-}" "${prev_due:-}" "${sp:-}" "$now"

  [ -n "${sp:-}${wp:-}${mp:-}" ] || {
    echo "usage panel captured but nothing parsed -- inspect $RAW" >&2; return 1; }

  printf '%s\tsession=%s%%\tresets=%s\tweek=%s%%\tresets=%s\t%s=%s%%\n' \
    "$(date '+%Y-%m-%d %H:%M:%S')" "${sp:-?}" "$(to24 "${sr:-}")" \
    "${wp:-?}" "$(todate "${wr:-}")" "${mn:-$MODEL_KEY}" "${mp:-?}" >> "$LOG"
  return 0
}

# A budget that empties BEFORE the clock said it would. Worth noticing because
# it is the one surprise in this system that is good news, and because it means
# work can start again now rather than at the hour printed on screen.
#
# Deliberately narrow: it fires only on a real collapse (was at least half
# spent, now essentially empty) that happens with real time left on the stated
# reset. A gentle drift downward is not a reset, and neither is a reading taken
# a minute after the deadline it was waiting for.
check_early_reset() {
  local prev="$1" due="$2" now_pct="$3" now="$4"
  [ -n "$prev" ] && [ -n "$due" ] && [ -n "$now_pct" ] || return 0
  case "$prev$now_pct$due" in *[!0-9.]*) return 0 ;; esac
  [ "${prev%%.*}" -ge 50 ] || return 0
  [ "${now_pct%%.*}" -le 5 ] || return 0
  [ "$now" -lt $(( due - 300 )) ] || return 0

  local mins=$(( (due - now) / 60 ))
  : > "$HOORAY"                      # the dashboard's party hat, cleared on read
  printf '%s\tEARLY RESET: session %s%% -> %s%% with %sm still on the clock\n' \
    "$(date '+%Y-%m-%d %H:%M:%S')" "$prev" "$now_pct" "$mins" >> "$LOG"
  "$(dirname "$(readlink -f "$0")")/claude-notify.sh" \
    "Limit reset early" \
    "Session budget went $prev% -> $now_pct% with ${mins}m still on the clock. You can start again now." \
    >/dev/null 2>&1 &
}

age_minutes() {
  local at; at="$(get at)"
  [ -n "$at" ] || { printf '%s' "-1"; return 0; }
  printf '%s' $(( ( $(date +%s) - at ) / 60 ))
}

cap() { printf '%s' "$(tr '[:lower:]' '[:upper:]' <<<"${1:0:1}")${1:1}"; }

show_lines() {
  local a; a="$(age_minutes)"
  if [ "$a" = "-1" ]; then
    echo "Session - no data. Run: claude-usage.sh --refresh"
    echo "Week    - no data."
    echo "$(cap "$MODEL_KEY") - no data."
    return 1
  fi
  printf 'Session - %s%% Used. Resets %s\n' "$(get session_pct)" "$(get session_reset)"
  printf 'Week - %s%% Used. Reset %s\n'     "$(get week_pct)"    "$(get week_reset)"
  printf '%s - %s%% Used. (Last refresh: %s)\n' \
    "$(cap "$(get model)")" "$(get model_pct)" "$(date -d "@$(get at)" +%H:%M)"
}

case "${1:-}" in
  --refresh)       scrape ;;
  --ensure)        a="$(age_minutes)"
                   if [ "$a" = "-1" ] || [ "$a" -ge "${2:-15}" ]; then scrape >/dev/null 2>&1; fi
                   show_lines ;;
  --brief)         printf 'session %s%% (resets %s) · week %s%% (resets %s) · %s %s%% · read %sm ago\n' \
                     "$(get session_pct)" "$(get session_reset)" \
                     "$(get week_pct)" "$(get week_reset)" \
                     "$(get model)" "$(get model_pct)" "$(age_minutes)" ;;
  --json)          jq -n --arg sp "$(get session_pct)" --arg sr "$(get session_reset)" \
                        --arg wp "$(get week_pct)"    --arg wr "$(get week_reset)" \
                        --arg m  "$(get model)"       --arg mp "$(get model_pct)" \
                        --arg age "$(age_minutes)" \
                     '{session:{pct:$sp,resets:$sr},week:{pct:$wp,resets:$wr},
                       model:{name:$m,pct:$mp},age_minutes:($age|tonumber)}' ;;
  --raw)           cat "$RAW" 2>/dev/null ;;
  --session-pct)   get session_pct ;;
  --session-reset) get session_reset ;;
  --week-pct)      get week_pct ;;
  --week-reset)    get week_reset ;;
  --model-pct)     get model_pct ;;
  --model)         get model ;;
  --age)           age_minutes; echo ;;
  --parse)         parse ;;          # re-parse the last capture after a tweak
  -h|--help)       sed -n '2,28p' "$0" ;;
  "")              show_lines ;;
  *) echo "unknown option: $1" >&2; exit 2 ;;
esac
