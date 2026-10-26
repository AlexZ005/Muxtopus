---
title: Orchestrators
parent: Scheduled windows
nav_order: 1
---
{% raw %}
# Orchestrators: a wave and a sweep

An orchestrator is an ordinary scheduled window whose job is other windows. It is **a pattern, not a process**: there is no orchestrator daemon, no orchestrator entry type and nothing in the executor that knows the word. What makes a window an orchestrator is the text it is pasted — one of four templates in the account's `schedules/templates/` — and the entries it writes. The liveness half (noticing a lane has stopped) stays in the watchdog, which costs nothing; see [`stranded`, and why the orchestrator is a pattern](schedules.md#stranded-and-why-the-orchestrator-is-a-pattern-rather-than-a-process).

An orchestrator works on **the account it was started from**: that account's tmux session, its windows, its schedules folder and its handovers. It never reaches into another account.

## Two shapes

There are two kinds of orchestrator, and they disagree on every axis a template has to state — which is why they are two templates rather than one with an "if you are a wave…" in it. A fork inside a paste is a sentence the model evaluates on every run, at full price, and a sweep that reads "if you are a wave, write one entry per lane" is one bad turn from spawning lanes it does not own.

| | wave | sweep |
|---|---|---|
| owns lanes | yes: writes one entry per lane, under its own window | none, ever |
| input | a plan file | the watchdog's state files and `handover.sh list` |
| output | the lane entries, one integrate entry, and its own STATUS file (which *is* the plan) | a table, a phone line, and its own next entry |
| ends | after one turn; integration is a separate window | after one turn; it recurs |
| worth a turn | always: a plan needs a model | **only when something is actionable** — most of its steps are reading state, and usually there is nothing to do |
| the trap | none specific | a pane's `❯` line is a hint, not a message ([below](#the-trap-the-prompt-line-is-a-hint)) |
| the human gate | "integrate, then hand over" | "push, PR, close — never release" |

### When a wave is worth it

A wave costs one planning turn and one cold integrate turn; nothing is spent while the lanes run, because the orchestrator ends its turn and the scheduler holds the integrate entry on `after:` until every lane is done. That overhead pays for itself at **three or more lanes that can run in parallel**. Below that, one window doing the work in phases is cheaper and easier to follow.

## The four templates

`setup-schedules.py` seeds them beside the plan templates, and — like every template — writes one only when its file is absent, so an edited template survives every re-run and a deleted one comes back with the shipped text. All four are **`type: work`** templates: an orchestrator is finished only when `handover.sh done` runs, and only a work entry carries the footer that says so.

| template | pasted into | what it does |
|---|---|---|
| `orchestrate.md` | the wave orchestrator | reads the plan, writes its STATUS file **first** (the file is the plan; the window is not), one entry per lane, one integrate entry, `claude-watchdog.sh --check`, then ends its turn |
| `lane.md` | each lane a wave spawned | the brief is the whole job; no push and no PR unless the brief says otherwise; a "For the orchestrator" section in its handover |
| `integrate.md` | the wave's integrate step | takes over an earlier integrator's worktree if there was one, reads every lane handover, merges in the plan's order, then marks the orchestrator done |
| `sweep.md` | the recurring sweep | a census from state files, acts on what is finished, reports, writes its own next entry |

What `orchestrate.md` asks of every lane brief is what the briefs that actually worked had in common: an **identity line** first ("Read this brief and execute it end to end. Your slug is …; your handover is …; your questions file is …"), a **"Facts measured by the planner"** section with a receipt for each fact (a count, a file, a date) so no lane re-derives it, **phases sized S/M/L, each with its test**, and a **Finish** line that says exactly what done means for that lane — which tests, whether it pushes, a PR to which base, merge or never merge.

A lane's slug starts with the orchestrator's (`<orch>-<lane>`), so two orchestrators cannot share a lane file or a handover.

**Round 2 is a new wave, not a resume.** When the owner answers a preview with fixes, the orchestrator writes a new wave whose rules file names that feedback as its acceptance test, rather than waking the old lanes.

