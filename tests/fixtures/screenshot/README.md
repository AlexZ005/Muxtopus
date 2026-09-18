# tests/fixtures/screenshot -- the machine in the README's screenshot

A fake machine for `make-screenshot.py`, in the shape `tests/sandbox/setup.sh`
copies in: `home/` becomes the sandbox HOME, `home/.local/share/muxtopus/` the muxtopus home,
`state/` the XDG state dir. Nothing in it is real: the account is called
`work`, the repos are `~/src/acme/*`, the session ids are made up and every
path is spelled with `@SB@` until setup.sh replaces it.

The story it tells, because a screenshot of an empty dashboard shows nothing:

    ➥checkout-refactor          working             a lane with three children
      ➥➥cart-api                needs you           sitting on a permission prompt
        ➥➥➥cart-qa           idle, handover done three levels deep
      ➥➥cart-ui                 limited             wound down at the session limit, a resume entry pending
    ➥billing-migration          stranded            idle 3h, handover open, nothing pending names it
      ➥➥billing-db  ?       working             its QUESTIONS file has two unanswered forks
    ➥search-index               due                 its reset has passed; the watchdog prompts it next pass
    infra                       idle                a hand-made window, opted out of both switches

Time is written relative to now -- `@T-3600@` an epoch, `@HM+5400@` a clock,
`@DATE-1800@` a stamp, each that many seconds from now -- in every file that
holds one, and `mtimes.tsv` says how old each handover file should
look; make-screenshot.py resolves both after setup.sh has copied the tree,
so the AGE and RESUMED columns read as they would on a live machine.

Window ids `@1`..`@7` in `tree.tsv` are the seven windows make-screenshot.py
opens in the sandbox session, in that order, so the handovers tab's WINDOW
column can say which are still open. `@9` is one that is not.

To change the picture, change these files and run `make-screenshot.py`.
