# Muxtopus -- the price and model table behind the insights view's $ figures
# and its "% of the context window". One block per model, blank line between
# blocks, the same `key: value` syntax as options.md.
#
#   model:           the model id as a transcript records it. A block also
#                    matches that id with a date suffix (claude-haiku-4-5
#                    matches claude-haiku-4-5-20251001) and NOTHING looser: a
#                    model this file does not name shows "no price", never a
#                    neighbour's price.
#   input output cache_read cache_write_5m cache_write_1h
#                    US dollars per million tokens
#   window:          context window in tokens (1000000, 1M, 200K); leave it
#                    out when unknown and the % figures skip that model
#
# EVERY $ IS "API-EQUIV": what the same tokens would cost on the Claude API at
# these list prices. A subscription paid none of it. Not modelled: fast mode,
# data-residency (inference_geo "us") and Batch pricing, and web searches.
#
# The numbers were copied from Anthropic's published pricing page on the date
# below; context windows from Anthropic's model table. Update the date when you
# update a number. This file is yours; install.sh never rewrites it.

as of: 2026-09-17
source: https://platform.claude.com/docs/en/about-claude/pricing

model:          claude-fable-5-1
input:          10
output:         50
cache_read:     0.25
cache_write_5m: 12.50
cache_write_1h: 20
window:         1M

model:          claude-mythos-5-1
input:          10
output:         50
cache_read:     0.25
cache_write_5m: 12.50
cache_write_1h: 20
window:         1M

model:          claude-fable-5
input:          10
output:         50
cache_read:     1
cache_write_5m: 12.50
cache_write_1h: 20
window:         1M

model:          claude-mythos-5
input:          10
output:         50
cache_read:     1
cache_write_5m: 12.50
cache_write_1h: 20
window:         1M

model:          claude-opus-5
input:          5
output:         25
cache_read:     0.50
cache_write_5m: 6.25
cache_write_1h: 10
window:         1M

model:          claude-opus-4-8
input:          5
output:         25
cache_read:     0.50
cache_write_5m: 6.25
cache_write_1h: 10
window:         1M

model:          claude-opus-4-7
input:          5
output:         25
cache_read:     0.50
cache_write_5m: 6.25
cache_write_1h: 10
window:         1M

model:          claude-opus-4-6
input:          5
output:         25
cache_read:     0.50
cache_write_5m: 6.25
cache_write_1h: 10
window:         1M

model:          claude-sonnet-5
input:          2
output:         10
cache_read:     0.20
cache_write_5m: 2.50
cache_write_1h: 4
window:         1M

model:          claude-sonnet-4-6
input:          3
output:         15
cache_read:     0.30
cache_write_5m: 3.75
cache_write_1h: 6
window:         1M

model:          claude-haiku-4-5
input:          1
output:         5
cache_read:     0.10
cache_write_5m: 1.25
cache_write_1h: 2
window:         200K

# Older models: priced, but their windows are not in the model table this was
# copied from, so no window line.

model:          claude-opus-4-5
input:          5
output:         25
cache_read:     0.50
cache_write_5m: 6.25
cache_write_1h: 10

model:          claude-sonnet-4-5
input:          3
output:         15
cache_read:     0.30
cache_write_5m: 3.75
cache_write_1h: 6

model:          claude-opus-4-1
input:          15
output:         75
cache_read:     1.50
cache_write_5m: 18.75
cache_write_1h: 30

model:          claude-opus-4
input:          15
output:         75
cache_read:     1.50
cache_write_5m: 18.75
cache_write_1h: 30

model:          claude-sonnet-4
input:          3
output:         15
cache_read:     0.30
cache_write_5m: 3.75
cache_write_1h: 6

model:          claude-3-5-haiku
input:          0.80
output:         4
cache_read:     0.08
cache_write_5m: 1
cache_write_1h: 1.60
