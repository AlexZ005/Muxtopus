---
title: Cutting a release
parent: For contributors
nav_order: 2
---
{% raw %}
# Cutting a release

A release is a tag on `main`, a `CHANGELOG.md` entry, and a GitHub Release carrying three files: the source tarball, `get.sh`, and `SHA256SUMS`. `release.sh` builds the files; everything else is `git` and `gh`.

## One number, in one place

`VERSION` holds it. The dashboard's header, the bash renderer, `muxtopus --version`, the tarball's name and `get.sh` all read that file, and `tests/test_version.py` fails if the number turns up anywhere else, apart from `CHANGELOG.md`, which is a history of numbers rather than a source of one. It also checks that the newest `CHANGELOG.md` entry is the number in `VERSION`.

The number is [semver](https://semver.org/) over what a user touches: the `muxtopus` command line, the schedule-entry headers and placeholders, `handover.sh`'s commands, and the files and formats under `~/.config/muxtopus` and `MUXTOPUS_HOME`. Renaming or moving any of those is a major. A new key, header or setting is a minor. A fix is a patch.

## The steps

On a branch, as a pull request like any other lane:

1. **Write the entry.** Add `## vX.Y.Z — YYYY-MM-DD` at the top of [`CHANGELOG.md`](https://github.com/AlexZ005/Muxtopus/blob/main/CHANGELOG.md), with every `changes/*.md` fragment that landed since the last tag under it. Group them by area and demote each fragment's `##` to `####`. Say why the number is the number.
2. **Consume the fragments.** `git rm` each fragment you used. `changes/README.md` stays.
3. **Bump `VERSION`** to the same number, and nowhere else.
4. **Try the build.** `./release.sh build HEAD` builds `dist/` from the commit, and `./release.sh notes` prints the entry exactly as the release page will show it.
5. **Merge the PR** once CI is green.

Then, from `main`:

```bash
git checkout main && git pull
v=$(cat VERSION)
git tag -a "v$v" -m "muxtopus $v"
git push origin "v$v"
./release.sh build                      # builds dist/ from the tag, not the working tree
./release.sh notes > /tmp/notes.md
gh release create "v$v" --title "muxtopus $v" --notes-file /tmp/notes.md \
  dist/muxtopus-$v.tar.gz dist/get.sh dist/SHA256SUMS
```

**Check it before announcing it.** The release must not be a draft (`gh release view "v$v" --json isDraft`). Its three assets must download. And the one-line installer must work in a clean container, against the published URL:

```bash
podman run --rm -it archlinux bash -c '
  pacman -Sy --noconfirm tmux git jq python curl >/dev/null
  useradd -m t && su - t -c "curl -fsSL https://github.com/AlexZ005/Muxtopus/releases/download/v'"$v"'/get.sh | bash -s -- --no-watchdog && ~/.local/bin/muxtopus -V"'
```

## What `get.sh` is, and why it pins

`get.sh` is generated for each release from `packaging/get.sh.in`, and two values are stamped into it: that release's version, and its tarball's sha256. It installs that release and nothing else. Once a release exists, `get.sh` cannot drift onto `main` or onto a later tag. A tarball swapped under it, or a tag moved, fails the checksum and nothing gets installed.

`releases/latest/download/get.sh` is a stable URL for the newest release's `get.sh`. It follows new releases, but whichever `get.sh` it serves still installs only its own tag.

The tarball is `git archive` of the tag, compressed with `gzip -n`, so it is reproducible. Anybody can run `./release.sh build vX.Y.Z` on a clone and should get the same sha256 as the one on the release page.

## Why only a tarball and an installer

Two other formats were considered for the first release and left out. Each can be revisited.

- **A `pipx` package.** The Python half is a package, but muxtopus is mostly bash: `muxtopus` itself, the watchdog, `handover.sh`, the notifier. The watchdog's systemd unit points at a script path. Under pipx that path would be inside a venv that pipx rebuilds whenever Python changes. That is the exact breakage the design avoids by keeping the dashboard's venv beside the code and falling back to bash when it breaks. A pipx package would carry the shell scripts as package data and run them from site-packages. It would work, but it would be a second layout to support for no gain over `get.sh`.
- **An AUR `PKGBUILD`.** This was built on a Steam Deck, and SteamOS's root filesystem is read-only and replaced on every OS update. A pacman package there needs the read-only bit turned off, and the next update wipes it. `get.sh` writes only to `$HOME` and survives updates. On ordinary Arch a PKGBUILD would be reasonable: install the tree to `/usr/share/muxtopus` and let each user run its `install.sh`. But it would need an AUR account to publish and a maintainer to keep it current. It is worth doing once someone other than the author asks for it.
{% endraw %}
