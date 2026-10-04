# Stage-1 pre-mortem

1. **Transaction fracture under 50 concurrent operations:** balance mutation, pending-request transition and
   receipt/key insertion commit separately. Violates ledger 9–11: conservation, no negative balance, at-most-once request payment.
2. **Retry identity mishandling:** caller/path scope, parsed JSON equality, replay-before-validation or failed-key
   reuse is wrong. Violates stage-1 §7, ledger 131–148. Concurrent identical calls must yield one 201 and 49 identical 200s.
3. **Validation/transport coercion:** Python booleans are accepted as amounts, integral JSON floats are rejected,
   Unicode length is counted incorrectly, query exponents are accepted, or rejected/chunked bodies poison keep-alive.
   Violates §4–5 and lessons 9001–9003.
4. **Split boundary errors:** zero shares disappear or cannot be paid, caller omission changes the divisor, or
   remainder allocation follows sorted rather than submitted handles. Violates §9, ledger 221–231 and eventually 9.
5. **Batch/upgrade state gaps:** sequential settlement funding rejects a valid net batch or partially applies it;
   import regenerates receipts, merges destination credentials, drops operator permissions/tokens/retry bodies,
   or replays seeded movements against net balances. Violates §10–11, ledger 232–273.

Sent to Coordinator before execution. All are hypotheses, not product findings.

# W-5/W-6 review pre-mortem

1. Normalized body equality collapses a changed raw form field's new intent (1045).
2. An empty/truncated receipt is treated as success rather than uncertainty (1088–1092).
3. A delayed write reply clears or overwrites a newer edit/pending retry (1043,1090,1101).
4. Earlier refreshes or capture callbacks replace newer state (1083,1222).
5. Names/notes render as HTML, lose text, or force 375px horizontal scroll (§8 notes,1024–1027).

Sent to Coordinator before client review. Only the first two currently have reproduced product findings.

# Stage-3 pre-mortem

1. **Effective time is confused with knowledge time.** A backdated correction leaks into a `known_at`
   view before its recorded time, a future-known payment contributes before revision 1 exists, or the replaced
   revision is counted alongside the correction. Probe both sides of recorded/effective instants, equivalent
   offsets, inclusive `as_of`, half-open statement boundaries and zero reversals. Entries 2016–2021,
   2038–2041, 2070–2083; D-16 and D-18.
2. **Correction identity and state commit separately.** Concurrent writers with the same expected revision
   both succeed; a decrease debits the sender instead of the receiver; stale/funds/history failures claim a key;
   or replay validates the current revision rather than returning the immutable original result. Probe 50-way
   same-key and different-key corrections, a correction after a later revision, and corrected retry after failure.
   Entries 2046–2065 and 2095.
3. **Historical available funds omit lifecycle events or test transient tie order.** Total stays positive
   while an earlier open hold makes available negative, a partial capture releases too much, or a future query
   misses expiry known at creation. A same-instant net-funded boundary may be falsely rejected if movements
   are checked sequentially. Probe creation, nonfinal/final capture, void and expiry across both clocks, including
   retrospective corrections that are affordable now. Entries 2060–2064 and 2102–2113.
4. **Statement pages drift or report page-local balances.** A correction moves a row across the window,
   an intervening payment changes the default `to`, or limit/offset changes balance_after/opening/closing.
   Probe frozen snapshots while writing, identical effective times with bytewise IDs, zero-delta entries,
   empty/final/beyond-end pages, cross-user tokens and pre-reset token invalidation. Entries 2024–2037,
   2078–2094 and 2116; D-17.
5. **Upgrade reconstructs the wrong opening ledger or mutates linked originals.** Imported net balances
   are replayed, original receipt/timestamp/retry data is regenerated, closed seeded holds invent a lifecycle,
   or captures/settlement members become correctable. Probe stage-1 and stage-2 exports with pending requests,
   partial holds, captures and saved receipts; verify conserved totals in historical views, immutable feed
   receipts, two-party revision privacy and 422 linked_payment_immutable. Entries 2009–2012, 2042–2044,
   2064–2069, 2096–2101 and 2113–2116.

Ledger eaecb1a merged before this preparation. These are prospective risks, not findings or stage-3 product work.
