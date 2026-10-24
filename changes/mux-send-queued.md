## lanes: mux-send into a busy window

- `mux-send` into a window that is mid-turn no longer reports the line as unsent: Claude Code queues it ("Press up to edit queued messages"), and mux-send now says it was queued and exits 0; it reads the input box between the last two rule lines, not the last prompt mark on screen
