## c: the name is typed in the Create row, and esc is instant again

- **esc opens the menu straight away.** A lone Escape used to take the full
  250ms that a split escape sequence is allowed, because a bare ESC looks
  like the start of one — a quarter second of nothing on the key that leaves
  every view. The two waits are now separate: 100ms to tell Escape from an
  arrow, and the old generous budget once a sequence has actually begun.
  `MUXTOPUS_ESC_TIME` overrides it on a slow link.
- **No name modal.** `c` opens the form directly with the name already in
  the first row — `Create ➥[muxtopus-crane]` — and you type into that row.
  The field is padded, so nothing moves sideways as you type; the first
  character replaces the whole offer; a space becomes the hyphen a slug
  would have had anyway. `c enter` is now the whole gesture, one keystroke
  fewer than before.
- **Press `c` again and it offers a different name.** The suggestion used to
  be seeded from the folder alone, so the second look gave the same word —
  the only thing that moved it on was a name being *taken*, which one you
  just declined is not.
- **Model, Effort and Permission mode say what you will actually get.**
  Those rows read `(account default)`, which names the mechanism — no flag
  is passed — and never the outcome. They now read the value out of the
  settings.json that will apply (the project's `settings.local.json`, its
  `settings.json`, then the account's) and name it and the file. When
  nothing sets it anywhere the row says `unset`, which is a different and
  honest answer: the CLI's own built-in default applies.
