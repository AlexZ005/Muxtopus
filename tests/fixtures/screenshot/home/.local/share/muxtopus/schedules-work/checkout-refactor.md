type: work
at: reset
title: checkout-refactor
slug: checkout-refactor
cwd: @SB@/home/src/acme/checkout
model: opus
effort: high
permission-mode: bypassPermissions
options: questions, phases
status: launched
created: @DATE-13000@
launched: @DATE-7200@
---
Split the checkout refactor into lanes: the cart API, its tests and the UI. Write one schedule entry per lane and one more, after: all three, that integrates them.
