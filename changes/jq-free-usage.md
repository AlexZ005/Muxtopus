## usage: the numbers are read again, and jq is no longer required

- The usage probe now ANSWERS the trust dialog instead of stopping in front
  of it — the same Down/Enter on "Yes, I trust this folder" that the
  scheduler and the restore have always used for the windows they open. On a
  machine whose folder had never been accepted, every reading failed as
  "<account> has not trusted <folder>" while the launcher was quietly
  accepting the same dialog in the same folder all day.
- The probe also picks a folder it can actually enter. It used to choose any
  folder the account had accepted, which on one box was `/root` — left there
  by a `claude` run under sudo, and unreadable by the user who owns the
  session, so the probe fell back to home and hit the dialog anyway.
- **jq is optional.** It was a silent hard requirement at ~60 call sites and
  only three of them ever checked for it, so a machine without jq could not
  read `sessions/<pid>.json` at all: no sessions, no token counts, no model
  on the dashboard, reported as "0 session(s)". Muxtopus now reads JSON
  through `mux_json`, which uses the real jq when it is installed, libjq via
  the `jq` PyPI wheel when that is importable, and its own small reader
  otherwise. Installing jq is still worth it and the installer still says so
  — it just no longer decides whether the watchdog can see your sessions.
