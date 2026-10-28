---
title: Remote e2e slots
parent: Scheduled windows
nav_order: 2
---
{% raw %}
# Remote e2e slots

`e2e-slot` hands out machine-wide Playwright slots, and on a small machine the browsers are what run out first. Three local slots on a 29 GB Steam Deck kept it at 19 GB of RAM and 11 GB of swap, so the slot count could not grow there. A **remote slot** moves only the browser to another machine. The test, its `node` and the lane's dev server stay where they are, so no test changes and no checkout on the other machine.

```
this machine                                     the other machine (say a desktop PC)
-------------                                    ------------------------------------
e2e-slot --  node test.cjs                       pw-remote-server.cjs   :39001
   NODE_OPTIONS=--require pw-remote-shim.cjs        +- playwright 1.62.1 run-server (127.0.0.1)
   chromium.launch()  ---- websocket ---------->     +- playwright 1.63.0 run-server (127.0.0.1)
                                                          +- Chromium
   vite on localhost:5466  <---- tunnel ---------------- page.goto('https://localhost:5466/')
```

A remote slot leaves the test's `node` and the dev server here, and every page call crosses the network. For suites of many small calls, and to keep the dev server off this machine too, a [pc slot](pc-host.md) moves the whole run.

## Turning it on

```bash
# ~/.config/muxtopus/config
MUXTOPUS_E2E_REMOTE=192.0.2.10:39001                       # one remote slot
MUXTOPUS_E2E_REMOTE=192.0.2.10:39001,192.0.2.10:39001  # two on the same server
MUXTOPUS_E2E_PREFER=remote                                     # (the default) try a remote slot first
```

Each entry is one slot, lettered after the local ones: with `MUXTOPUS_E2E_SLOTS=3`, the first remote slot is `D`. The command sees `E2E_SLOT=D` and `E2E_SLOT_REMOTE=host:port`. `E2E_REMOTE` in the environment replaces the list for one run, and `E2E_REMOTE=` turns it off.

- **A host that does not answer is skipped.** Before handing a remote slot out, `e2e-slot` asks `GET /json` (3 s, twice). A sleeping PC is skipped for a minute, and the run takes a local slot exactly as before. It says so once: `remote slot … does not answer; skipping it`.
- **`--local`** never takes a remote slot. Use it for anything that must not leave the machine. **`--exclusive` implies it** and still holds the remote slots, because a remote run's node and dev server are on this machine, and a timing run needs this machine quiet.
- **`MUXTOPUS_E2E_PREFER=local`** fills the local slots first and uses the remote ones as overflow.

## What changes for a test, and what does not

Nothing in the lane changes. On a remote slot, `e2e-slot` puts `lib/pw-remote-shim.cjs` in `NODE_OPTIONS`. The first time the test loads Playwright, `chromium.launch(options)` becomes `chromium.connect()` to the slot's server, with the same options. The test gets an ordinary `Browser`.

