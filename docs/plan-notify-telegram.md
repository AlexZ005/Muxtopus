# Plan: tell the phone, and let the phone answer

Status: PLAN, 2026-09-17, written by lane `handover-visibility` at the user's
request; the forks in §8 were ANSWERED interactively before this was written.
Nothing here is implemented. Locate by symbol, not by line.

Read before this: `claude-notify.sh` (all 127 lines), the per-session loop at
the end of `claude-watchdog.sh` (where `state=` is decided and `stranded` is
logged), `check_schedules` / `sched-why.tsv`, `profile.sh` (`MUX_CONFIG_KEYS`,
`mux_load_config`), `muxconfig.py`, `muxsettings.py`,
`docs/plan-handover-visibility.md` §2.2 and §3b, `docs/plan-dashboard-menus.md` §5.

## 0. Why, measured today

`➥➥dash-menus-settings` sat **55 minutes** on Claude Code's
`Dangerous rm operation on possibly-empty variable path ... Do you want to
proceed?` -- under `bypassPermissions`, which does not cover that check. The
watchdog published it as `idle`. Three lanes and one held schedule entry
waited behind one keypress that nobody knew was wanted. Separately, a
QUESTIONS file appeared in `core/plans` and the only sign was a line in a view
that was not open.

What exists: `claude-notify.sh` sends plain text through ntfy, Pushbullet or
Telegram; Telegram is configured and working on this machine (`--status`,
last good send 09-05); its ONLY caller is `claude-usage.sh` (early reset).
`--telegram-chat <token>` already solves the fiddly half of setup. The
watchdog ALREADY runs `tmux capture-pane` on every idle pane every pass, so
detecting a prompt costs no new fork.

## 1. Events -- on CHANGE, never per pass

| event | fires when | switch (default) |
|---|---|---|
| `waiting` | an idle pane shows a permission / trust prompt on two consecutive passes (so ≥30 s, not a flash) | `MUXTOPUS_NOTIFY_WAITING` (on) |
| `questions` | an unanswered QUESTIONS file is new, or its set of unanswered forks changed -- both folders, as `muxhandovers.scan` reads them | `MUXTOPUS_NOTIFY_QUESTIONS` (on) |
| `trouble` | a verdict becomes `stalled` or an entry `error`; a lane becomes `stranded`; a launch fails; an entry has been `blocked` longer than `MUXTOPUS_NOTIFY_BLOCKED_AFTER` minutes (120; `0` = never) -- plain blocked is ordinary waiting | `MUXTOPUS_NOTIFY_TROUBLE` (on) |
| `done` | a handover appears in `done/`: its gist, and the entries it released | `MUXTOPUS_NOTIFY_DONE` (on) |
| (existing) | the early limit reset in `claude-usage.sh` | unchanged |

Plus `MUXTOPUS_NOTIFY_INBOUND` (on): whether buttons are attached and replies
obeyed at all; and `MUXTOPUS_NOTIFY_PANE_TEXT` (on): whether a `waiting`
message quotes the prompt box -- pane text leaves the machine for Telegram's
servers, the setup guide says so in one sentence, and this is the off switch.

Seven keys, in `MUX_CONFIG_KEYS`, `muxconfig.KEYS` and
`muxsettings.DASHBOARD_KEYS` in the same order (the existing mirror test covers
them). They live in the settings store, not in `claude-notify.conf`: that file
holds SECRETS and is per machine; the switches are preferences, per account,
written by the Settings menu, and the watchdog already reads the store through
`mux_load_config`. The user's requirement "configurable what to receive" is
exactly these rows.

**Dedupe.** `notify_event <key> <fingerprint> <title> <body> [buttons]` in the
watchdog: `key` is e.g. `waiting:%654`, `questions:<path>`, `blocked:<file>`;
it sends only when the fingerprint stored in `$STATE/notify/sent.tsv` differs,
and a key whose condition ended is dropped so the next occurrence fires again.
A daemon restart re-reads the file and re-sends nothing. Every title starts
with `$MUX_LABEL` so two accounts are told apart on one phone.

