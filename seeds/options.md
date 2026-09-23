# Muxtopus -- schedule options: the checkbox table the dashboard shows when a
# schedule entry is created (`c`) or reopened (`o`). One block per option,
# blank line between blocks, the same `key: value` syntax as a schedule file.
#
#   key:      id, [a-z0-9-]+, unique; recorded as `options: a, b, lanes=3`
#   group:    table section (contract | windows | model | output | project)
#   label:    the checkbox text        hint: the dim text beside it
#   default:  on | off                 types: plan | work  (optional filter)
#   line:     ONE sentence appended to the prompt body, under "## Options"
#   set:      a header field instead of a line (needs choices:)
#   ask:      number | text -- collects {{VALUE}} when ticked
#
# Placeholders are resolved when the prompt is PASTED, by sched_compose:
#   {{SLUG}} {{WINDOW}} {{HANDOVER}} {{HANDOVERS}} {{QUESTIONS}} {{SCHEDULES}}
#   {{STATE}} {{CWD}} {{PARENT}} {{VALUE}}
#
# Per account: profiles/<name>.options.md is read after this file and
# overrides or adds by key. This file is yours; install.sh never rewrites it.

# ------------------------------------------------------------- contract

key: questions
group: contract
label: questions go to a file
hint: nobody is watching: QUESTIONS-{{SLUG}}.md, recommended answer, proceed
default: on
line: Nobody is watching this window: do not ask questions and never wait for an answer. If a fork genuinely needs the user, append it to {{QUESTIONS}} as a numbered question with the options, your RECOMMENDED one marked and a one-line why, then proceed with the recommendation and mark that decision provisional in the handover.

key: phases
group: contract
label: one commit per phase
hint: [feat] <phase>: summary + body bullets + attribution trailer
default: on
types: work
line: Work in phases, in the order given, ONE commit per phase: message `[feat] <phase>: lowercase summary` (or `[fix]`), body bullets saying what, why, how it was verified and the counts against your measured base, plus the attribution trailer your harness specifies. Never use bare `git stash` (it is shared across worktrees).

key: nopush
group: contract
label: no push, no PR
hint: the orchestrator integrates; untick for a release entry
default: on
types: work
line: Do not push, do not open a PR, do not touch another branch or worktree, and do not edit CLAUDE.md, CHANGELOG.md, RELEASING.md or the user docs -- list what they should say in your handover under "For the orchestrator".

key: lowpri
group: contract
label: /low-priority on a limit
hint: spends the WEEKLY budget instead of parking until the reset
default: on
line: Budget: if a usage-limit banner appears, type `/low-priority` and continue. If a "Budget checkpoint" note tells you to wind down, land the step you are on, commit, update {{HANDOVER}} and stop -- the scheduler resumes you.

key: verify
group: contract
label: verify by firing it
hint: a change only reasoned about, never run, is not verified
default: on
line: Verify end to end, for real: run the thing you changed and read what it did. A change that is only reasoned about, never fired, is not verified; say in the handover exactly what was run and what was observed, and list as OWED anything you could not run here (hardware, a phone, VR, a real GPU) -- never fake it.

key: symbols
group: contract
label: locate by symbol, not line
hint: plan line numbers are stale; never fix what already works
default: on
line: Line numbers and quotes in a plan are STALE: locate everything by symbol, read the code and `git log` first, and never "fix" something that already works.

key: expert
group: contract
label: act as the expert
hint: the professional in the relevant role; do what an expert would recommend
default: off
line: Act as the senior professional in the relevant role would: prefer the established practice over the clever one, say when a request would not be recommended and do it anyway if asked, and record the reasoning in the handover.

key: until
group: contract
label: stop at a time
hint: asks for a time; work until then, then pause with a handover
default: off
ask: text
line: Work until {{VALUE}}, then stop whatever you are on at a clean point: commit, bring {{HANDOVER}} up to date with exact resume steps, and end your turn. The user reviews before anything continues.

# -------------------------------------------------------------- windows

key: subwindows
group: windows
label: spawn sub-windows
hint: schedule entries under this window; never a monitor loop
default: on
line: You may open further Claude windows for independent subtasks: write {{SCHEDULES}}/<slug>.md (type: work, a past `at:`, `window: {{WINDOW}}`, `cwd:`, the brief as the body) and the watchdog launches it under this window within 30s, named ➥<slug>, with its own handover at ~/.code/handovers/STATUS-<slug>.md. Do NOT poll or monitor those windows yourself; read their handovers when you are resumed.

