# The fake machine's options.md -- one block of every shape the table can
# draw: a plain line, a types-filtered line (work, and orchestrate), an ask:
# that opens the prompt, a set: that opens the picker, and one deliberately
# broken block that must be shown greyed with its reason rather than dropped.

key: questions
group: contract
label: questions go to a file
hint: nobody is watching: QUESTIONS-{{SLUG}}.md, recommended answer, proceed
default: on
line: Nobody is watching this window: write any fork to {{QUESTIONS}} with a recommendation and proceed.

key: phases
group: contract
label: one commit per phase
hint: [feat] <phase>: summary, body bullets, attribution trailer
default: on
types: work
line: Work in phases, ONE commit per phase, the test run before the commit.

key: nopush
group: contract
label: no push, no PR
hint: the orchestrator integrates
default: off
line: Do not push and do not open a pull request.

key: lanes
group: windows
label: parallel lanes
hint: a number; {{VALUE}} in the sentence
default: off
ask: number
line: Run at most {{VALUE}} lanes in parallel.

# Offered only to the orchestrate pick (c ▸ orchestrate ▸ wave / sweep):
# hidden from every plan and work table, so no older screen moves.
key: automate
group: orchestrate
label: full automation, end to end
hint: commit, push, PRs, merge when green; never stop to ask
default: on
types: orchestrate
line: Full automation, end to end: work until the whole item is finished.

key: model
group: model
label: model
hint: a CLI alias, written as a header field
default: off
set: model
choices: opus, opus[1m], fable, sonnet, haiku

key: effort
group: model
label: effort
hint: passed as claude --effort
default: off
set: effort
choices: low, medium, high, xhigh, max

key: Broken_Key
group: project
label: a block nobody can parse
line: It should still be shown, greyed, with its reason.
