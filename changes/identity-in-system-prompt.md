## windows: the identity lines move into the system prompt; an empty first prompt opens a blank claude

- A window opened from the dashboard with `c` and no first prompt now opens at a blank prompt. Nothing is pasted and nothing is typed. Before, it received the seven `[muxtopus]` identity lines as its first message and spent its first turn answering them.
- Every scheduled and restored lane window still knows which window it is, its slug and its handover file: those lines now go to `claude --append-system-prompt-file`, where they cost no turn and hold for the whole session. A `work` body is pasted as before, without the header on top.
- A `claude` too old to take that flag gets the identity pasted at the top of the first prompt, as every window did until now, and the watchdog log says so once.
- `claude-watchdog.sh --check --body` prints the identity and the paste as two separate blocks, and says when an entry pastes nothing.
- The installer's closing block is shaped like Claude Code's own: a `⚠  Setup notes:` list with what is not in place yet and the exact line to run before `muxtopus` works in this shell.
