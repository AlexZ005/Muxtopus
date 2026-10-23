---
title: A PC as a second host
parent: Scheduled windows
nav_order: 3
---
{% raw %}
# A PC as a second host

A [remote e2e slot](remote-e2e.md) moves only the browser to another machine. A **pc host** takes more: a Linux machine you reach by ssh (on Windows, a WSL2 distro of its own) that runs **whole e2e runs**, the tree, its `node_modules`, the dev server, the test and the browser, in a **pc slot**.

```
this machine                                  the pc host (a WSL2 distro, or any Linux box)
------------                                  ---------------------------------------------
e2e-slot -- env APP_URL=https://app:5487/ node tests/e2e/x.test.cjs
  slot C is pc ----- ssh (one control connection) -----> ~/.cache/muxtopus-pc/bin/e2e-pc-remote.sh
   1 rsync the tree, and inputs the command names  --->   the same paths: $HOME/code/proj/...
   2                                                      node_modules from a cache, by lockfile hash
   3                                                      lane-dev: the dev server on :5487 there
   4 output streamed back  <-----------------------------  node tests/e2e/x.test.cjs  (+ Chromium)
   5 new files copied back to the same paths  <---------  evidence, screenshots, /tmp files
```

## Why

Measured on a Steam Deck (WiFi) against a desktop PC: a remote slot's test still makes every `page.evaluate` and locator call across the network, so suites of many small round trips got **slower** remotely (lock-settings, 359 checks: 247 s remote, 210 s local), and the test's `node` and the dev server still used the small machine's memory. A pc slot keeps all of that on the far machine, so only the output comes back. The [numbers](#what-it-buys) are below.

## Hosts are named, and named locally

Every machine muxtopus may use is a section of `~/.config/muxtopus/hosts.conf`. That file is never part of the repository, and nothing in the repository holds an address. Every other setting names the section:

```ini
# ~/.config/muxtopus/hosts.conf
[pc]
ssh = alice@192.0.2.10      # anything ssh takes: user@host, or a ~/.ssh/config alias
port = 22022                # optional
key = ~/.ssh/muxtopus-pc    # optional (IdentitiesOnly when given)
e2e_slots = 2               # pc slots this machine sends there (default 1)
gpu = auto                  # auto | d3d12 | cpu  (see "The GPU")
```

`MUXTOPUS_HOSTS` moves the file. `ssh` is required. The rest have defaults.

## Turning pc slots on

```bash
# ~/.config/muxtopus/config
MUXTOPUS_E2E_PC=pc            # the host's e2e_slots slots
MUXTOPUS_E2E_PC=pc:2,gpu-box  # two on pc, gpu-box's own count
```

pc slots are lettered after the local and remote ones. With `MUXTOPUS_E2E_PREFER=remote` (the default) a free pc slot is tried **first**, then a remote one, then a local one, since a pc run leaves the least on this machine. `E2E_PC` in the environment replaces the list for one run, and `E2E_PC=` turns it off.

- `--local` never takes a pc slot. `--exclusive` holds the local and remote slots, but not the pc ones, because no part of a pc run is on this machine to disturb a timing run.
- A host that does not answer ssh is skipped, and asked again a minute later. The run takes another slot.
- If the host cannot take **this** run, nothing starts there and the run takes another slot, with a line saying why. That happens when the tree is a checkout of the host's own, when the dev server's port is taken there, or when the account there has another `HOME`.
- Ctrl-C, or a `timeout` around `e2e-slot`, stops the run on the far side too. ssh's stdin is the run's lifeline: when it closes, the far side ends the run's whole process group.
- Each run ends with one line of timings: `pc run on pc: rc 0; mirror 0.6s, deps 0.0s, server 0.2s, run 6.6s, back 0.1s (0 files), all 8.5s`.

## What changes for a test, and what does not

The command is run **as given**, in the same folder, and the same paths mean the same files. That holds because the account on the pc host has **the same `HOME`** as this one: the same user name, so `/home/alice` on both. The run refuses a host where `HOME` differs. With the same `HOME`, no argument, environment value or test default (`process.env.OUT || '/tmp'`) has to be rewritten.

**What is sent before the run:**

