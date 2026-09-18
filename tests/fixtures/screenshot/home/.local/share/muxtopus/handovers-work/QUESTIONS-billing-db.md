# QUESTIONS — billing-db

1. **Drop the legacy `invoices_v1` table in this migration, or keep it one release?**
   The reporting job still reads it nightly; nothing else does.
   - **(a) RECOMMENDED: keep it one release, drop it in the next.**
   - (b) drop it now and move the reporting job in the same change

2. **Backfill in batches of 1 000 or 10 000?** Measured on staging: 4 s per
   batch of 10 000, no lock contention.
   - (a) 1 000, slower and safe
   - **(b) RECOMMENDED: 10 000**
