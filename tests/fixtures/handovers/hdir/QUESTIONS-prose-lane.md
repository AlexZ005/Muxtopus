# QUESTIONS -- prose-lane

Forks I could not ask about, with the answer I took. Nothing here blocked me.

## 1. The working tree already had uncommitted work when I started

MEASURED: eleven files modified, none of it mine. Every file parses, so it is
coherent rather than half-typed.

**Answer taken:** one checkpoint commit of the pre-existing tree FIRST,
labelled as such, then my phases on top of it.

## 2. `after:` naming a slug that never launches waits forever

An entry whose dependency never launches would sit pending indefinitely.

**Answer taken:** do not add a timeout. A dependency that silently gives up
and runs anyway is worse than one that waits.
