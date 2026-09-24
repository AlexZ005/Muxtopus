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

The dashboard's create form offers these through a third pick, `orchestrate ▸ wave / sweep`, which copies the chosen template into the body and records the shape in an informational `kind:` header line. The templates use two placeholders beyond the lane's own — `{{HANDOVERS}}` (the handovers folder) and `{{STATE}}` (this account's watchdog state directory) — and a work entry may name a template with `template:`, which is how a sweep's next entry stays a ten-line header.

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

## What an orchestrator never does

- **Release.** It never runs `release.sh`, never tags, never publishes, never merges a release PR (a `release/*` branch, or one that bumps `VERSION`) and never edits `VERSION`. Those are the owner's, every time; `preview-gate` exists to stop *before* them.
- **Wait.** A wave ends its turn after writing its entries; the integrate entry waits on `after:`, not a window polling. A turn spent waiting is budget spent on nothing.
- **Resume a stranded lane.** A lane whose handover is open and whose window is gone is listed for the owner, with its handover's next step. An unrequested turn is still a turn.
- **Answer a question.** An unanswered questions file is listed, never answered.
- **Type into a window that is holding a gate.** A window waiting for the owner's word is doing its job.
{% endraw %}
