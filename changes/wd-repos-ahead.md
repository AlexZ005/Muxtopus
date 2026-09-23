## dashboard: unpushed commits show up beside uncommitted files

- The uncommitted panel on the main view now lists a tree that is ahead of its upstream even when nothing in it is modified, with `↑n` beside the file count for n commits not yet pushed (`0 ↑2` is a clean tree two commits ahead), and the panel's title adds how many commits are unpushed in all. An unpushed commit lives only on this disk, which is what the panel is there to warn about.
- The count is against the last `git fetch`: the watchdog never fetches and never touches the network. A branch with no upstream, or a detached HEAD, shows no arrow rather than a `↑0` nobody measured.
- `repos.tsv` in the watchdog's state folder gains three columns after the three it had: branch, ahead and behind (`-` when they cannot be known).
- Goldens: the dashboard fixture's repo-b is now two commits ahead, so the 31 screens that draw the uncommitted panel moved by two lines each — its title gains `· 2 commit(s) unpushed` and repo-b's cell reads `3 ↑2`. Nothing else in any screen moved.
