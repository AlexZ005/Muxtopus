# changes/

One file per pull request, named after its lane (`changes/<slug>.md`): a
heading and a few lines about what a USER would notice. A release
concatenates them into `CHANGELOG.md`, bumps `VERSION` and tags `vX.Y.Z`,
after which the fragments are removed.

Why fragments and not a changelog everyone edits: several lanes run at once,
each on its own branch, and a single `CHANGELOG.md` is then a guaranteed
conflict at the top of the file in every one of them. A new file per lane
never conflicts with anything.

    ## dashboard: <what changed>

    - the sentence a user would want to read
    - another, if the change has two halves

Nothing about refactoring, test counts or commit hygiene: that is what the
pull request and the commits are for. A fragment that says only "internal
refactor, no user-visible change" is the right fragment for a lane that has
none, and that is worth writing down too.
