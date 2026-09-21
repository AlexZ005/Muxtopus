## install: the fetched python actually arrives

The interpreter the previous release fetches when a machine has no `python3`
≥ 3.10 never got as far as being unpacked. Three bugs, all of them found by installing it
in a clean container rather than by reading the code:

- **The checksum was looked for in the wrong place.** python-build-standalone
  publishes one `SHA256SUMS` for the whole release, not a `.sha256` beside
  each asset — so every download was refused with `no published sha256` and
  every machine fell back to the bash renderer. The sum is now read from that
  file, by asset name.
- **It chose a release candidate.** The names carry the Python version and
  `3.15.0rc2` sorts above `3.14.7`, so the newest build in the list was a
  pre-release. Only released `3.x.y` builds are considered now, and the
  free-threaded variants — a different runtime offered under a name that
  sorts the same — are skipped.
- **The install hints named packages that do not exist**: `sudo pacman -S
  python3` (Arch calls it `python`) and `sudo pacman -S claude` (not a distro
  package at all — it now points at the Claude Code docs). On Debian and
  Ubuntu the python line asks for `python3-venv` too, which is what the
  dashboard's venv needs.

On a container with no `python3` at all, `./install.sh` now fetches CPython
3.14.7, checks it, builds the venv, and the Rich dashboard and `muxtopus
stats` both run.
