# Skills in this repository

`.claude/skills/` holds the repeatable procedures of this repo as Claude Code
**skills**: a skill is a folder with a `SKILL.md`, loaded on demand by name
rather than read into every conversation. They are checked in so that anyone
working here — with an agent or without one — gets the same procedure, and so
that a change to how we release travels in the same commit as the change to
`release.sh`.

| skill | what it is for |
|---|---|
| [`start-a-lane`](.claude/skills/start-a-lane/SKILL.md) | branch, worktree, venv symlink, fragment — the lane rules, before the first edit |
| [`cut-a-release`](.claude/skills/cut-a-release/SKILL.md) | assemble the changelog, bump `VERSION`, tag, build `dist/`, publish and verify |

## Using them

With Claude Code in this checkout they are available as `/start-a-lane` and
`/cut-a-release`, and the agent will reach for one when the task matches its
description. Without an agent they are ordinary Markdown: read the file.

## Adding one

A procedure earns a skill when it is **repeated**, **easy to get wrong**, and
**longer than a paragraph**. Everything else belongs in
[`docs/contributing.md`](docs/contributing.md) (how the code is shaped) or
[`CLAUDE.md`](CLAUDE.md) (the short list of traps).

```
.claude/skills/<name>/SKILL.md
```

with front matter naming it and saying *when to use it* — the description is
what a reader or an agent matches against, so write it as a trigger ("use when
asked to release, tag or publish") rather than as a title.

Keep a skill about **procedure**. Why the code is the way it is belongs in the
code's own comments, which in this repo are long on purpose.
