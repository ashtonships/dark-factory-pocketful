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
