#!/usr/bin/env bash
# claude-winddown-hook.sh -- hand a running session one line from the watchdog.
#
# Registered as a PostToolUse hook, so it runs after every tool call. That is
# the ONLY point at which a session that is busy working can be told anything:
# UserPromptSubmit needs a prompt that will not arrive until the work stops,
# and typing into the pane is forbidden while a turn is in flight because the
# keystrokes land in whatever the window is composing.
#
# VERIFIED BY EXPERIMENT, NOT BY THE REFERENCE. The hooks documentation shows
# additionalContext only under UserPromptSubmit and describes PostToolUse as
# carrying a permission decision, which would make this impossible. Measured on
# 2.1.261 with a marker string: a PostToolUse hook printing the
# additionalContext shape below reaches the model mid-turn, which quotes it
# back as "PostToolUse:<Tool> hook additional context: ...". Exit code 2 with
# stderr also reaches it, but that is documented as a BLOCKING ERROR, so this
# uses the quiet path. If a future version breaks it, the tell is that
# wind-downs stop landing while the wound ledger still fills up.
#
# COST. The common case -- nothing to say to anybody -- is a builtin read and a
# glob, with NO fork at all, because this runs after every single tool call.
# jq is reached for only when a directive is actually being delivered.
set -uo pipefail

# Drain stdin with a builtin rather than cat: the payload must be consumed
# whether or not it is needed, and a fork here would be paid on every tool call.
IFS= read -r -d '' payload || true

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/claude-watchdog"
DIR="$STATE/directives"

shopt -s nullglob
pending=("$DIR"/*)
(( ${#pending[@]} )) || exit 0

# Pull session_id out of the payload without spawning jq. The shape is machine
# generated so the pattern is exact; anything that does not come out looking
# like a uuid falls back to a real parse rather than guessing.
sid="${payload#*\"session_id\":\"}"
sid="${sid%%\"*}"
if [ "${#sid}" -ne 36 ] || [ "${sid//[!-]/}" != "----" ]; then
  sid="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)"
fi
[ -n "$sid" ] || exit 0

if [ -f "$STATE/hookdebug" ]; then
  printf '%s\tsid=%s\tpending=%d\n' "$(date '+%F %T')" "$sid" "${#pending[@]}" \
    >> "$STATE/hook.log"
fi

f="$DIR/$sid"
[ -f "$f" ] || exit 0

# EXPIRY. A directive is only collected on a tool call, so a window that goes
# idle holds one indefinitely -- and delivering it tomorrow, on a fresh budget
# and against whatever the user has since asked for, is worse than never
# delivering it: the session has no way to tell a stale order from a live one.
# Past the TTL it is dropped silently, which is also what makes a hand-queued
# wind-down safe to change your mind about.
TTL="${WINDDOWN_TTL:-1800}"
now="$(printf '%(%s)T' -1)"
age=$(( now - $(stat -c %Y "$f" 2>/dev/null || echo "$now") ))
if [ "$age" -gt "$TTL" ]; then
  rm -f "$f"
  exit 0
fi

msg="$(<"$f")"
# Delete FIRST. A directive is a one-shot: if anything below fails, the right
# outcome is a message that was missed once, never one repeated after every
# tool call for the rest of the session.
rm -f "$f"
[ -n "$msg" ] || exit 0

# printf, not a here-string: <<< appends a newline, which jq -Rs then
# faithfully encodes into the injected text.
esc="$(printf '%s' "$msg" | jq -Rs . 2>/dev/null)" || exit 0
printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s}}\n' "$esc"
exit 0
