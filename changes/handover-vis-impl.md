## dashboard: handovers and questions, where the schedules are

The `s` screen has a second tab. ←→ moves between them; the strip names both
and carries their counts, so from the schedules you can still see how many
handovers are open and how many question files are waiting on you.

- Every lane's STATUS and QUESTIONS file in one list, ordered by what is
  OWED: unanswered questions first, then open handovers, then everything
  finished. Two filters, `f` for finished rows and `a` for question rows, and
  both are remembered between runs -- `R` no longer resets them.
- Questions files are read from BOTH folders. The old panel looked only in
  the legacy one and therefore usually showed nothing at all.
- A lane that ran, was marked done and then ran again has two handover files,
  and `after:` treats it as finished. The row says so instead of quietly
  disagreeing with the executor.
