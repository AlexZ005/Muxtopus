# A synthetic price table for the tests -- the shipped one is seeds/prices.md.
# Two blocks are broken on purpose: a window that is not a number, and a
# block with an unknown key and most prices missing.
as of: 2026-09-17

model:          claude-opus-5
input:          5
output:         25
cache_read:     0.50
cache_write_5m: 6.25
cache_write_1h: 10
window:         1M

model:          claude-haiku-4-5
input:          1
output:         5
cache_read:     0.10
cache_write_5m: 1.25
cache_write_1h: 2
window:         lots

model:          half-priced
input:          1
bogus:          3
