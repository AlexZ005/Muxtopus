## watchdog: the last thing each session said

- `claude-watchdog.sh --status` has a `SAID` column: the first 80 characters of each session's last text, on one line — what it last told you, without switching to its window. A session with nothing to read (a background job, a plain shell) says `-`. `--status` also names its columns now, in a `#` line above the rows.
- The dashboard's claude table has a `SAID` column too, **hidden until you ask for it**: esc ▸ Settings ▸ Columns, `enter` on `claude · SAID`. At 80 columns it is one `shift-→` away and cut with an ellipsis; from about 113 columns it shows all 80 characters.
- It is the session's last *text*: a window that has since run a tool shows what it said before that, and IDLE beside it says how old the turn is. It never leaves the machine — no phone notification carries it.
- Goldens: none moved. The main table is unchanged because SAID starts hidden, and no golden captures the Settings ▸ Columns screen (its new row is covered by `tests/test_columns_menu.py`).
