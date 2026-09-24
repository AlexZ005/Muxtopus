## schedules: a lane's name may be 32 characters

- A slug, the name a lane carries as its window, its handover file and its row in the window tree, may now be 32 characters instead of 22. A longer `title:` is no longer cut short. An orchestrator's `<orchestrator>-<lane>` names fit: `orchestrate-plan-` alone was 17 of the old 22.
- A title over 32 characters is still cut, and `--check`, the log and the dashboard still say so and name the slug it became.
- The schedules table's SLUG column grows to fit the longest slug on screen, up to 32 characters, so a long name is drawn whole instead of with an ellipsis. With only short slugs it is the width it always was.
- The name field on the `c` form is padded to the new limit, so that row is ten columns wider.
- Goldens: 57 screens moved. The 50 that draw the schedules table have SLUG two columns wider, because the fixture's 24-character slug `with-options-and-a-model` is now whole instead of cut to `with-options-and-a-mod`. The 7 that draw the `c` form have its name field ten columns wider. Nothing that was whole is cut.
