## dashboard: fits a small terminal

- **The tab strip shrinks instead of spilling off the edge.** When the tabs
  do not fit, their labels get shorter first (full, then short, then an
  initial — the tab you are on keeps its name longest); only then do tabs
  past the first six scroll, with a `«N` / `N»` count of what is off each
  side and `←→ tab 7/9` saying where you are. `←` `→` still visit every tab,
  drawn or not.
- **The footer no longer falls off a short terminal.** On a 24-row client
  (or any small one) the lanes and claude tables give up rows and scroll,
  with `▲ N more` / `▼ N more` like a long menu, and the schedules table
  does the same. If there still is not room, the uncommitted panel and then
  the deck header step aside, and the claude title says so.
- On a narrow terminal the tables drop their least important columns
  instead of squeezing the window names out, and no row wraps onto two lines.