key: lanes
group: windows
label: parallel lanes
hint: asks for a number; the most windows working at once
default: off
ask: number
line: Run at most {{VALUE}} lane windows in parallel; a lane that must wait for another gets `after: <that slug>` in its entry instead of a window that sits idle.

key: orchestrate
group: windows
label: orchestrate, don't babysit
hint: spawn, end the turn, get resumed by after:
default: off
line: You are the orchestrator, and you do no lane work yourself: split the plan into lanes, write one schedule entry per lane (`window: {{WINDOW}}`, a brief each, `after:` where one depends on another), then write ONE more entry named integrate-{{SLUG}} with `after:` listing every lane and a body that says to read every lane's handover and integrate -- and then END YOUR TURN. Do not wait, poll or run a monitor: the scheduler resumes you when the lanes are done, and a turn spent waiting is budget spent on nothing.

# ---------------------------------------------------------------- model

key: model
group: model
label: model
hint: header field, passed as claude --model at launch
# MEASURED 2026-09-16: these are CLI aliases, NOT the names the dashboard's
# MODEL column shows. `--model opus-5` is refused ("may not exist or you may
# not have access") and the window dies on its first turn, having already
# eaten the paste. Valid: an alias (opus, fable, sonnet, haiku), optionally
# with a context suffix (opus[1m]), or a full id (claude-opus-5).
default: off
set: model
choices: opus, opus[1m], fable, sonnet, haiku

key: effort
group: model
label: effort
hint: header field, passed as claude --effort at launch (auto = unset)
default: off
set: effort
choices: low, medium, high, xhigh, max

key: permission-mode
group: model
label: permission mode
hint: header field, passed as claude --permission-mode at launch
# WHY THIS EXISTS (MEASURED 2026-09-16): a scheduled window is unattended, but
# the launcher passed no mode, so it inherited defaultMode from settings.json
# -- `auto` -- and an auto-mode window that meets a decision it will not take
# on its own STOPS, silently. That is how four lanes sat idle for three days.
# It cannot be fixed afterwards: shift+tab cycles auto -> manual -> accept
# edits -> plan -> auto, and bypassPermissions is NOT in that cycle (pressed
# four times on a live lane to check). Launch is the only way in.
# Left OFF by default on purpose: skipping every permission check is a choice
# an entry should make out loud, not inherit.
default: off
set: permission-mode
choices: bypassPermissions, acceptEdits, auto, manual, dontAsk, plan

key: route
group: model
label: route subtasks by model
hint: a cheaper model for mechanical steps, the strong one for judgment
default: off
line: Route subtasks by model: mechanical, well-specified steps (renames, fixture updates, running and reading a suite, a docs sweep) go to a cheaper model as a subagent or `claude -p --model sonnet`; design, integration and anything that decides a fork stay on this model. Say in the handover which steps went where.

# --------------------------------------------------------------- output

key: artifact
group: output
label: publish an Artifact
hint: the report as a claude.ai page; link in the handover
default: off
line: When the work is a report, audit or plan, publish it as an Artifact as well as writing the file, and put the artifact link at the top of {{HANDOVER}}.

key: prlink
group: output
label: session link in PRs
hint: https://claude.ai/code/session_... in every PR body
default: on
line: Every PR description you write ends with the link to this Claude session (https://claude.ai/code/session_...), as your harness's attribution note gives it, so the conversation behind the change can be opened from the PR.

# -------------------------------------------------------------- project
# Project lines: off by default, here as the pattern to copy for your own.

key: tp-base
group: project
label: theprototype: measure the base first
hint: npm run check gate, plain npm ci, held suites, serialised e2e
default: off
types: work
line: Before any edit, read CLAUDE.md's "Replication golden rules" and "Verification (mandatory before commit)", then MEASURE YOUR BASE in this worktree: `npm run check` (the number you measure is the gate; a plain `npm ci` only, never `--legacy-peer-deps`), `npx vitest run`, and every suite you are told to hold. Run e2e suites one at a time under `flock -w 5400 /tmp/tp-e2e.lock`, and prove each guard with a counterfactual before committing.

key: tp-plans
group: project
label: theprototype: plans are read-only, in cloud
hint: read by absolute path under cloud/docs/plans-core; never commit core plans/
default: off
line: Plans are versioned in the cloud repo and are read-only for you: read them by absolute path under /home/deck/.code/theprototype-app/cloud/docs/plans-core/ and never edit or commit anything under core `plans/` (gitignored on purpose). Your status goes in your handover; the orchestrator folds it into the plan files.
