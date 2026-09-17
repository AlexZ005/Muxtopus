"""dashboard.help -- the `?` screen, still one string.

It is here rather than in deck_status.py because the shell is the shell, and
it is still ONE string rather than a section per module because phase 5 of
docs/plan-dashboard-split.md is where `?` becomes what the loaded modules
say about themselves (App.add_help) -- and that is the one golden capture the
split is allowed to change, reviewed by eye, in its own commit.

Until then: every word of it is what it was before the split.
"""
from dashboard.core import (CONTEXT_WINDOW, DIM, FRAME_INTERVAL, GREEN,
                            PROFILE, PROFILE_LABEL, RED, SCHEDULES_DIR,
                            USAGE_MAX_AGE, WATCHDOG_TREE, WD_INTERVAL, YELLOW,
                            knob, options_paths)
import muxsettings

SOFT = knob("WATCHDOG_SOFT_PCT", PROFILE)
HARD = knob("WATCHDOG_HARD_PCT", PROFILE)

HELP = f"""
  [bold]deck-status[/] -- lane dashboard

  [bold]q[/] quit        [bold]r[/] redraw now      [bold]R[/] reload this script
  [bold]s[/] scheduled windows      [bold]enter[/] on the extras row stops/starts them
  [bold]w[/] watchdog    [bold]m[/] monitoring      [bold]p[/] btop   [bold]?[/] this screen
  [bold]u[/] read usage limits      [bold]up/down[/] pick   [bold]space[/] menu   [bold]esc[/] muxtopus menu
  [bold]c[/] a new claude session (folder, model, effort, mode, where, name, first prompt)
  [bold]enter[/] open the selected session's window (Ctrl-b 0 comes back here)
  [bold]f[/] lanes: this account only / every account
  [bold]←/→[/] fold / unfold a subtree      [bold]t[/] tree ordering on / off

  [{DIM}]THE WINDOW TREE[/]
    tmux has NO window hierarchy: its windows are a flat, indexed list per
    session, with no parent to set and nothing to collapse. So the tree is DATA
    the scheduler keeps ({WATCHDOG_TREE}) and this table is the VIEW of it.
    A window the scheduler opened from another one is drawn under it and
    indented; ← folds that subtree (the parent then shows +N), → unfolds it, and
    ← on a leaf steps out to the parent. With nothing parented the order is
    exactly what it always was -- sessions by context -- so the tree costs
    nothing until there is one. [bold]t[/] turns the ordering off entirely.

    What tmux CAN be made to honour is done in the flat list too: the depth is
    carried by the window name (➥lane, ➥➥child) and a child is inserted after
    the last window of its parent subtree, so a family stays contiguous.

  [{DIM}]LANES AND ACCOUNTS[/]
    A dev server belongs to the account whose session started it -- read off
    CLAUDE_CONFIG_DIR in its environment, which it keeps even after the window
    that started it is gone. The table shows this account's by default; f, or
    enter on a lane row, shows every account's with each one labelled. Arrow
    up from the first session to reach the lane rows.

  [{DIM}]THE MENU (space)[/]
    Two switches at the top, then everything you can do to the window under
    the cursor: open, rename, skip it, wind it down, resume it, continue it at
    low priority, or close it. Arrows pick, enter chooses, esc closes.

  [{DIM}]A NEW CLAUDE SESSION (c)[/]
    Seven screens through the picker and the prompt: the working folder (the
    cursor's, the setting, every session's, the dirty trees, the checkouts
    under MUXTOPUS_HOME, or a typed path -- it must exist); the model, as a CLI
    ALIAS (opus, fable, sonnet…; `--model opus-5` is refused by the CLI and
    kills the window after it has eaten the paste); the effort; the permission
    mode (preselected from Settings, or nothing preselected when that says
    ask -- a default, never a lock); where it goes (a top-level window, or
    under a live one: ➥➥name, inserted after that parent's subtree, drawn
    indented); the name, which is the slug (window, handover, handover.sh
    done); and an optional first prompt.
    THEN IT WRITES A SCHEDULE ENTRY with at: already past, and nothing else:
    the watchdog opens the window within one pass and does the trust dialog,
    the readiness wait, the paste and the tree row -- one launcher, whoever
    asked. The entry carries model:, effort:, permission-mode:, cwd:,
    parent:/window:, and watchdog: off / monitor: off when Settings says a
    new window is not watched or monitored (the launcher opts the session out
    once it has an id). An empty prompt writes a plan entry: the session gets
    its identity line and nothing invented.
    Choosing bypassPermissions also offers "…and make it the default": a
    confirm names the exact settings.json (project or account, per Settings)
    and what changes -- EVERY future session there skips permission prompts,
    including ones nothing is watching. The write merges permissions.defaultMode
    into the existing JSON (nested, where Claude Code reads it), backs the
    old file up beside itself, and refuses a file that is not valid JSON.

  [{DIM}]THE MUXTOPUS MENU (esc) AND SETTINGS[/]
    esc opens the dashboard's own menu -- what is not about one row: Settings,
    the watchdog and monitor switches by their full names (w and m stay the
    fast path), Disconnect (detaches this tmux client; every window keeps
    running, `muxtopus` attaches again), Reload (R) and Quit.

    Settings are written to

        {muxsettings.dashboard_conf_path(PROFILE)}

    a file the DASHBOARD owns, in the same KEY="value" shell as config -- kept
    apart from config because that one is yours and full of your comments, and
    a program that rewrites it would eventually eat them. It is read as a
    layer ABOVE config (and profiles/<name>.dashboard.conf above
    profiles/<name>.conf), so what the menu writes is what the next frame
    reads; a value is only reported as saved once it has been read back from
    disk. `muxtopus -c` shows every setting with the layer it came from.
    The settings: the menu layout (table, modal, bottom), the permission mode,
    model and effort preselected when c creates a window, whether such a window
    is watched and monitored, the working folder offered first, and which
    settings.json "make it the default" writes to.

  [{DIM}]SESSION MONITORING[/]
    Off by default, and a separate switch from the watchdog because they are
    different powers. The watchdog RESTARTS a window that already stopped,
    which cannot lose anything. Monitoring speaks to a window that is still
    WORKING, asking it to commit what it has and write a handoff before the
    budget runs out -- so that the next window can start from that handoff
    instead of carrying a quarter-million tokens of context forward.

    It is delivered through a PostToolUse hook, so it reaches a session mid-turn
    without typing into a pane that is busy composing. Two bands: past {SOFT}% of
    the session budget it is asked to stop spawning subagents, past {HARD}% to
    checkpoint and stop. The hard band only fires when it BUYS something -- a
    context big enough to be worth restarting fresh, or a weekly budget too
    spent for /low-priority to carry the session through. Otherwise the window
    is left to run into the limit banner, which costs nothing.

    THE SESSION IS NEVER TOLD WHY. It receives an instruction, not a budget
    negotiation. The reasoning is logged here instead: the WOUND column says
    when a window was last asked to wrap up, and the log carries the reading
    that decided it.

  [{DIM}]UNCOMMITTED[/]
    Its own table rather than a column, because dirty trees and sessions do not
    line up: a repo can be dirty with no session and no dev server anywhere
    near it, and that is the copy most likely to be lost. The DIRTY column on a
    session row is a hint for the tree that window is sitting in.

  [{DIM}]SCHEDULED WINDOWS (s)[/]
    One .md per window to open later, in {SCHEDULES_DIR} (templates in
    templates/; the folder README documents the format). The watchdog daemon
    launches due items: `at: reset` fires when the session limit resets or the
    budget simply reads fresh; an absolute time fires when it passes. The new
    window opens right after its `window:` target, named with a leading ➥,
    and the prompt lands as ONE bracketed paste. A file the view cannot parse
    shows as corrupted with the reason, and never launches.
    In the view: enter/e edit · c create (type, template, THE OPTIONS TABLE,
    then the editor to paste the prompt) · o reopen the options table on a
    pending entry · l launch now · d delete · r reload · s/esc back.
    space opens the ENTRY'S menu: the why sentence when it is blocked, waiting
    or stalled, then edit, options, launch now, duplicate (a pending copy
    with a different slug, opened in the editor), check (the executor's
    --check --body report, full screen), open its window when it has one,
    and delete. A corrupted entry gets its reason and only delete.

  [{DIM}]THE OPTIONS TABLE (c, and o on a pending entry)[/]
    The checkboxes between the template and the editor: the contract sentences
    you would otherwise retype into every brief, ticked once. They come from

        {options_paths(PROFILE)[0]}

    which is YOURS -- one block per option, blank-line separated, `key: value`
    like a schedule header, its own comment block at the top being the format
    spec. Edit it and the table changes; a second account overrides or adds to
    it in profiles/<name>.options.md. A block the reader cannot make sense of
    is shown greyed with the reason rather than dropped, exactly as a
    corrupted schedule entry is.

    ↑↓ picks, space or enter ticks. An option that needs a number or a time
    opens the text prompt; one with a list of choices opens the picker (that
    is how model: and effort: are set). THE ACTIONS ARE ROWS at the bottom:
    check all, uncheck all, continue (save what is ticked, then the editor;
    "save" on a reopen) and, on create only, skip (continue with nothing
    ticked). esc CANCELS, on create and on reopen alike: on create no entry
    file is written at all, on reopen the file is untouched.

    A TICK WRITES ONE OF TWO THINGS: a sentence, appended to the body under a
    `## Options` heading at the END of it, or a header field (model:, effort:)
    the launcher passes as a flag. The header also records `options:
    questions, phases, lanes=3`, and THAT is the source of truth: o reopens
    the table from it and regenerates the section, so a sentence edited by
    hand in that section is overwritten on the next save. To keep one, move it
    ABOVE the heading -- everything above it is preserved byte for byte -- or
    edit it in options.md where it came from.

    Placeholders in a sentence ({{{{SLUG}}}}, {{{{WINDOW}}}}, {{{{HANDOVER}}}},
    {{{{QUESTIONS}}}}, {{{{SCHEDULES}}}}, {{{{CWD}}}}, {{{{PARENT}}}}) are written out
    LITERALLY and resolved by the executor when the prompt is pasted, because
    the slug does not exist yet while the table is open. {{{{VALUE}}}} is the
    exception -- it is what the prompt collected, and it is resolved here.

    WHY AN ENTRY HAS NOT FIRED is printed under the table for the row under the
    cursor, in the executor's own words -- `at: reset` is two gates (the budget
    reading fresh, or the five-hour window rolling over) and the line says which
    one it is waiting on. A row marked [{RED}]stalled[/] cannot be judged at all and
    will not resolve on its own. To resolve an entry in full without launching
    anything -- slug, window name, handover path, insert target, the exact
    paste, and the due verdict with its reason:

        claude-watchdog.sh --check <name> [--body] Plan sessions write their forks into core/plans/QUESTIONS-*.md
    instead of asking; those files are listed in the view until answered.

  [{DIM}]A session shown as (background) was started with `claude --bg`. It has no
  terminal, so there is no window for enter to open and no pane for the
  watchdog to type into -- it can be watched but never restarted from here.[/]

  [{DIM}]USAGE LIMITS (top right)[/]
    The only numbers here that cannot be computed locally. Claude Code has no
    usage subcommand and no file holding live limit state, so [bold]u[/] runs
    claude-usage.sh, which starts a throwaway session, sends /usage, reads the
    pane and kills it -- about four seconds, no turn taken. It is ON DEMAND for
    that reason, and the third line carries the time it was read so a stale
    number cannot pass for a current one.

    [bold]u[/] refreshes only if the figures are over {USAGE_MAX_AGE} minutes old, so leaning
    on the key costs nothing; [bold]U[/] forces a read now. [bold]R[/] reloads this script and
    nudges the limits the same way u does. The watchdog also refreshes hourly
    on its own, so the numbers stay warm with nobody watching.

    THE READING BELONGS TO THIS ACCOUNT ([{YELLOW}]{PROFILE_LABEL}[/]) and no other. The probe
    is a tmux session, and a tmux session does NOT inherit the environment of
    whatever created it -- so the account has to be handed in explicitly, and
    for a while it was not: every account's probe read the same budget and
    filed it under its own name. If two dashboards ever show identical figures
    again, that is the shape of the bug.

    A FAILED READ SAYS SO. It leaves the last good numbers alone and marks the
    third line [{YELLOW}]stale[/], rather than writing a row of blanks stamped with the
    current time -- which showed "?%" and then counted as fresh enough not to
    retry. A read that cannot get to a prompt names its reason: the account is
    not logged in, has not trusted the folder, or never finished setup.

    The same values are available to scripts and to prompts:
      claude-usage.sh --brief | --json | --session-pct | --week-pct
      claude-usage.sh --ensure 15     refresh only if older than 15 minutes
    Every reading is appended to usage.log with a timestamp.

    If a limit ever empties BEFORE the time it promised, that is the one good
    surprise here, so it is announced loudly and sent to your phone. Configure
    a backend in ~/.config/claude-notify.conf (ntfy, Pushbullet or Telegram --
    see the header of claude-notify.sh); with none configured it is logged and
    nothing is sent.

  [{DIM}]CLAUDE[/]
    [bold]CONTEXT[/] is the session's live context against {CONTEXT_WINDOW // 1000}k
    (set CLAUDE_CONTEXT_WINDOW if yours differs -- a running session cannot be
    asked what its window is). [bold]SPENT[/] is that session's lifetime input +
    cache writes + output, the parts billed at or above full rate; cache READS
    are excluded because they cost about a tenth and would swamp the number.
    Subagent tokens are NOT included -- they never enter the parent transcript.
    [bold]IDLE[/] is time since that session last wrote a turn; it goes amber past
    15 minutes, so a stalled window reads differently from a finished one.
    [bold]RESUMED[/] is when the watchdog last restarted that session.

  [{DIM}]UNCOMMITTED WORK[/]
    [bold]DIRTY[/] on the lanes table is tracked files changed in that working tree.
    It is not on the claude table because a session's cwd here is /home/deck,
    which is not a repo -- the question is only answerable per TREE. A dirty
    repo with no dev server would then be invisible, so the system line names
    those separately. Untracked files are ignored: a scratch file is noise, a
    modified tracked file is work you could lose.

    [{YELLOW}]limited[/]  stopped at a usage limit, waiting for the reset
    [{RED}]due[/]      the reset has passed and it is still sitting there
    [{RED}]stranded[/] NOTHING IS EVER GOING TO TOUCH THIS. A ➥ lane, idle past
             WATCHDOG_STRANDED (120m), with an OPEN handover, and no pending
             schedule entry naming it -- not by slug, not by after:, not a
             resume- entry. idle stays dim because it is a fact about the last
             turn and usually means finished; this is a fact about the future.
             It is a label, never a trigger: the watchdog only ever prompts a
             [{RED}]due[/] window. Schedule a ➥resume from the menu, or answer its
             handover.

    [bold]w[/] arms the watchdog: an IDLE window that hit a limit is prompted to
    continue once its reset time passes, once per limit. It never types into a
    window that is working. Disarmed, the panel still reports; nothing is sent.
    Measured twice here: autoContinueAtUsageLimit does NOT resume after the
    5-hour session limit, and /loop dies on its first refused wakeup.

    [bold]space[/] excludes ONE session (the [{GREEN}]checkmark[/] becomes a dot). The choice
    lives in the watchdog's own file, so it holds whether or not this dashboard
    is open, and survives a restart. Everything is included by default, so a
    session started tomorrow is covered without being opted in.

  [{DIM}]All of it is read from files claude-watchdog.sh publishes: no API calls,
  no tokens, and no tmux captures from this process.[/]

  [{DIM}]CLOSED WINDOWS LEAVE ON THE NEXT REDRAW[/]
    That file is rebuilt once every {WD_INTERVAL}s, so a window closed just after a pass
    used to sit on this table for most of the next one -- measured at 21 and 25
    seconds, long enough to arrow onto a row that is not there any more. Each
    row now carries its process id, and this frame has already walked /proc for
    the memory figures, so a row whose process is gone is dropped here: no
    fork, no tmux call, gone within {FRAME_INTERVAL:g}s.

    Nothing else got faster. Rows still APPEAR at the watchdog's pace, because
    deciding what a session IS costs a transcript read, and a 2s frame will not
    pay for one. The test is only whether the pid is still in /proc -- not
    whether it still looks like claude, because dropping a live session to
    catch a recycled pid trades a harmless wait for a hidden window.

  [{DIM}]LANE STATE[/]
    [{GREEN}]fresh[/]    under 6h
    [{YELLOW}]ageing[/]   6-24h
    [{RED}]stale[/]    over 24h. A vite server was measured at 2487 MB after three
             days against 1142 MB fresh, and a long-lived server is also what
             serves dual module instances.

  [{DIM}]RAM is summed per PROCESS GROUP: `npm run dev` and the vite it spawns are
  separate processes, the port belongs to vite, and npm holds ~70 MB of its own.[/]

  [{DIM}]press any key[/]
"""
