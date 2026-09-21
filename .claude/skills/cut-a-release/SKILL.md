---
name: cut-a-release
description: Cut and publish a muxtopus release — assemble the changelog from changes/ fragments, bump VERSION, tag, build dist/ and publish the GitHub release with its checks. Use when asked to release, tag or publish a version.
---

# Cut a release

The full prose is `docs/releasing.md`. This is the running order, with the
traps that are easy to hit.

## 1. The release lane

A release is a lane like any other (see the `start-a-lane` skill):

```bash
git worktree add -b release/vX.Y.Z ../wt/relXYZ origin/main
```

## 2. Assemble the entry

Put `## vX.Y.Z — YYYY-MM-DD` at the top of `CHANGELOG.md`, above the previous
one, with every `changes/*.md` fragment that landed since the last tag
underneath. Group by area and demote each fragment's `##` to `####`.

Open with a short paragraph saying **why the number is the number** — semver
over what a user touches: the `muxtopus` command line, the schedule-entry
headers, `handover.sh`'s commands, and the files under `~/.config/muxtopus`
and `MUXTOPUS_HOME`. Renaming or moving any of those is a major; a new key,
header or setting is a minor; a fix is a patch.

Then `git rm` each fragment you used. `changes/README.md` stays.

## 3. Bump VERSION, and nowhere else

```bash
echo "X.Y.Z" > VERSION
.venv/bin/python tests/test_version.py
```

**The number must not appear in any other file** — a comment or a fragment
counts. If the test names `muxtopus --version prints ...` as failing while
`VERSION` is right, check whether `MUXTOPUS_DIR` in your environment points at
a *different* checkout; that is an artifact of your shell, not the release.
Confirm with:

```bash
env -i HOME=/tmp/x PATH=/usr/bin:/bin bash -c 'cd '"$PWD"' && ./muxtopus -V'
```

## 4. Trial build, then merge

```bash
./release.sh build HEAD     # dist/ from the commit
./release.sh notes          # exactly what the release page will show
```

Open the PR, merge once CI is green, then `git pull --ff-only` in main.

## 5. Tag and publish, from main

```bash
v=$(cat VERSION)
git tag -a "v$v" -m "muxtopus $v" && git push origin "v$v"
./release.sh build                        # from the TAG, not the working tree
./release.sh notes > /tmp/notes.md
gh release create "v$v" --title "muxtopus $v" --notes-file /tmp/notes.md \
  dist/muxtopus-$v.tar.gz dist/get.sh dist/SHA256SUMS
```

## 6. Check it before announcing it

Not a draft, three assets, and the published checksums match:

```bash
gh release view "v$v" --json isDraft,assets
# download all three into a scratch dir, then:
sha256sum -c SHA256SUMS
```

Then the one-line installer, in a clean container, against the published URL.
**Leave `jq` out of the container deliberately** — it is optional, and this is
the cheapest proof that the fallback reader still works:

```bash
podman run --rm archlinux bash -c '
  pacman -Sy --noconfirm tmux git python curl >/dev/null
  useradd -m t && su - t -c "curl -fsSL https://github.com/AlexZ005/Muxtopus/releases/download/v'"$v"'/get.sh | bash -s -- --no-watchdog && ~/.local/bin/muxtopus -V"'
```

If you also probe `mux_json` inside the container, write the probe to a file
and run it — nested shell quoting through `podman ... su -c "..."` will eat
your `$` and hand back empty output that looks exactly like a broken fallback.
