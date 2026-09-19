## muxtopus: relaunching from inside tmux works

- after Quit, typing `muxtopus` at the prompt the dashboard window drops to starts the dashboard again, instead of failing with "sessions should be nested with care"
- `muxtopus` run from a window of another tmux session switches that client over rather than refusing to nest
