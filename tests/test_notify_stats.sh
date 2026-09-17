#!/usr/bin/env bash
# /stats: the usage ledger's totals on the phone, and the week/month/all buttons.
#
# Moved here from the insights lane (plan-dashboard-split.md §5) so that one
# lane owns muxtelegram.py; the figures are muxstats', and what is proven is
# that the phone says the same numbers as `muxtopus stats --json` for the
# same period, out of the same ledger, with no collect of its own.
#
#   bash tests/test_notify_stats.sh
. "$(dirname "$0")/notify_sandbox.sh"
sb_init
T="$REPO/muxtelegram.py"; MS="$REPO/muxstats.py"
SH="$XDG_STATE_HOME/muxtopus-notify"
ST="$XDG_STATE_HOME/muxtopus/stats"
printf 'BACKEND=telegram\nTELEGRAM_TOKEN=111:GOOD\nTELEGRAM_CHAT=4242\n' > "$CLAUDE_NOTIFY_CONF"

poll() { python3 "$T" poll; }
texts() { sb_calls sendMessage | jq -r .text; }
last_text() { sb_calls sendMessage | tail -1 | jq -r .text; }
last_edit() { sb_calls editMessageText | tail -1 | jq -r .text; }
UID_N=0
say() {
  UID_N=$(( UID_N + 1 ))
  sb_update "$(jq -cn --arg t "$1" --argjson c "${2:-4242}" --argjson u "$UID_N" \
    '{update_id:$u, message:{message_id:(500+$u), from:{id:$c}, chat:{id:$c, type:"private"}, text:$t}}')"
}
press() {
  UID_N=$(( UID_N + 1 ))
  sb_update "$(jq -cn --arg d "$1" --argjson u "$UID_N" --argjson m "${2:-1001}" \
    '{update_id:$u, callback_query:{id:("q"+($u|tostring)), from:{id:4242}, message:{message_id:$m, chat:{id:4242}, text:"x"}, data:$d}}')"
}
kb_of_last() { sb_calls sendMessage | jq -c 'select(.reply_markup) | .reply_markup | fromjson' | tail -1; }
cb_of() { kb_of_last | jq -r --arg l "$1" '.inline_keyboard[][] | select(.text|test($l)) | .callback_data'; }
cb_said() { sb_calls answerCallbackQuery | tail -1 | jq -r .text; }
menu_commands() { sb_calls setMyCommands | tail -1 | jq -r '.commands' | jq -r '.[].command'; }
# What the CLI says for the same ledger and period. --no-collect, because the
# bot never collects either: a command reads what the watchdog wrote.
cli() { python3 "$MS" --state-dir "$ST" stats --no-collect "--$1" --json --prices "$PRICES"; }

echo "== nothing collected yet: it says so, and does not pretend"
say /stats; poll
check "the reply names the account" grep -q "^personal · stats" <<<"$(last_text)"
check "..and says the ledger is empty" grep -qi "nothing collected yet" <<<"$(last_text)"