- **The tree**: the git top level of the run's folder, or else the nearest folder with a `package.json`. It is mirrored with `rsync --delete`, without `node_modules` or `.git`. The first sync of a 9,000-file tree took 20 s over WiFi, and later ones take under a second.
- **Inputs the command names.** An absolute path under `HOME` or `/tmp` in an argument or an environment value is mirrored if it exists here: a `MODULES_REPO`, a scene zip, an evidence folder. Environment values that describe this machine are not mirrored: `*_HOME`, `*_PATH`, a venv, anything under `~/.local`, `~/.cache` or `~/.config`. Nor is a folder in `HOME`'s first two levels. **`E2E_PC_INPUTS="path path"`** names more inputs, for paths that only a script the command runs knows about (a battery's `env.sh`, and the repos it points at). An input folder with a `package-lock.json`, and `node_modules` here, gets its own `node_modules` there.
- **`node_modules`**, rebuilt from the lockfile: `npm ci` runs once per lockfile hash (and `node` version), and every later tree with the same lockfile gets a hard-linked copy in about a second. It runs only for lockfiles whose folder has `node_modules` here. There is never a `--legacy-peer-deps`.
- **The dev server**, when the run needs one. That means `--dev DIR PORT`, or the port of `APP_URL` when its host is this machine (`localhost`, or a name `/etc/hosts` points at a loopback address). It is started on **the same port** there with `lane-dev`, from the same folder and with the same command as this machine's `lane-dev` server on that port, if there is one. Otherwise the tree's `npm run dev`. One request warms it up, because vite's first page load optimises dependencies (20 s measured). After the run it is left to `lane-dev`'s idle timer, which keeps it warm for the next run. `--dev` stops it after the run, as it does here.

**The environment** goes with it, except names that describe this machine or session, or are credentials:

