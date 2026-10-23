## e2e slots: pc slots, where the whole run happens on another machine

- `MUXTOPUS_E2E_PC=pc` adds **pc slots**: the run's tree is mirrored to a host you reach by ssh (a WSL2 distro on a Windows PC, or any Linux box), and its `node_modules`, the dev server, the test and the browser all run there. The output streams back, and every file the run wrote (evidence, screenshots, `/tmp`) is copied back to the same path. Nothing in a lane's command changes. Measured on a Steam Deck against a desktop PC, the Deck kept about 25 MB for a run that takes 1.4–2.9 GB locally, and the suites that a remote slot made slower (many small page calls over WiFi) got faster.
- **Hosts are named in `~/.config/muxtopus/hosts.conf`**, which is never in the repository. A setting names a host (`pc`), and only that file holds its address, user and key.
- `node_modules` there is built once per lockfile hash (`npm ci`), and every later tree with the same lockfile gets a hard-linked copy. The dev server is started on the same port with `lane-dev` and kept warm by its idle timer, or stopped after the run with `--dev`.
- A pc slot is tried first while `MUXTOPUS_E2E_PREFER` is `remote`. `--local` never takes one, and `--exclusive` does not hold them. A host that does not answer is skipped. A run the host cannot take (its tree is a checkout of that machine's own, the port is taken there) goes to another slot and says why. Ctrl-C or a `timeout` stops the run over there too.
- On a WSL2 host, a test that asks for a GPU (`--use-angle=vulkan`) gets the PC's card through Mesa's d3d12 driver instead of a silent CPU rasteriser (`gpu = auto` in `hosts.conf`).
- Credentials in the environment are not sent (`*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `GH_*` and the like). `E2E_PC_ENV` names one to send anyway. The manual page *A PC as a second host* has the whole list.
- `lib/pc-host-setup.ps1` (Windows) and `lib/pc-host-setup.sh` (Linux) set a host up. On Windows that is a new distro of its own (your other distros are not touched), sshd that takes a key only, a keep-alive task, a port proxy, and a firewall rule for one address. `-Uninstall` removes them.

## the published repository: no private addresses

- The manual's examples now use documentation addresses (`192.0.2.10`, `198.51.100.7`) and neutral paths. A test fails CI on a LAN address, a MAC address or a home folder in any tracked file. A local `~/.config/muxtopus/private-words` file adds your own names to what it looks for.

## fixes

- **A comment on a default's line in `profile.sh` no longer takes everything down.** `WATCHDOG_REPORT_E2E_MIN=600   # a note` turned every word of the note into a "key", and the watchdog crash-looped while every `e2e-slot` and `handover.sh` failed with it. The key list now ignores comments and keeps only `NAME=value` lines.
- **A lane problem is reported once per `WATCHDOG_REPORT_REPEAT_MIN`, even if a pass misses it.** One pass that did not see a problem (an e2e holder the process walk missed) used to drop its key, so the next sighting was "new" and was sent again. A five-hour e2e hold reached its parent six times in 40 minutes. A reported key now stays for one repeat interval after it was last sent.