The dashboard's create form offers these through a third pick, `orchestrate ▸ wave / sweep`, which copies the chosen template into the body and records the shape in an informational `kind:` header line. A wave starts with `orchestrate` ticked; a sweep starts with `subwindows`, `preview-gate` and `rules-file` off; neither has `nopush`, which would contradict `automate` — [the options table](schedules.md#the-options-table) has the rules. The templates use two placeholders beyond the lane's own — `{{HANDOVERS}}` (the handovers folder) and `{{STATE}}` (this account's watchdog state directory) — and a work entry may name a template with `template:`, which is how a sweep's next entry stays a ten-line header.

### Options only an orchestrator is offered

The options table carries a group of `types: orchestrate` blocks, each one sentence appended to the paste like any other option:

| key | default | what the sentence asks |
|---|---|---|
| `automate` | on | work until the whole item is finished: commit, push, open PRs and merge them when green, in dependency order |
| `preview-gate` | on (a wave) | before anything irreversible — a release, a tag, a deploy — stop at a preview and wait for "release" typed in this window |
| `plan-window` | off | write the plan in a separate `plan` window first, then spawn lanes from it |
| `rules-file` | on (a wave) | one rules file every lane reads first; a brief says only what differs, and the difference wins |
| `roles` | off | name a professional role per lane in its brief |
| `credits` | off | an external budget shared by the lanes, planned in the STATUS file, a share per brief |
| `cadence` | off | the sweep's next `at:` — never sooner |

The defaults in the shipped table are a wave's; a sweep owns no lanes and never releases, so `preview-gate` and `rules-file` mean nothing to it. The table is `~/.config/muxtopus/options.md`, copied once and then yours, like the templates.

## How a sweep recurs, and how it stops

`at:` is one-shot: an entry is launched once and marked `launched`. A sweep gets its next run by **writing its own next entry** as the last thing it does. Of the ways a recurring job could be built, it is the only one where the number of turns can go *down* when there is nothing to do, and the only one that needs nothing new from the executor: every turn in the chain was requested — by the owner's first entry, and by the template the owner chose, which says in words when to write the next one and when not to.

- **The cadence** is the `cadence` option's time, or **`at: reset`** when it is unticked — the existing five-hour gate, which fires on a quiet account whether or not anything hit a limit. The template says *never sooner*: the model may end the chain, but it may not shorten the cadence.
- **The stop condition.** When nothing is open anywhere — no open handover, no pending entry, and no checkout that is dirty or unpushed — the sweep writes **no** next entry, and says so in its report, on the phone and in its handover. The owner starts the next chain with one `c`.
- **The slug is date-stamped**: `sweep-MMDD`, with `-b`, `-c` … for later runs the same day. Not vanity: the closure rule below is keyed by slug, and a sweep always named `sweep` would find its predecessor's finished handover and close *its own* window. With a stamp, the next sweep closes the last one's window as an ordinary finished lane.
- **A runaway is visible.** The next entry is in the `s` view the moment it is written, and `d` deletes it; `claude-watchdog.sh --check sweep-` lists every one pending.
- **A dead chain is visible too**: a sweep that dies mid-turn leaves an open handover and an idle window, which is exactly what `stranded` reports.

A no-op sweep still costs one turn — a table and a next entry, reading only state files. That price is paid at the cadence the owner set and never more often.

## The closure rule

A sweep closes a window only when **all** of these hold:

- the window's `STATUS-<slug>.md` is in the handovers `done/` folder;
- it is not the window holding a release that has not shipped;
- it is not a dashboard, a plain shell, or the sweep's own window;
- no pending entry names it in `window:`, `parent:` or `after:` — otherwise a wave's late lanes would launch under a window that no longer exists and be drawn as roots.

It closes by the window **id** from the tree, never by name, because names repeat. An unanswered questions file does not keep a window open: the file outlives the window, and `handover.sh list` keeps showing it.

## The trap: the prompt line is a hint

Text after a `❯` in an idle Claude Code window is the CLI's dimmed placeholder **hint**, not a message someone typed and nobody sent. Measured on 2026-09-20: twelve such lines each looked like pending input, and one read "close the PR and delete the remote branch" — for a PR that had already been merged. Re-sending it would have been destructive. So a sweep never reads a pane and never types into one: what a window owes is judged from its handover and its repository, both files.

## Dev servers on demand: `lane-dev`

A lane that proves its work in a browser needs a dev server for a minute or two, then not for an hour. In one round on a 29 GB machine, twelve lanes each left a vite server running (about 1 GB apiece with its workers), swap filled, and every window opened after that made it worse. Lanes had been told to "stop it after", and they forgot. The [memory guard](watchdog.md#the-memory-guard) now holds new windows while memory is low, and `lane-dev` keeps the servers from piling up in the first place:

```bash
lane-dev start <dir> <port>        # npm run dev -- --port <port> --strictPort, in <dir>
lane-dev start <dir> <port> --idle 5 -- <command…>   # any command; $PORT is set
lane-dev status                    # PORT  PGID  RAM  UNUSED  DIR
lane-dev stop <port|dir>
```

- `start` returns once the port is listening. The server runs in a session of its own, so it outlives the shell (or the tool call) that started it, and `stop` takes npm, vite and every worker down as one process group. It refuses (exit 3) a port that something else is listening on, or that lane-dev runs for another folder. `start` on a folder that is already running is a no-op.
- **It stops itself.** A watcher stops a server that nothing has used for `--idle` minutes (`LANE_DEV_IDLE`, default 15; `0` never). *Used* means an open connection to the port, or one the last poll (every 10 s) had not seen. An open browser tab holds the HMR websocket and keeps the server alive, so close the browser when the proof is done.
- Its state is in `~/.local/state/lane-dev/<port>/`. The server's output is the `log` there, kept as `<port>.log` once the server has stopped, with the reason it stopped.
- Without a `package.json`, give the command after `--`, or in `LANE_DEV_CMD` (run with `bash -c`).

**`e2e-slot --dev <dir> <port> -- <command>`** starts that folder's server once a slot is held, runs the command and stops the server afterwards. A server that was already running is left as it was. Its idle timer still applies. `e2e-slot` is the machine-wide set of Playwright slots, two by default. `MUXTOPUS_E2E_SLOTS` (esc ▸ Settings ▸ Budget ▸) sets how many; `E2E_SLOTS` in the environment beats it for one run. `--exclusive` holds every slot (for timing runs), and `--wait SECS` bounds the wait (exit 75 when none came free). The command sees `E2E_SLOT=A`, `B`, … or every letter at once for an exclusive run. `MUXTOPUS_E2E_REMOTE` adds [remote slots](remote-e2e.md) whose browser runs on another machine; `--local` keeps a run off them. `--pc-first SECS` waits up to SECS for a [pc slot](pc-host.md) before taking any other — for a run of hours that would otherwise sit in this machine's RAM — and stops waiting the moment a pc host is found asleep. A slot is a `flock`, and neither lane-dev nor the server it starts inherits it, so a server outliving a run never holds a slot.

`install.sh` links both into `~/.local/bin` beside `muxtopus`, but only where the name is free or already a link into a muxtopus checkout. A file of your own by either name is left alone, and the installer says so.

**For lane rules** (what an orchestrator should paste into a brief):

> Start your dev server only for a proof run: `lane-dev start <worktree> <your port>`, or `e2e-slot --dev <worktree> <your port> -- <e2e command>`, which starts it for the run and stops it after. `lane-dev stop <your port>` the moment the proof is taken; the idle watcher stops a forgotten one after 15 minutes. Never leave a browser open on it.

## Long runs, typing into a lane, and pre-flight

Three small tools for the things lanes and orchestrators got wrong unattended. `install.sh` links them beside `lane-dev`.

- **`mux-done run <label> -- <command>`** runs a long command (a test battery, a production proof) unchanged — its output and exit code pass straight through — and, when it ends, leaves ONE line in `~/.local/state/claude-watchdog/done/<slug>/<label>.done`: the label, the exit code, the minutes and the command's last output line (or the last line matching `MUX_DONE_MATCH`). Start it in the background and end the turn: Claude Code's task notification wakes the lane. If the notification is lost — measured: three lanes compacted while idle and never woke — the watchdog finds the marker for a window that has been idle since BEFORE the run ended and types that line into it, once ([`WATCHDOG_DONE_NUDGE`](configuration.md), default 5 minutes). `mux-done mark <label> <text>` writes a marker by hand, `list` shows them (and what is running or lost), `ack` clears them; the slug comes from `--slug`, `MUXTOPUS_SLUG` or the window's name.
- **A run stopped before it finished.** Claude Code stops an idle session's background shells under critical memory pressure — its low-memory reaper, which kills the shell's process group and everything under it — and its notice tells the agent the command "was stopped because the system is running low on memory" and *not* to start it again until asked. Measured: a lane's queued e2e rerun was stopped that way while it waited for a slot, the lane did as the notice said, and a green release waited 13 hours. So while `mux-done run` works it leaves `<label>.run` (its pid and start time); a run whose process is gone with no marker is **lost**. The watchdog types the lane one line — "Your run <label> was stopped before it finished (low-memory reaper). Requeue the same command now (lane rule); say so in STATUS." — with the command, once more 30 minutes later if the label was not started again, and tells the lane's parent when the same label is lost twice or the second line went unanswered ([`WATCHDOG_LOST_RUN_NUDGE`](configuration.md), default `on`). The reaper is named only when its notice is in the lane's transcript after the run started; otherwise the line says the process is gone and wrote no result. Starting the label again clears it; `mux-done ack <label>` clears a run you stopped on purpose. `--health` lists it as `e2e job lost: <slug> <label>`, and the window's TAGS read `lost`.
- **`mux-done run --detach <label> -- <command>`** runs the command in a session of its own (`setsid -f`), out of the reaper's reach: the part left in the background shell prints the run's output and exits with its code, so the task notification is as before, and if that part is reaped the run goes on and its marker wakes the lane through the done nudge. Stopping the shell no longer stops the run: `mux-done stop <label>` does (it signals only a process group the run leads). Use it for long batteries and queued e2e reruns, not for a dev server.
- **earlyoom**, if the machine runs it, is not what stops these: it kills the process with the largest memory score, and an `e2e-slot` waiter or a `mux-done` wrapper is a few megabytes of bash. To make that explicit, add `--avoid '^(e2e-slot|mux-done)$'` to its options (it matches the process name; on a systemd box, `EARLYOOM_ARGS` in `/etc/default/earlyoom`). With `-g` earlyoom kills a victim's whole process group, so a browser it kills mid-run can take its `e2e-slot` holder with it — a lost run, which the watchdog then reports as above. Muxtopus does not change earlyoom's configuration.
- **`mux-send <target> <text>`** types one line into a Claude window the way that works: the text literally, a second's pause, Enter as its own key, then a look at the input box; Enter again (twice at most) while the text still sits there. Exit 1 when it is still unsent — left in the box for a person to see — and 2 when there is no such pane (resolved with `list-panes`: `display-message -t` with a window that does not exist answers for the CURRENT pane).
- **Pre-flight.** The PostToolUse hook runs **`mux-lint`** the moment a session writes a schedule entry or `profile.sh` (a Write or Edit of the file, or a Bash command naming either), and hands the session what it found in the same turn: a schedule entry that starts with a YAML `---` line (every reader takes its front matter as empty, so it never launches — the line is dropped on the spot, and the watchdog drops it on its next pass from a file nobody linted), anything `--check` says can never run, and a comment on a `KEY=` line or a syntax error in `profile.sh`. `mux-lint schedule <file>` and `mux-lint profile [<file>]` run it by hand.

## Machine reports

A lane that stalls, finishes, waits at a prompt, stays stuck after its limit reset or holds an e2e slot for hours is [reported to its parent](watchdog.md#reports-to-the-parent): the watchdog types one line into the window that spawned it, starting `MUXTOPUS watchdog (HH:MM), a machine report for <slug>, not the owner`. For a wave that window is the orchestrator — which has ended its turn, so the line is what wakes it. `orchestrate.md` tells it what to do with one: in one short turn, nudge a stalled lane with one line (`tmux send-keys -t <win> -l '<text>'`, then a separate `tmux send-keys -t <win> Enter`), close a finished one under the closure rule above, list a prompt or a long hold for the owner, then end the turn again. It is still not waiting: the watchdog is the one watching, for free, and a turn is spent only when something is wrong.

`claude-watchdog.sh --health` prints the same verdicts on demand. With no orchestrator to hear them — a lane whose parent is gone, or a root window — the phone is told instead.

## What an orchestrator never does

- **Release.** It never runs `release.sh`, never tags, never publishes, never merges a release PR (a `release/*` branch, or one that bumps `VERSION`) and never edits `VERSION`. Those are the owner's, every time; `preview-gate` exists to stop *before* them.
- **Wait.** A wave ends its turn after writing its entries; the integrate entry waits on `after:`, not a window polling. A turn spent waiting is budget spent on nothing.
- **Resume a stranded lane.** A lane whose handover is open and whose window is gone is listed for the owner, with its handover's next step. An unrequested turn is still a turn.
- **Answer a question.** An unanswered questions file is listed, never answered.
- **Type into a window that is holding a gate.** A window waiting for the owner's word is doing its job.
{% endraw %}
