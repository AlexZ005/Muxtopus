#!/usr/bin/env bash
# mux-alerts: the conditions where every lane silently stops -- a session lost,
# an account logged out, a budget at its limit (and, off by default, past a
# band), stalled and stranded -- each told ONCE, "cleared" once, behind its own
# switch, and under /mute recorded rather than sent.
# The sandbox of tests/notify_sandbox.sh: -L mxnotify, a fake claude, the fake
# Bot API. Nothing here reaches a real pane, account, bot or config.
#   bash tests/test_notify_alerts.sh
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
W="$REPO/claude-watchdog.sh"
HO="$HOME/.code/handovers"; SC="$HOME/.code/schedules"
ST="$XDG_STATE_HOME/claude-watchdog"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"
chmod 600 "$CLAUDE_NOTIFY_CONF"

setkey() { sed -i "/^$1=/d" "$MUXTOPUS_CONFIG"; printf '%s=%s\n' "$1" "$2" >> "$MUXTOPUS_CONFIG"; }
pass() { "$W" --once >/dev/null 2>&1; }
msgs() { sb_ncalls sendMessage; }
texts() { sb_calls sendMessage | jq -r .text; }
since() { sb_calls sendMessage | tail -n +"$(( $1 + 1 ))" | jq -r .text; }
screen() { printf '%s' "${1:-● done.

────
❯
────
}" > "$HOME/fake-screen"; sleep 0.8; }
# usage.tsv as claude-usage.sh writes it; AGE in seconds.
usage() {  # usage SESSION WEEK MODEL [AGE]
  { printf 'at\t%s\n' "$(( $(date +%s) - ${4:-0} ))"
    printf 'session_pct\t%s\nsession_reset\t18:40\nsession_reset_at\t\n' "$1"
    printf 'week_pct\t%s\nweek_reset\tSep 25, 09:00\n' "$2"
    printf 'model\tFable\nmodel_pct\t%s\naccount\tpersonal\nmodel_reset\tSep 26, 10:00\n' "$3"
  } > "$ST/usage.tsv"
}
: > "$HOME/.claude/.credentials.json"      # logged in; the auth test removes it

screen
tmux new-session -d -s claude -n '➥lane-a' -x 100 -y 40 "cd $HOME && claude"
for i in $(seq 50); do ls "$HOME/.claude/sessions/"*.json >/dev/null 2>&1 && break; sleep 0.1; done
"$W" --on >/dev/null
mkdir -p "$ST"; usage 10 10 10
pass
check "baseline: nothing sent" [ "$(msgs)" = 0 ]

echo "== limits: bands are OFF by default, the limit is ON"
usage 70 10 10; n="$(msgs)"; pass
check "soft band, LIMIT_BANDS off: nothing" [ "$(msgs)" = "$n" ]
usage 100 10 10; pass
check "session at 100%: one message" [ "$(msgs)" = $(( n + 1 )) ]
check "it names the budget" grep -q "limit hit: session budget" <<<"$(since "$n")"
check "and when it resets" grep -q "Resets 18:40" <<<"$(since "$n")"
pass; pass
check "told once" [ "$(msgs)" = $(( n + 1 )) ]
usage 100 10 10 $(( 4 * 3600 )); pass
check "a stale reading neither fires nor clears" [ "$(msgs)" = $(( n + 1 )) ]
usage 3 10 10; pass
check "reset: one \"cleared\"" grep -q "cleared: limit hit: session budget" <<<"$(since "$n")"
check "exactly one" [ "$(msgs)" = $(( n + 2 )) ]

echo "== limits: the model's week, and LIMIT off"
setkey MUXTOPUS_NOTIFY_LIMIT off
usage 3 10 100; n="$(msgs)"; pass
check "LIMIT off: nothing" [ "$(msgs)" = "$n" ]
setkey MUXTOPUS_NOTIFY_LIMIT on; pass
check "switched on while it lasts: told then" grep -q "limit hit: Fable weekly budget" <<<"$(since "$n")"
check "with the model's reset" grep -q "Resets Sep 26, 10:00" <<<"$(since "$n")"
usage 3 10 10; pass