| not sent | |
|---|---|
| this machine and session | `PATH HOME USER LOGNAME SHELL PWD OLDPWD SHLVL TERM* COLORTERM TMPDIR LANG LANGUAGE LC_* TMUX* SSH_* DISPLAY WAYLAND_* XAUTHORITY XDG_* DBUS_* LD_* MAIL HOSTNAME EDITOR VISUAL PAGER LS_COLORS LESS* PS1-4 PROMPT_COMMAND HIST*`, desktop and session variables (`DESKTOP_SESSION GTK_* QT_* KDE_* GNOME_* SDL_* STEAM* PULSE_* PIPEWIRE_* XCURSOR_* MOZ_* KONSOLE_* VTE_* WINDOWID INVOCATION_ID JOURNAL_STREAM SYSTEMD_* MANAGERPID MEMORY_PRESSURE_* DEBUGINFOD_* GPG_* SUDO_* OTEL_*`) |
| tools of this machine | `NODE_OPTIONS PLAYWRIGHT_BROWSERS_PATH PW_REMOTE_* npm_* NVM_*` |
| this machine's muxtopus and Claude | `CLAUDE* ANTHROPIC_* MUXTOPUS_* WATCHDOG_*`, and the slot choice made here: `E2E_SLOTS E2E_SLOT_LOCK E2E_PREFER E2E_REMOTE E2E_PC` (the host's own `e2e-slot` uses its own) |
| credentials | `GH_* GITHUB_* AWS_*`, and any name containing `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `API_KEY`, `PRIVATE_KEY` or `CREDENTIAL` |

`E2E_PC_ENV="NAME OTHER"` sends those names anyway. `LANG` is `C.UTF-8` there. The command also sees `E2E_SLOT`, `E2E_SLOT_PC=<host>` and an empty `E2E_SLOT_REMOTE`. Its stdin is not forwarded.

**What comes back:** every file the run wrote, copied to the same path here with `rsync --update`, so a file changed here in the meantime wins. That covers files newer than the run's start in the tree, in every path the command named, and in `/tmp` (two levels deep, the user's own files). `node_modules`, `.git`, `.svelte-kit` and `.vite` stay behind.

**What stays there:** the mirror, `node_modules` and the warm dev server, ready for the next run. A `node_modules` cache nobody used for two weeks is removed.

**The host's own checkouts are safe.** A mirror is written only where nothing is, or where a mirror already is (a `.muxtopus-mirror` marker at its top). A folder of the host's own, such as a lane that lives there or a git checkout, is never synced over. A run whose tree would be is refused, and an input that would be is left alone, so the run sees the host's copy and says so.

**When muxtopus is installed on the host**, the run goes through that machine's own `e2e-slot --local`. Runs sent from here and lanes that live there then share that machine's slots, so neither side assumes all of its capacity.

### The GPU

Tests that ask for a GPU pass ANGLE flags chosen for the machine they were written on. On Linux that is `--use-angle=vulkan`, and in WSL2 there is no Vulkan driver for the Windows GPU, so Chromium silently gets Mesa's llvmpipe, a CPU rasteriser. WSL does have Mesa's d3d12 driver over `/dev/dxg`, reached through EGL. Measured in the distro, as reported by `WEBGL_debug_renderer_info`:

| launch | renderer |
|---|---|
| no GPU flags | `ANGLE (Google, Vulkan 1.3.0 (SwiftShader ...))` |
| `--use-angle=vulkan` | `ANGLE (Mesa, Vulkan 1.4 (llvmpipe ...))` |
| `--use-angle=gl-egl`, `GALLIUM_DRIVER=d3d12` | `ANGLE (Microsoft Corporation, D3D12 (<the card>), OpenGL ES 3.1)` |

So with `gpu = auto` and a host that has `/dev/dxg` and the d3d12 driver, `lib/pw-pc-shim.cjs` turns a launch's `--use-angle=vulkan` into `gl-egl`, and the run gets `GALLIUM_DRIVER=d3d12`. A launch that asks for no GPU keeps SwiftShader, as it would anywhere else. On one GPU suite (animated-models) d3d12 took 36–40 s green, and llvmpipe 46 s, then 76 s red. `gpu = cpu` turns the mapping off. It is still not this machine's GPU, so **frame-rate and timing gates belong on `--local` or `--exclusive`**.

## What it buys

Measured 2026-10-23: a Steam Deck (WiFi, other lanes running) against a desktop PC (i9-13900K, RTX 4090, wired) in use by its owner at the same time, with a WSL2 distro of 24 threads and 32 GB. The same seven core suites and snapshot as the [remote slot's measurement](remote-e2e.md#what-it-buys), three repeats each, every suite its own `e2e-slot` call. The times are the whole call (probe, mirror, deps, server, run, copy-back), medians in seconds:

| suite | local | remote | pc | pc green |
|---|---:|---:|---:|---:|
| llms-txt | 10 | 13 | 11 | 3/3 |
| union-53 | 53 | 30 | 30 | 3/3 |
| lock-ux | 109 | 66 | 62 | 3/3 |
| invite-links | 227 | 132 | 122 | 3/3 |
| lock-settings | 210 | 247 | 217 | 3/3 |
| particles-fx | 64 | 41 | 43 | 3/3 |
| mesh-knife | 118 | 62 | 60 | 3/3 |
| **all** | **791** | **591** | **544** | 21/21 |

- **Memory.** On the Deck, a pc run (e2e-slot and ssh) peaked at 18–26 MB, against 1.4–2.9 GB for a local run and 0.27–0.35 GB for a remote one. The dev server is not on the Deck either.
- **Speed.** 1.45× local and 1.09× remote overall. The suites a remote slot made slower got their time back: lock-settings went from 247 s remote to 217 s (local 210 s). Its time is mostly its own waits, so no machine makes it much faster.
- **Overhead**, from each run's timing line, on a warm tree: mirror 0.9–2.5 s, deps 0.0–0.2 s, server 0.1–0.3 s, copy-back under 0.5 s. A tree's first run also pays the first sync (20 s for 9,000 files), one `npm ci` (8 s) and vite's first page load (20 s).
- These seven suites launch without GPU flags, so every kind of slot renders them on SwiftShader (the CPU).

## Setting up a pc host

**Windows.** Run this as an administrator, with `lib/pc-host-setup.ps1` and `lib/pc-host-setup.sh` side by side, and the public half of a key made for it on the test machine (`ssh-keygen -t ed25519 -f ~/.ssh/muxtopus-pc`):

```powershell
powershell -ExecutionPolicy Bypass -File pc-host-setup.ps1 -Root C:\muxtopus-wsl -Distro muxtopus `
    -User alice -PublicKey "ssh-ed25519 AAAA... alice@testbox" -Allow 198.51.100.7 `
    -LoopbackNames app.example -Playwright 1.62.1,1.63.0
