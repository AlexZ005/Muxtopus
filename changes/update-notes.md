## Release notes arrive on a machine without jq

`What is in <new>…` printed *"Release notes for muxtopus X.Y.Z could not be
fetched"* on every machine that has no `jq` — which is the ordinary fresh
box — for a release whose notes were sitting in the reply it had just
downloaded. It called `jq` directly instead of `mux_json`, so the bundled
JSON reader never got a look in.

Two things went with it:

- **That message is no longer cached.** It was written into
  `notes-X.Y.Z.md`, the file that exists so the notes are fetched once, so a
  laptop that happened to be offline for the first `What is in…` never saw
  that release's notes again however long it was online afterwards. A failed
  fetch is now the absence of an answer rather than a stored one, and the
  next try is a real one.
- **The `prerelease` channel works there too.** Its check also required `jq`
  and silently found no release at all without it, which reads on the
  dashboard as "checked just now, nothing new".

The bundled JSON reader learned the two things this needed: `.[0]`, and
input that is not one value per line — `api.github.com` pretty-prints, so
*not one line* of its reply parsed and the whole body came out empty. It
still refuses a slice, and indexing an object with a number is still an
error rather than a guess.

## The header says when a release is out

The deck header now carries `v<running> (v<new> available)` in yellow beside
the version, and `(v<new> downloaded)` once `download` mode has fetched it.
The version and the fact that it is behind were two facts at opposite ends
of the screen; the question occurs while reading the first one. Nothing is
drawn on a day when there is nothing out.