# A ledger with rows TODAY, so week, month and all cover the same figures and
# a difference between the phone and the CLI can only be this file's fault.
mkdir -p "$ST"
TODAY="$(date +%F)"
{
  printf 'day\tsession\tproject\tlane\tmodel\tside\trequests\tin\tout\tcache_read\tcache_w5m\tcache_w1h\tthinking\tctx_peak\tctx_sum\tctx_n\ttools\tweb\tturns\tactive_s\tcompactions\tfirst_ts\tlast_ts\thours\ttool_mix\tcoarse\n'
  printf '%s\taaaa0000-0000-4000-8000-000000000001\t~/work/repo-a\tlane-a\tclaude-opus-5\t0\t12\t40000\t9000\t300000\t50000\t0\t3000\t120000\t600000\t12\t7\t1\t9\t1800\t0\t%s\t%s\t10=49000\tRead=4,Edit=3\t0\n' \
    "$TODAY" "$(date +%s)" "$(date +%s)"
  printf '%s\tbbbb0000-0000-4000-8000-000000000002\t~/work/repo-b\tlane-b\tclaude-opus-5\t0\t5\t10000\t2000\t80000\t20000\t0\t500\t60000\t200000\t5\t2\t0\t4\t600\t0\t%s\t%s\t10=12000\tRead=2\t0\n' \
    "$TODAY" "$(date +%s)" "$(date +%s)"
} > "$ST/ledger.tsv"
printf 'backfill\tdone\nlast_collect\t%s\nschema\t1\nsince\t%s\n' "$(date +%s)" "$TODAY" > "$ST/meta"
# The prices file at the path muxstats looks for it beside MUXTOPUS_CONFIG,
# so the bot and the CLI below price the same tokens the same way.
PRICES="$(dirname "$MUXTOPUS_CONFIG")/prices.md"
cp "$REPO/seeds/prices.md" "$PRICES"

echo "== /stats: the phone's figures are the CLI's figures"
say /stats; poll
TXT="$(last_text)"
check "the period is this week" grep -q "this week" <<<"$TXT"
WANT_TOK="$(cli week | jq -r '.tokens.total')"
WANT_SES="$(cli week | jq -r '.sessions.count')"
check "the session count is the ledger's" grep -qF "$WANT_SES session(s)" <<<"$TXT"
check "the token total is the ledger's" bash -c '
  python3 - "$1" "$2" <<EOF
import re, sys
want, text = int(sys.argv[1]), sys.argv[2]
shown = re.search(r"([0-9.]+[MkK]?) tokens", text).group(1)
mul = {"M": 1_000_000, "k": 1000, "K": 1000}.get(shown[-1], 1)
n = float(shown.rstrip("MkK")) * mul
sys.exit(0 if abs(n - want) <= max(1000, want * 0.01) else 1)
EOF' _ "$WANT_TOK" "$TXT"
check "the top projects are named" grep -q "top: repo-a" <<<"$TXT"
check "in/out/cache are on their own line" grep -q "of input from cache" <<<"$TXT"

echo "== the buttons: week · month · all, the one in view marked"
check "three buttons" [ "$(kb_of_last | jq '[.inline_keyboard[][]] | length')" = 3 ]
kb_of_last | jq -r '.inline_keyboard[][].text' | tr '\n' ' ' | grep -q '· week ·' \
  && ok "week is the one marked" || bad "week is the one marked"

echo "== a button switches the period IN PLACE"
CB="$(cb_of 'month')"
check "the month button has a pending id" [ -n "$CB" ]
press "$CB" 1001; poll
E="$(last_edit)"
check "the message was edited, not re-sent" [ "$(sb_ncalls editMessageText)" -ge 1 ]
check "..to this month" grep -q "this month" <<<"$E"
check "..and no extra message was sent" [ "$(texts | grep -c 'stats')" = 2 ]

echo "== the old button is retired by the new one"
press "$CB" 1001; poll
check "pressing it again is refused" grep -qi "expired or already used" <<<"$(cb_said)"

echo "== /stats all, and an argument that is not a period"
say "/stats all"; poll
check "all is honoured" grep -q "· stats · all" <<<"$(last_text)"
say "/stats yesteryear"; poll
check "an unknown period falls back to the week" grep -q "this week" <<<"$(last_text)"

echo "== it is in the bot's menu, and in /help"
rm -f "$SH/commands.sha"; poll
check "setMyCommands lists /stats" grep -qx stats <<<"$(menu_commands)"
say /help; poll
check "/help lists it" grep -q "^/stats" <<<"$(last_text)"

echo "== a command from a wrong chat is still dropped"
N="$(sb_ncalls sendMessage)"
say /stats 999; poll
check "no reply" [ "$(sb_ncalls sendMessage)" = "$N" ]

sb_done