- **The dev server is reached through the connection.** `exposeNetwork` tunnels `<loopback>` and every name `/etc/hosts` points at this machine (`127.0.0.1 theprototype.app`) back here. `https://localhost:5466/` therefore means this machine's vite, not the PC's. Such a name answers both `127.0.0.1` and `::1`, because vite listens on `[::1]` only. `PW_REMOTE_EXPOSE` replaces the list.
- **Args go through; this machine's paths do not.** `executablePath`, `env`, `downloadsPath`, `tracesDir` and the signal handlers are dropped. An `executablePath` is said on stderr, since the PC uses its own Chromium.
- **`download.path()` works.** On a connected browser it throws ("Path is not available when connecting remotely"). The shim saves the download locally with `saveAs()` and returns that path.
- **Some launches stay local**, with one line on stderr: `launchPersistentContext` (a profile directory on this disk), `headless: false`, firefox and webkit.
- **If the server stops answering** after the slot was handed out, the browser is launched here instead: `remote browser at … failed (…); launching here instead`. `PW_REMOTE_FALLBACK=fail` makes it an error.
- **Platform-dependent code sees this machine.** `process.platform` in the test is `linux` even though the browser runs on Windows, so a helper that picks an ANGLE backend by platform picks Linux's (`vulkan`), and Windows runs it. The GPU behind WebGL is the remote machine's. Measured on the first PC: without GPU flags both sides render on SwiftShader (the CPU), and with them the remote browser got `ANGLE (NVIDIA, Vulkan 1.4.351 (NVIDIA GeForce RTX 4090))` from the scheduled task's non-interactive session, against the Deck's `AMD Radeon 890M`. **Frame-rate and timing gates therefore belong on `--local` or `--exclusive`**, where the numbers mean this machine.  On a Windows host, WebGPU needs [the d3d11 setting](#the-gpu-on-a-windows-host).

## The GPU on a Windows host

A test picks its GPU flags from the platform of the machine its `node` runs on, so a Linux test machine asks for `--use-gl=angle --use-angle=vulkan --enable-features=Vulkan --enable-gpu --ignore-gpu-blocklist`, plus `--enable-unsafe-webgpu` for the WebGPU suites. Measured on a Windows desktop with an RTX 4090 as the browser host:

| flags the browser got | WebGL | WebGPU (`navigator.gpu.requestAdapter()`) |
|---|---|---|
| none | SwiftShader | null |
| the Linux ones (`--use-angle=vulkan`) | ANGLE Vulkan on the RTX 4090 | **null** |
| `--use-angle=d3d11 --enable-unsafe-webgpu --ignore-gpu-blocklist --enable-gpu` | D3D11 on the RTX 4090 | nvidia / lovelace |
| channel `chromium` (new headless) | none at all | — |

So with the Linux flags the WebGPU suites fail or fall back. **`MUXTOPUS_E2E_REMOTE_GPU=d3d11`** fixes it: `e2e-slot` passes it to a remote run as `PW_REMOTE_GPU=d3d11`, and the shim sends `--use-angle=d3d11` instead of `--use-angle=vulkan`, drops `Vulkan` from `--enable-features` (and the switch, if nothing else is left in it) and keeps every other arg. It says so once on stderr: `pw-remote-shim: --use-angle=vulkan -> d3d11 on …`. `E2E_REMOTE_GPU=keep` or `d3d11` overrides it for one run.

- **A launch that asks for no GPU is not changed.** It gets SwiftShader on any host, as before.
- **A local fallback keeps Vulkan**, because then the browser runs on this machine after all.
- **A server running on Windows does the same mapping itself** (`pw-remote-server.cjs`, from this version on). Keep the setting anyway for a host whose server predates it: the client's mapping reaches it without touching that machine.

## What it buys

Measured 2026-10-23 on a Steam Deck (29 GB, WiFi) with three local slots busy, against a desktop PC (i9-13900K, RTX 4090, wired). Seven core suites, local slot and remote slot back to back, three repeats each, same snapshot and dev server:

- **Memory.** A local run's test tree peaked at 1.4–2.9 GB on the Deck (node and Chromium). A remote run's peaked at 0.27–0.35 GB (node alone). Each busy remote slot is about 1–2.5 GB the Deck keeps.
- **Speed.** The seven suites took 591 s remotely against 791 s locally (medians, 1.34×). The remote side wins where the browser does the work (render, layout, SwiftShader frames: 1.5–1.9×). It loses on chatty suites, whose many small `page.evaluate` and locator round trips each cross the network: lock-settings, with 359 checks, took 247 s against 210 s.
- **Results.** Every remote run was green. On the loaded Deck, three suites failed locally on starvation (a 30 s click timeout, a velocity read as 0, a button that never became clickable) that were green on the same commit earlier in the day.

## Setting up the other machine

The other machine needs Node and nothing else from you. `lib/pw-remote-server.cjs` is one file with no packages.

**Windows** (as an administrator, with `pw-remote-server.cjs` beside the script):

```powershell
powershell -ExecutionPolicy Bypass -File pw-remote-setup.ps1 -Root C:\muxtopus-e2e -Allow 198.51.100.7 -Versions 1.62.1,1.63.0
powershell -ExecutionPolicy Bypass -File pw-remote-setup.ps1 -Root C:\muxtopus-e2e -Uninstall
```

Everything goes in `-Root`: the server, `start-servers.ps1`, one `playwright-<version>\` per version with its Chromium in `browsers\`, and `logs\`. Outside it there are exactly two things: a firewall rule (the ports, TCP, from `-Allow` only) and a scheduled task. The task starts the server at boot, logged on or not (S4U, no stored password), with no time limit. `-Uninstall` removes all three.

**Linux** (any user; a systemd user service or a `tmux` window keeps it up):

```bash
mkdir -p ~/pw-remote && cd ~/pw-remote && cp /path/to/muxtopus/lib/pw-remote-server.cjs .
for v in 1.62.1 1.63.0; do
  npm install --prefix playwright-$v playwright@$v
  PLAYWRIGHT_BROWSERS_PATH=$PWD/playwright-$v/browsers playwright-$v/node_modules/.bin/playwright install --with-deps chromium
done
node pw-remote-server.cjs --root ~/pw-remote --port 39001 --host 0.0.0.0 --allow 198.51.100.7 --install
```

**Versions.** A Playwright client refuses a server of another major.minor, and lanes on one machine often differ (1.62 and 1.63 on the day this was written). The server keeps one `run-server` per installed version and picks it by the client's `User-Agent`, so one port serves them all. With `--install`, a version nobody installed yet installs itself on its first request. That request gets a 503, and the run falls back to a local browser while it installs. `GET /json` lists what is installed.

## Security

**The port has no password.** Whoever reaches it gets a browser on that machine, inside your network, able to open any page that machine can reach. So:

- **Firewall it to the test machine.** `pw-remote-setup.ps1` makes the rule. On Linux, use `ufw allow from <test machine> to any port 39001 proto tcp` or the equivalent.
- `--allow` is the second fence. The server drops a connection from any other address, even when the firewall would let it through. The default is loopback only.
- **Why there is a router at all.** Bare `playwright run-server` drops a client's `args` unless it runs with `--unsafe`, and the test suites need their args. `--unsafe` also accepts `executablePath`, which means "run any program on this machine". So the `run-server`s listen on `127.0.0.1` only, and `pw-remote-server.cjs` rewrites every client's launch options before passing them on. It drops `executablePath`, `downloadsPath`, `artifactsDir`, `tracesDir`, `env` and `firefoxUserPrefs`, and it refuses (403) the Chromium switches that start a program or write where they are told: `--renderer-cmd-prefix`, `--utility-cmd-prefix`, `--gpu-launcher`, `--browser-subprocess-path`, `--user-data-dir`, `--log-file`, `--load-extension` and the like. A refused request falls back to a local browser, and the server's log names the switch.
- What runs on the PC runs as the user who ran the setup, not as SYSTEM.
{% endraw %}
