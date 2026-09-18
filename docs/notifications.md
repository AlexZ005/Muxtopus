---
title: Notifications
nav_order: 8
---
{% raw %}
# Notifications, and answering from the phone

Three lanes once waited fifty-five minutes behind one window sitting on `Do you want to proceed?`. The watchdog already captures every idle pane on every pass, so noticing costs nothing; the only thing missing was somewhere to say it. `claude-notify.sh` sends through **Telegram**, ntfy or Pushbullet, and with Telegram the message carries buttons, so the answer can come back.

```bash
claude-notify.sh --setup      # the guide: backend, token, and your first START
claude-notify.sh --status     # which backend is configured, and when it last sent
claude-notify.sh --test
```

## Setup

`--setup` is also `esc ▸ Settings ▸ Notifications ▸ Set up…` in the dashboard, which opens it in a tmux window of its own because it waits for you to press START in Telegram. It needs only `curl` and `jq`, and walks:

1. **Already configured?** It shows the backend and offers test, reconfigure or keep.
2. **Pick a backend.** Telegram first — the only one whose buttons can answer back — then ntfy and Pushbullet, which are two questions each.
3. **Telegram:** the BotFather steps in six numbered lines (`/newbot`, a name, a username ending in `bot`, copy the token); paste the token, which is validated with `getMe` and the bot's name echoed back; then *open t.me/<bot> and press START* — and it **waits**, polling for up to three minutes until your chat appears. Several chats → pick one.
4. **The one-sentence privacy note** and the inbound question: let the buttons answer prompts and questions?
5. **Write the file** and send a test message *with a button*, waiting for the press to prove the inbound half end to end.

It writes `~/.config/claude-notify.conf` (`0600`; it holds a token, and the old file is kept as a `.bak-<stamp>`), and that file is **per machine** — `getUpdates` has a single consumer, so two accounts' daemons share one bot and take one lock. By hand, one backend:

```sh
# ntfy -- no account, no token; the topic name IS the address, so pick
# something unguessable. Install the ntfy app and subscribe to it.
BACKEND=ntfy
NTFY_TOPIC=deck-a7f3k2-alerts
NTFY_SERVER=https://ntfy.sh          # optional, self-host if you prefer

# Pushbullet
BACKEND=pushbullet
PUSHBULLET_TOKEN=o.xxxxxxxx

# Telegram -- the only backend whose buttons can answer back
BACKEND=telegram
TELEGRAM_TOKEN=123456:ABC...
TELEGRAM_CHAT=987654321
```

`claude-notify.sh --telegram-chat TOKEN` prints which chats have messaged a bot, which is the fiddly half of finding your chat id. Unconfigured is not an error: the caller is a background service and a missing phone is not a reason to fail a pass.

What you are *told* is per account, in the settings store, on the seven `MUXTOPUS_NOTIFY_*` keys ([Configuration](configuration.md)) — the same Settings menu writes those, one row each, and the top row says which backend is configured and when it last sent. `Send a test` proves the phone hears this account.

## Four things, each its own switch

Each is said **once per occurrence rather than once per pass**, and every title starts with the account's label, so two accounts on one phone are told apart:

| event | fires when | key |
|---|---|---|
| **waiting** | an idle pane shows a permission or trust prompt on two consecutive passes (so ≥ 30 s, not a flash). Drawn `needs you`, yellow, on the dashboard too | `MUXTOPUS_NOTIFY_WAITING` |
| **questions** | an unanswered QUESTIONS file is new, or has a new unanswered fork | `MUXTOPUS_NOTIFY_QUESTIONS` |
| **trouble** | a verdict becomes `stalled` or an entry `error`; a lane becomes `stranded`; a launch fails; an entry has been `blocked` longer than `MUXTOPUS_NOTIFY_BLOCKED_AFTER` minutes (120; `0` never) — plain blocked is ordinary waiting | `MUXTOPUS_NOTIFY_TROUBLE` |
| **done** | a handover reaches `done/`: its gist, and the entries it released | `MUXTOPUS_NOTIFY_DONE` |
| (always) | a usage limit that empties *before* the time it promised | — |

Two more switches: `MUXTOPUS_NOTIFY_INBOUND` — whether buttons are attached and replies obeyed at all, and whether the bot answers commands; and `MUXTOPUS_NOTIFY_PANE_TEXT` — whether a waiting message may quote the prompt box. That is the one line of pane text that leaves this machine for the backend's servers; off, a waiting message names the window and nothing else.

A daemon restart re-reads what was already sent and re-sends nothing; a condition that ended and comes back fires again.

## The phone can answer

A waiting message carries **Yes · No · More**: Yes sends `1`, No sends Escape, More sends the lines above the prompt box. The pane is re-captured first and the keys are only sent if the *same* prompt is still there, so an answer that arrived after you answered at the machine edits itself to say so instead. `Yes, and don't ask again` is never offered from a phone: approving one action is not the same as changing a policy.

**A question, too.** Each unanswered fork arrives as a message of its own: the fork's text, a button per option (`(a) · ★ (b)`, the star on the one the lane recommends) and **✎ type**. Or just reply to the message. The answer is written into the fork as `**Answer (user via telegram, <date>):**`, by the same function the dashboard's answer flow uses. A lane that rewrote its file in the meantime still gets the answer in the right fork, found by title, and the message says the file had changed. A fork already answered at the machine is left alone, and the message says that instead. When the last fork is answered the file is marked ANSWERED, and if the lane's window is open and idle it is told `Your questions are answered in <path>`. Every answered message is edited to say what was written and when, so the chat is the record. At most eight forks of a file are sent at once; the rest wait in [the dashboard](handovers.md#answering-a-fork-without-leaving-the-dashboard).

## Or ask it, with every push switched off

A push can be missed, muted or dismissed, and a dismissed message takes its buttons with it — so the bot also answers commands, registered in Telegram's own menu button. With all four push switches off and inbound on, the bot is silent until asked — a supported way to run it.

| | |
|---|---|
| `/status` | per account: sessions by state, budget and reset, pending/blocked/stalled entries, open handovers, unanswered questions, watchdog heartbeat |
| `/pending` | everything actionable, **re-issued with fresh buttons**: prompts, each unanswered fork, trouble. The "I dismissed it" command |
| `/questions` | the unanswered QUESTIONS files as buttons (`25-late · 2 forks`); press one for its forks |
| `/blocked` | each entry that is not launching, with the scheduler's own why |
| `/windows` | one line per session; a `needs you` row brings its buttons |
| `/stats` | the usage ledger's totals; the buttons switch week / month / all |
| `/mute 2h`, `/unmute` | pushes off for a while; asking keeps working |

Re-issuing retires the old buttons and edits that message to `superseded`, so a stale button can never fire twice. Only the configured chat is ever obeyed; anything else is logged and dropped. There is **no webhook and no open port** — the watchdog polls `getUpdates` once a pass, so an answer lands within about 30 seconds — and the two accounts' daemons share one lock, so one update is handled exactly once.

## Two honest limits

Pane text leaves your machine for the backend's servers when `MUXTOPUS_NOTIFY_PANE_TEXT` is on, which is what that switch is for. And nothing typed on a phone is ever run as a shell — a prompt answer is one of two keys and nothing else, and a typed fork answer is a line of text in a QUESTIONS file.
{% endraw %}
