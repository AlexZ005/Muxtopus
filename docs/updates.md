---
title: Updates
nav_order: 11
---
{% raw %}
# New releases

muxtopus asks GitHub once a day whether there is a newer release, says so on the dashboard, and takes it when you say yes. Everything about that is a setting, including whether the question is asked at all.

```
esc ▸ Settings ▸ Updates ▸
muxtopus update              what is installed, what is out
muxtopus update --check      ask now, whatever the clock says
muxtopus update --apply      take it (it asks first; --yes does not)
muxtopus update --rollback   put back the tree the last update replaced
```

## What is sent, and what is not

One HTTPS request that follows `https://github.com/AlexZ005/Muxtopus/releases/latest` and reads the tag out of the URL it lands on. No token, no query string, no identifier, nothing about this machine, and no request at all when `MUXTOPUS_UPDATE_MODE=off`. Nothing is downloaded until you ask for it, and nothing is installed without the confirm row or `--yes`.

Two things do cost a second request, and both are asked for by a hand: `What is in X…`, which reads the release notes from the GitHub API, and the update itself, which downloads that release's installer and tarball.

The `prerelease` channel uses the API for the check as well — `releases/latest` skips prereleases by definition — which is 60 requests an hour without a token, against a check that runs once a day.

## The answer is shared, the switches are not

There is one installed tree. However many accounts run out of it, the check, its clock and its answer live in one place:

```
${XDG_STATE_HOME:-~/.local/state}/muxtopus-update/
    state              what the last check found (KEY=value)
    notes-X.Y.Z.md     release notes, fetched once and then kept
                       (a fetch that FAILS is not kept, so the next
                        try is a real one)
    update.log         every check, stage, install and rollback
    install-X.Y.Z.log  what the installer said
```

Every account's watchdog calls the check on every pass; all but the first return having read that file and asked nobody. The three settings are written to the shared `dashboard.conf` for the same reason, whichever account's dashboard you set them from — "check daily" cannot sensibly mean two different things on one machine. (A profile file can still narrow them by hand, as it can any key; the menu shows what that account actually reads.)

## Taking one

While a release is waiting, the deck header says so beside the version — `v<running> (v<new> available)`, in yellow, and `(v<new> downloaded)` once `download` mode has fetched it — and the key line at the foot of the main view carries the same in short. Both are absent on every other day.

The dashboard offers it under `esc` while there is one waiting, and in `Settings ▸ Updates` always:

| row | what it does |
|---|---|
| `Updates: <running> · <new> is out · checked 3h ago` | prints the full status, full screen |
| `Check now` | asks GitHub, ignoring the clock |
| `What is in <new>…` | that release's notes, full screen |
| `Update to <new> and reload` | a confirm, then the install |
| `Roll back to <previous>` | a confirm, then the move back |

Taking one does this, in order:

1. downloads that release's `get.sh` and its `SHA256SUMS`, and refuses to run the installer if the two disagree;
2. runs it, which downloads the tarball, checks it against the sha256 baked into `get.sh` at release time, unpacks it into `~/.local/lib/muxtopus` and runs its `install.sh`;
3. keeps the tree it replaced as `~/.local/lib/muxtopus.prev`;
4. sends every running watchdog a `--reload`, which is a SIGHUP it answers by re-execing itself onto the new code once the pass it is in has finished;
5. reloads the dashboard, exactly as `R` does.

**Your claude windows are not touched.** They are processes in tmux panes; nothing in this sequence signals them, and nothing about the tmux server changes. There is no "restart muxtopus to apply" because there is nothing that has to be restarted — the two things running muxtopus code reload themselves, and the work does not.

If an update is applied from a terminal rather than from the menu, a dashboard that is already running is the one thing still on the old code. It notices, and its header says `v<running> → <new> installed, press R` until you do.

## What it refuses

- **A git checkout.** A checkout runs in place and `git pull` is its upgrade; overwriting one with a tarball would throw away whatever was being worked on in it. The marker is `.muxtopus-release`, which `get.sh` writes and a checkout never has.
- **An installer whose sha256 is not the one published beside it.** Nothing is unpacked and nothing is run.
- **A directory it did not install into**, which is `get.sh`'s own rule and still applies.

## What the checksums do and do not prove

`get.sh` carries the sha256 of its release's tarball, computed from the tag when the release was built, and refuses anything else — so a tarball swapped under a published release, a moved tag or a truncated download is an error rather than an install. The updater adds one link to that chain: `get.sh` itself is checked against the `SHA256SUMS` published beside it before it is run.

Both files come over TLS from the same release, so this catches corruption and substitution *of one file*, not a GitHub account that has been taken over. Signed releases would be the answer to that, and there are none yet; this says so rather than implying more. Every release is reproducible — `./release.sh build vX.Y.Z` on a clone gives the same bytes — so a sum can always be checked against one built from the tag by a third party.

## Rolling back

The update kept the tree it replaced, so going back is a move and a reload rather than a hunt for an old tag on a machine whose dashboard has stopped working:

```bash
muxtopus update --rollback
```

It swaps the two trees, carries the dashboard's `.venv` back with the path, re-runs that older tree's `install.sh`, and reloads the watchdogs. The tree it just left becomes the one to roll *forward* to, so this is undoable exactly once in each direction. Only one generation is kept: two is a hoard, not insurance.

## The settings

All three are in `esc ▸ Settings ▸ Updates`, and all three are shared by every account.

| key | default | |
|---|---|---|
| `MUXTOPUS_UPDATE_MODE` | `notify` | `notify`: check and say so, download nothing. `download`: also fetch and verify it as soon as it is seen, so applying it is local. `off`: never check, and never reach the network for this |
| `MUXTOPUS_UPDATE_EVERY` | `24` | hours between checks |
| `MUXTOPUS_UPDATE_CHANNEL` | `stable` | `prerelease` also takes release candidates, for a machine you dogfood your own tags on |

And one more, in `esc ▸ Settings ▸ Notifications`:

| key | default | |
|---|---|---|
| `MUXTOPUS_NOTIFY_UPDATE` | `off` | tell the phone when a release is out, with the headline of its notes |

That one is told **once per version, ever** — the fingerprint is the version number, so the ledger that stops a waiting prompt being announced twice a minute is the same one that stops "<new> is out" arriving every day until it is installed. It never sends a "cleared" message either: installing a release is not an event a phone wants to hear about twice. It is off by default because it is news, not trouble, which is the same reason the budget bands are.

## Proving it

`tests/test_update.sh` builds two releases from this checkout — the one under test and a fabricated newer one — serves them out of a directory with `file://` URLs, installs the first, updates to the second, rolls back, rolls forward again, and checks every refusal. A self-updater that has never updated anything is the one part of this repository that cannot be proved by reading it.
{% endraw %}