```

It imports a **new** distro from Ubuntu 24.04's WSL root filesystem into `-Root\<Distro>`, so put `-Root` on the disk with room. Your other distros are not touched. Inside it, the script creates `-User`, which must be the test machine's user, with passwordless sudo inside the distro (Playwright's `install-deps` is apt). It sets up sshd on `-Port` (22022), key only, that user only. It installs `node` (`-Node`, from nodejs.org, into `~/.local`) and Chromium for each `-Playwright` version. Each `-LoopbackNames` name is mapped to the distro itself, because an `APP_URL` on `app.example` must mean the distro's own server there. Its Windows drives and Windows programs are switched off (`automount` and `interop` in `/etc/wsl.conf`), because nothing a lane runs needs them. Outside the distro the script creates three things:

- a scheduled task `<Distro>-keepalive` (at startup, logged on or not, S4U, no stored password). WSL stops a distro nothing is attached to, and sshd with it.
- a **port proxy** from this PC's address and `-Port` to `127.0.0.1:-Port`. WSL2's default NAT networking forwards a distro's port to the PC's localhost only. The alternative, `networkingMode=mirrored` in `.wslconfig`, would also work, but it is one setting for every distro on the PC, Docker's included, and applying it restarts them all.
- a firewall rule: `-Port`, TCP, from `-Allow` only.

`-Uninstall` removes those three and keeps the distro. `-Uninstall -RemoveDistro` also unregisters it, which **deletes its disk**.

**Memory and processors** are one setting for the whole WSL VM, in `%UserProfile%\.wslconfig`, and applying it needs `wsl --shutdown`, which stops **every** distro. The script does not do it, because that is the PC owner's call. An example, with swap kept off the system disk:

```ini
[wsl2]
memory=32GB
processors=24
swap=16GB
swapFile=E:\\muxtopus-wsl\\swap.vhdx
```

**Linux.** Any box with sshd works: run `pc-host-setup.sh root <user> <port> "<key>" [names]` as root, then `pc-host-setup.sh user [node] [playwright...]` as the user, and firewall the port to the test machine.

**Then, on the test machine**, add the host's section to `hosts.conf`, check it with `ssh` once (accept the host key), and set `MUXTOPUS_E2E_PC`.

## Lanes on the pc host

A pc host can also **run lanes**: windows of their own in its own tmux, under muxtopus installed there. This machine stays the **one scheduler**: its schedules, its budget guard, its dependency checks and its reports decide. The pc host only opens windows when told to and keeps them running.

```ini
# hosts.conf: the same section, one more key
[pc]
ssh = alice@192.0.2.10
lanes = 4                   # how many lanes it may run at once
```

**Which entries go there.** An entry's `host:` header (`host: pc`, or `host: local` to keep it here), and otherwise `MUXTOPUS_LANE_HOST`:

```bash
# ~/.config/muxtopus/config
MUXTOPUS_LANE_HOST=pc        # every new lane on pc
MUXTOPUS_LANE_HOST=pc:held   # on pc only while this machine's memory guard holds launches
```

**What happens when one is due.** This watchdog does what it always does (the time, `after:`, the budget), except that this machine's memory guard does not hold an entry for another host. That host's `lanes` and whether it answers do. Then it **hands the entry over**. A copy goes into the host's schedules folder, due now, with this machine's slug pinned and without `host:` and `after:`, which were judged here. The templates folder goes with it. The host's watchdog is woken, and its own launcher opens the window with the same code, flags, identity, trust answer and footer as here. The entry here is marked `launched` with `host: pc`, and the tree gets the lane's row under its parent. An entry the far side fails to launch is marked `error` here.

**What this machine sees, every pass**, for each host that answers:

- its `status.tsv` and `tree.tsv`, into `~/.local/state/claude-watchdog/hosts/<host>/`. The dashboard's claude table lists those sessions with a **HOST** column, which appears only while there are any. `claude-watchdog.sh --status` appends a `HOST` column and lists every host's rows after this machine's. `--health` names each host, its lanes and the age of its status, and its rows have a `HOST` column. A host's pane is written `<host>:%N` wherever this machine keeps one, so nothing here types into the wrong server. A status older than three passes is a host asleep, and its rows are neither drawn nor judged.
- **reports to the parent** across hosts: a pc lane that stalls, waits at a prompt, sticks at a limit or finishes is reported to its parent wherever the parent is, as `stalled 57-x (pc claude:4): …`. A nudge (`WATCHDOG_NUDGE_STALLED`) or a close (`WATCHDOG_CLOSE_FINISHED`) is typed into the pc's tmux over ssh. Set `WATCHDOG_REPORT=off` on the pc host, so its own watchdog does not report as well.
- **the handover folder**, kept the same on both machines (`muxhosts.py sync`). Each file is compared with a manifest of the last sync, and whichever side changed wins. A new or edited file is copied, and a removed one is removed, so `handover.sh done` on either machine moves the file into `done/` on both. Both sides changed: the newer wins. Nothing is ever deleted without a manifest. A mount was the alternative, but the pc would have to log into this machine with a key that opens the whole account, and every lane there would hang whenever this machine slept.

On the dashboard, a pc row's actions (open, rename, close, send, the opt-outs) are refused with a line that says where the window is. Each of them drives this machine's tmux or this watchdog's files.

**Setting it up**, after the pc slot setup above: in the distro, install muxtopus at the **same path** as here, with the same account. The state, schedules and handover folders are then at the same places relative to `HOME`. Then log Claude Code in there (`claude`, then the URL it prints). If lanes run with `permission-mode: bypassPermissions`, accept that mode there once as well: start `claude --permission-mode bypassPermissions` and choose `Yes, I accept`, which writes `skipDangerousModePermissionPrompt` to `~/.claude/settings.json`. The watchdog never answers that warning itself. A launch that meets it is marked `error`, with a log line that says so, and the window is left on the warning. Then start `muxtopus -d` so its tmux session exists, arm its watchdog, and set `WATCHDOG_REPORT=off` in its config. A lane there runs its e2e through that machine's own `e2e-slot`, on local slots of its own. Clone the lanes' repositories there as you would here. Its git credentials are its own.

## Token use

The account-wide session and week figures are one reading for the whole account, wherever its lanes run. Which lane spent the tokens is in each machine's own ledger (`muxtopus stats`), and the watchdog brings each lane host's ledger back with its status. Every five minutes it writes `~/.local/state/claude-watchdog/tokens-by-lane.jsonl`, one line per day, host and lane:

```json
{"date": "2026-10-23", "host": "pc", "slug": "57-clips", "roadmap": "57", "spent": 1234567, "cached": 98765432}
```

`spent` is SPENT (input, cache writes and output, the parts billed at or above full rate) and `cached` is CACHED (cache reads), summed over models and subagents, from the ledger, which counts each message once. The per-session counters in `status.tsv` count a resumed session's copied messages again. `slug` is `-` for a session that is no lane, and `roadmap` is the slug's leading number. The file is rewritten whole, so today's lines are the day so far and earlier days are final. `MUXTOPUS_HOST_NAME` names this machine in it, and its hostname is the default.

## Security

- **ssh, key only.** sshd in the distro takes one user's public key: no passwords, no root. The port is firewalled to the one test machine (`-Allow`), and a port proxy is the only way in from the LAN.
- **No secrets cross unless named.** Credentials in the environment (the table above) are not sent. `E2E_PC_ENV` is the explicit way to send one, and it then sits in the run's environment file there, mode 600, removed when the run ends.
- **No secrets in the repository.** Addresses, user names and key paths live in `hosts.conf` on the machine that uses them. `tests/test_no_private.py` fails CI on a LAN address, a MAC address or a home folder in any tracked file.
- **The distro cannot reach Windows.** Drives are not mounted and Windows programs cannot be started from it. The GPU is reached through `/dev/dxg` and the driver folder WSL provides, not through a drive.
- **The user has passwordless sudo inside the distro.** That is the price of `playwright install-deps`. Anyone holding the ssh key is root in the distro, so guard the key like the machine.
- A pc run writes only under `HOME` and `/tmp` there, and only where nothing of the host's own is (the marker rule above). It copies back only under `HOME` and `/tmp` here.
- **Only this machine opens connections.** The pc host has no key to this machine. The handover sync, the status pull and every report go out from here over the one ssh connection.
- **Credentials for lanes there are that machine's.** Claude Code logs in there with its own login. Git credentials are given to it separately, and muxtopus copies none.
{% endraw %}
