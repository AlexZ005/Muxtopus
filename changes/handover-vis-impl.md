## dashboard: handovers and questions, where the schedules are

The `s` screen has a second tab. `←` `→` moves between them; the strip names
both and carries their counts, so from the schedules you can still see how
many handovers are open and how many question files are waiting on you.

- Every lane's STATUS and QUESTIONS file in one list, from BOTH folders,
  ordered by what is OWED: unanswered questions first, then open handovers,
  then everything finished. Each row says how old it is, which window the
  lane ran in and whether that window is still open, and how many pending
  schedule entries are waiting on it.
- **A fork can be answered without leaving the dashboard.** `enter` on a
  question file walks its forks one at a time, offers the lettered options as
  rows with the recommended one already picked, and writes your answer into
  the file the moment you give it — with the editor one key away on every
  screen, because no parser will understand every lane's prose.
- `space` acts on a row: view, edit anyway, open its window, mark done, mark
  answered, or tell that lane's window its answers are in. Marking a handover
  done launches everything held `after:` it, so the confirm names them.
- Two filters, `f` for finished rows and `a` for question rows, and both are
  remembered between runs — `R` no longer resets them. What a filter hides is
  always counted on the panel border.
- On the main view, a session whose lane has an unanswered question file
  carries a yellow `?`, and the key line says how many are waiting.
- `handover.sh` gains `answered` and `unanswer`; `done` now carries an
  answered question file into `done/` with its handover and leaves an
  unanswered one where it is, because a finished lane's open forks are still
  owed a look.
- Question files are read from both folders. The old panel looked only in the
  legacy one and therefore usually showed nothing at all.
- A lane that ran, was marked done and then ran again has two handover files,
  and `after:` has always treated it as finished. The row now says so, in
  yellow, instead of quietly disagreeing with the executor.