echo "== limits: bands, when switched on"
setkey MUXTOPUS_NOTIFY_LIMIT_BANDS on
usage 70 10 10; n="$(msgs)"; pass
check "soft band told" grep -q "soft band: session budget 70%" <<<"$(since "$n")"
usage 90 10 10; pass
check "hard band told" grep -q "hard band: session budget 90%" <<<"$(since "$n")"
usage 80 10 10; pass
check "a band that only FELL is quiet" [ "$(msgs)" = $(( n + 2 )) ]
usage 10 10 10; pass
check "back under soft: cleared" [ "$(msgs)" = $(( n + 3 )) ]
setkey MUXTOPUS_NOTIFY_LIMIT_BANDS off

echo "== limits: a banner in a pane beats the reading"
n="$(msgs)"
screen "You've hit your weekly limit · resets Sep 25, 9am
❯ "
pass
check "weekly banner: told" grep -q "limit hit: weekly budget (all models)" <<<"$(since "$n")"
check "with the banner's reset" grep -q "Resets Sep 25, 9am" <<<"$(since "$n")"
screen; pass
check "banner gone: cleared" grep -q "cleared: limit hit: weekly budget" <<<"$(since "$n")"

echo "== auth: a pane, the probe, the credentials file"
n="$(msgs)"
screen "● Working on it
  ⎿  API Error: 401 {\"type\":\"error\",\"error\":{\"type\":\"authentication_error\"}}
     · Please run /login
❯ "
pass
check "auth error on screen: logged out" grep -q "personal · logged out" <<<"$(since "$n")"
check "the body names the pane" grep -q "➥lane-a shows: API Error: 401" <<<"$(since "$n")"
pass; pass
check "told once" [ "$(msgs)" = $(( n + 1 )) ]
screen "  the notes say: users see 'Please run /login' when the token lapses
❯ "
pass
check "a QUOTE of the words is not a logout: cleared" grep -q "cleared: logged out" <<<"$(since "$n")"
n="$(msgs)"
printf '%s\t%s\n' "$(date +%s)" "personal is not logged in ($HOME/.claude)" > "$ST/usage.fail"
usage 10 10 10 120; pass
check "probe found the login screen: logged out" grep -q "the /usage probe found the login screen" <<<"$(since "$n")"
rm -f "$ST/usage.fail" "$HOME/.claude/.credentials.json"; pass
check "credentials gone: still ONE alert (same condition)" [ "$(msgs)" = $(( n + 1 )) ]
: > "$HOME/.claude/.credentials.json"; pass
check "logged in again: cleared" [ "$(msgs)" = $(( n + 2 )) ]
setkey MUXTOPUS_NOTIFY_AUTH off
rm -f "$HOME/.claude/.credentials.json"; n="$(msgs)"; pass
check "AUTH off: nothing" [ "$(msgs)" = "$n" ]
: > "$HOME/.claude/.credentials.json"; pass
check "AUTH off: no cleared either" [ "$(msgs)" = "$n" ]
setkey MUXTOPUS_NOTIFY_AUTH on

echo "== session lost: the process dies, the window stays"
tmux new-window -d -t claude: -n '➥lane-b' "cd $HOME && claude; exec sleep 600"
for i in $(seq 50); do [ "$(ls "$HOME/.claude/sessions/"*.json | wc -l)" = 2 ] && break; sleep 0.1; done
pass
pb="$(tmux list-panes -t 'claude:➥lane-b' -F '#{pane_id}')"
check "the new pane is in the ledger" grep -q "^$pb	➥lane-b	0" "$ST/notify/panes.tsv"
pid="$(jq -r --arg p "$pb" 'select(.tmux|endswith("."+$p)) | .pid' "$HOME/.claude/sessions/"*.json)"
kill "$pid"; sleep 0.5
n="$(msgs)"; pass
check "one pass missing: not news yet" [ "$(msgs)" = "$n" ]
pass
check "two passes: session lost" grep -q "session lost: ➥lane-b" <<<"$(since "$n")"
check "it says what the pane runs now" grep -q "now runs sleep" <<<"$(since "$n")"
pass; pass
check "told once" [ "$(msgs)" = $(( n + 1 )) ]
tmux kill-window -t 'claude:➥lane-b'; pass
check "window closed: cleared" grep -q "cleared: session lost: ➥lane-b" <<<"$(since "$n")"
check "and dropped from the ledger" bash -c '! grep -q "^$1	" "$2"' _ "$pb" "$ST/notify/panes.tsv"
setkey MUXTOPUS_NOTIFY_SESSION off
tmux new-window -d -t claude: -n '➥lane-c' "cd $HOME && claude; exec sleep 600"
for i in $(seq 50); do [ "$(ls "$HOME/.claude/sessions/"*.json | wc -l)" = 2 ] && break; sleep 0.1; done
pass
pc="$(tmux list-panes -t 'claude:➥lane-c' -F '#{pane_id}')"
kill "$(jq -r --arg p "$pc" 'select(.tmux|endswith("."+$p)) | .pid' "$HOME/.claude/sessions/"*.json)"; sleep 0.5
n="$(msgs)"; pass; pass; pass
check "SESSION off: nothing" [ "$(msgs)" = "$n" ]
tmux kill-window -t 'claude:➥lane-c'; pass
setkey MUXTOPUS_NOTIFY_SESSION on

echo "== stranded: its own switch, and cleared"
sid="$(jq -r .sessionId "$HOME/.claude/sessions/"*.json | head -1)"
mkdir -p "$HOME/.claude/projects/sb"
printf '{"type":"assistant","timestamp":"%s"}\n' "$(date -u -d '-3 hours' +%Y-%m-%dT%H:%M:%SZ)" > "$HOME/.claude/projects/sb/$sid.jsonl"
printf '# STATUS: lane-a\nhalf way\n' > "$HO/STATUS-lane-a.md"
setkey MUXTOPUS_NOTIFY_STRANDED off
n="$(msgs)"; pass
check "STRANDED off: nothing" [ "$(msgs)" = "$n" ]
setkey MUXTOPUS_NOTIFY_STRANDED on
setkey MUXTOPUS_NOTIFY_TROUBLE off; pass
check "STRANDED on (TROUBLE off): told" grep -q "stranded: ➥lane-a" <<<"$(since "$n")"
rm -f "$HO/STATUS-lane-a.md"; pass
check "stranded ends: cleared" grep -q "cleared: stranded: ➥lane-a" <<<"$(since "$n")"
rm -f "$HOME/.claude/projects/sb/$sid.jsonl"
setkey MUXTOPUS_NOTIFY_TROUBLE on

echo "== /mute: recorded, not sent -- and /unmute is not a flood"
mkdir -p "$XDG_STATE_HOME/muxtopus-notify"
printf '%s\n' "$(( $(date +%s) + 3600 ))" > "$XDG_STATE_HOME/muxtopus-notify/mute"
usage 100 10 10; n="$(msgs)"; pass
check "muted: nothing reaches the API" [ "$(msgs)" = "$n" ]
check "muted: but the key is recorded" grep -q "^limit:session	3" "$ST/notify/sent.tsv"
check "and the log says MUTED" grep -q "MUTED: personal · limit hit" "$ST/notify.log"
rm -f "$XDG_STATE_HOME/muxtopus-notify/mute"; pass; pass
check "unmuted, condition unchanged: still nothing" [ "$(msgs)" = "$n" ]
usage 5 10 10; pass
check "and its recovery is told" grep -q "cleared: limit hit: session budget" <<<"$(since "$n")"

echo "== restart re-sends nothing; unconfigured sends nothing"
usage 100 10 10; pass; n="$(msgs)"; pass; pass
check "no message on quiet passes" [ "$(msgs)" = "$n" ]
mv "$CLAUDE_NOTIFY_CONF" "$CLAUDE_NOTIFY_CONF.off"
rm -f "$HOME/.claude/.credentials.json"; pass
check "unconfigured: nothing reaches the API" [ "$(msgs)" = "$n" ]
mv "$CLAUDE_NOTIFY_CONF.off" "$CLAUDE_NOTIFY_CONF"
sb_done