**The `waiting` state** also goes to `status.tsv` in place of `idle`, mirrored
in the Python state list the way `stranded` was (commit 75fbb02's pattern),
and drawn yellow as `needs you`. The detector is a small list of anchored
patterns (`Do you want to proceed?`, `❯ 1. Yes`, the trust dialog's wording),
in one variable, with fixture pane captures in the tests -- today's capture is
the first fixture.

## 2. Outbound with buttons

`claude-notify.sh` gains `--buttons 'Label=data|Label=data'` and
`--reply-to`/`--edit <message_id>`; Telegram renders an inline keyboard, the
other backends ignore buttons and append `answer at the machine`. It prints
the sent `message_id` on stdout. `TELEGRAM_API` (default
`https://api.telegram.org`) becomes overridable, which is what makes every
test below possible without touching the real bot.

A `waiting` message: window name, how long, the prompt box (last ≤25 lines,
when allowed), buttons **Yes · No · More**. A `questions` message: a header,
then ONE message per unanswered fork (cap 8, then `N more -- open the
dashboard`): the fork's text, buttons **(a) · (b) · (c)** with `★` on the
recommended one, **✎ type** (a ForceReply; a plain Telegram reply to the fork
message works too).

## 3. Inbound: `muxtelegram.py` (new, stdlib only)

Called once per watchdog pass when inbound is on and the backend is telegram:
`getUpdates` with the stored offset, `timeout=0`. Latency ≤ one pass (30 s).
No new daemon, no webhook, no open port.

* **One poller per bot.** `getUpdates` has a single consumer and the `claude`
  and `claude-work` daemons share one bot, so offset, lock and pending actions
  live in ONE per-machine folder (`$XDG_STATE_HOME/muxtopus-notify/`), taken
  under `flock`; a pending action records its profile and whichever daemon
  holds the lock dispatches it. Without this the two daemons steal each
  other's updates -- the first bug this design would otherwise ship.
* **Callback data is an opaque id** (Telegram caps it at 64 bytes):
  `pending/<id>.json` = `{kind, profile, pane, prompt_sha, path, fork_id,
  option, message_id, created}`. One-shot, expires after 24 h.
* **Who is obeyed:** only `from.id`/`chat.id` equal to `TELEGRAM_CHAT`, only
  callbacks whose id is pending. Anything else is logged and dropped.
* **A prompt answer** re-captures the pane and proceeds only if the prompt is
  STILL there with the same `prompt_sha` (the guard used by hand today);
  otherwise the message is edited to `already answered at the machine`. Yes
  sends `1`, No sends `Escape`. Option 2 (`Yes, and don't ask again`) is never
  offered: a phone may approve one action, not change a policy. More replies
  with the next 60 lines of the pane.
* **A fork answer** calls `muxhandovers.write_answer` -- the SAME function the
  dashboard's answer flow uses (handover plan §3b), with
  `**Answer (user via telegram, <date>):**`; when the last fork is answered it
  marks the file ANSWERED and, if the lane's pane is live and idle, sends it
  the `Your questions are answered in <path>` line.
* After acting: `answerCallbackQuery`, and the message is EDITED to say what
  was done and when, so the chat is the audit trail; `notify.log` gets a line.

## 4. Setup: `claude-notify.sh --setup`, opened from Settings

Interactive, plain `read`, no dependency beyond `curl` and `jq`:

1. Configured already? Show backend, offer **test / reconfigure / keep**.
2. Pick a backend: **Telegram** first, ntfy, Pushbullet (the latter two are
   two questions each; their guide is the header comment, reworded).
3. Telegram: the BotFather steps in six numbered lines (`/newbot`, name,
   username ending `bot`, copy the token); paste the token (validated with
   `getMe`, the bot's name echoed back); then `Now open t.me/<bot> and press
   START` -- and it WAITS, polling `getUpdates` every 2 s for 3 minutes, until a
   chat appears (the existing `--telegram-chat` logic, looped); several chats
   -> pick one.
4. The one-sentence privacy note (§1) and the inbound question (`let the
   buttons answer prompts and questions? [Y/n]` -> the store key).
5. Write `claude-notify.conf` under `umask 077`, the old file kept as
   `.bak-<stamp>`; send the test message WITH a button; wait for the press to
   prove inbound end to end; say `done -- this window closes in 5 s`.

Dashboard: **Settings ▸ Notifications ▸** (menu kind `notify`): a status row
(`telegram ✓ last sent 2m ago` / `not configured`), `Set up…` (runs
`tmux new-window -n notify-setup '<repo>/claude-notify.sh --setup'`; with no
`$TMUX` the row says to run it by hand and names the command), `Send a test`,
the six on/off rows, the blocked-after threshold as a choice row
(`never 30m 1h 2h 6h`). All through `muxsettings.put`.

## 5. Interaction with the other two plans

* `muxhandovers.parse_forks` / `write_answer` / `scan` come from
  `handover-vis-impl` phases 1 and 5b. This plan does NOT reimplement them.
* `deck_status.py` is owned, in order, by `dash-menus-settings` then
  `handover-vis-impl`. Hence TWO entries: **`notify-core`** (phases 1-3) starts
  now and never opens `deck_status.py`, `muxhandovers.py` or `handover.sh`;
  **`notify-dash`** (phases 4-6) is held by
  `after: notify-core, handover-vis-impl`.
* `notify-core` touches the key lists in `profile.sh` and `muxconfig.py`,
  which other lanes also append to. It stages with `git add -p`-equivalent
  care (diff first; commit only its own hunks) and says so in its commit body.

## 6. Phases, one commit each, and each test

Sandbox discipline as `docs/plan-dashboard-menus.md` §5, plus: `TELEGRAM_API`
points at a FAKE Bot API (`tests/fake_telegram.py`, stdlib `http.server`:
records `sendMessage`/`editMessageText`, serves scripted `getUpdates`), and
`CLAUDE_NOTIFY_CONF` at a sandbox file. NO test talks to the real bot, reads
the real `claude-notify.conf`, or sends a key to a real pane. The real
`--test` is the user's to press.

| # | lane | commit | test |
|---|---|---|---|
| 1 | core | `[feat] notify: --setup guide, --buttons, a swappable API base` | the wizard driven by a here-doc against the fake API: bad token refused, waits then finds the chat, conf is 0600 with a `.bak`, test message has a keyboard; ntfy/pushbullet paths still send; unconfigured still exits 0 |
| 2 | core | `[feat] watchdog: waiting state, and four events told once` | sandbox daemon + fake `claude` printing today's prompt: `status.tsv` says `waiting` on pass 2, ONE message, none on passes 3-5, a new one after the prompt clears and returns; each switch off -> nothing sent; blocked threshold with a faked clock file; `done` names the released entry; key-list mirror test green |
| 3 | core | `[feat] muxtelegram: the phone answers a prompt` | scripted callback from the right chat -> the sandbox pane receives `1`; from a wrong chat -> dropped and logged; stale `prompt_sha` -> not sent, message edited; expired id; two daemons, one lock: every update handled exactly once |
| 4 | dash | `[feat] muxtelegram: the phone answers a fork` | button and typed reply both land as `write_answer` lines; last fork marks ANSWERED; file changed underneath -> re-applied |
| 5 | dash | `[feat] settings: notifications, and a needs-you row` | captures: the submenu, a toggle round-tripped to the file the sandbox watchdog reads, `Set up…` opens a window IN THE SANDBOX server, `waiting` drawn yellow |
| 6 | dash | `[docs] notifications: README, help, the setup guide` | `--check` on real entries still 0 (read only) |

## 7. Not doing

A webhook or any listening port; approving `don't ask again` remotely; free
text typed into a pane from the phone (a prompt answer is one of two keys,
never a shell); per-event quiet hours (Telegram's own mute covers it);
WhatsApp/Signal/etc. -- the backend switch is where a second messenger goes,
and `--buttons` is the only thing it must implement to get inbound.

## 8. Forks, as answered by the user 2026-09-17

* Inbound: **buttons for forks AND prompts.**
* Events: **all four, each individually switchable** (the user's addition ->
  the keys of §1 in Settings).
* Setup: **Settings ▸ Notifications opening a new tmux window** running an
  interactive guide; Telegram first.
* Delegation: **another window, opus.**
