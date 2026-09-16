# A fixture for test_options.py: ONE BLOCK PER RULE the reader enforces, plus
# two good ones so a change that rejects everything still fails the test.
# The expected `bad` reason for each is asserted by key in the test.

key: good-line
group: contract
label: a good line option
hint: ticked, it appends one sentence
default: on
types: work
line: A sentence with {{SLUG}} left literal.

key: good-set
group: model
label: a good header field
# A comment INSIDE a block, which the real options.md uses to carry a
# measurement next to the `model` option. It must not end the block.
default: off
set: model
choices: opus, opus[1m], fable

group: contract
label: block with no key at all
line: nothing can address this.

key: Bad_Key
label: uppercase and underscore
line: not [a-z0-9-]+.

key: neither
label: no line and no set
hint: nothing to do when ticked

key: both
label: a line AND a header field
line: a sentence.
set: model
choices: opus

key: setnochoices
label: a header field with nothing to choose
set: effort

key: askwhat
label: an ask of an unknown kind
ask: colour
line: paint it {{VALUE}}.

key: asknovalue
label: asks for a value the line never uses
ask: number
line: run some lanes in parallel.

key: defaultmaybe
label: a default that is neither on nor off
default: maybe
line: a sentence.

key: typesall
label: a types filter that is not a type
types: everything
line: a sentence.

key: strayline
label: a block with a line that is not a field
This sentence has no field name in front of it.
line: a sentence.

key: twice
label: one field given twice
label: and again
line: a sentence.

key: good-line
label: the same key a second time in one file
line: a sentence.
