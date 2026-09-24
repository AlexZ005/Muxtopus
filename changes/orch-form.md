## schedules: `c ▸ orchestrate ▸ wave / sweep` creates an orchestrator

- `c` in the schedules view offers a third pick, **orchestrate**, and then **wave** or **sweep**. The entry it writes is an ordinary `type: work` entry whose body is `templates/orchestrate.md` or `templates/sweep.md`, copied so what you edit is what gets pasted, with a `kind: wave` or `kind: sweep` line the executor ignores.
- The options table for an orchestrator offers the `orchestrate` group (full automation, the preview gate, a rules file, the sweep's cadence …) on top of the usual work options. A wave starts with *orchestrate, don't babysit* ticked. A sweep starts with *spawn sub-windows*, the preview gate and the rules file off. Neither starts with *no push*, because full automation pushes. A plain `plan` or `work` entry never sees the orchestrate rows, and the plan template picker no longer lists the four orchestrator templates.
- A sweep is named `sweep-<MMDD>` (`-b`, `-c` … for a second one that day) and pins that as its `slug:`.
- `o` on an orchestrator entry reopens it with the orchestrate rows, read from `kind:`.
- If the template is missing, the picker says so on that row and points you at `setup-schedules.py`. An `options.md` from before the orchestrate group existed gets a notice naming `seeds/options.md` to copy it from.
- `claude-watchdog.sh --check` no longer reports a long entry's body as "empty" now and then.
- Goldens: `create-type` (the third row) moved. `create-orchestrate` and `create-orch-options` are new: the `wave / sweep` picker, and a sweep's options table with the orchestrate group.
