## the stats collector test stubs the interpreter the watchdog actually runs

- `tests/test_stats_watchdog.sh` put its recording/failing `python3` on `PATH` and
  greped the source for `timeout "$STATS_TIMEOUT" python3`. Both stopped being true when
  the python half moved to `$MUX_PYTHON`, so the stub was never reached: ten of its
  thirty-one checks had been failing since v5.2.3, including every assertion about the
  collector's five-minute cadence and its failure guard.
- The test now pins `MUXTOPUS_PYTHON`, which is the first candidate `mux_resolve_python`
  probes and the documented way to name an interpreter, and asserts the bound in its
  current form. 31 passed.
- No product code changed. The guard it covers was working the whole time; nothing was
  proving it.
