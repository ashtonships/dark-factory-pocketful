# Ledger status

Updated by Coordinator. Ledger: `ledger/pocketful.md`. Time box: final report by Sun 4 Oct 18:00 CDT.

| Stage | State | Accepted revision | Gate receipt |
|---|---|---|---|
| 1 | in progress (ledger 273/273 sentences, 251 entries + 22 waivers + 9001–9003) | — | — |
| 2 | ledger written (222/222 sentences, 211 entries + 11 waivers); W-5/W-6 pre-work in review | — | — |
| 3 | not started | — | — |
| 4 | not started | — | — |

| Item | Seat | State | Entries | Evidence |
|---|---|---|---|---|
| W-1 | Builder | d3614cf; gating with W-2 at ca640ff | see ledger table | — |
| W-2 | Builder | ca640ff handed back 16:24; gate requested | 62–79, 131–204, 217–220 | — |
| W-3 | Builder | a3d2baf handed back; gate after W-1/W-2 | 205–216, 221–231 | — |
| W-4 | Builder | open | 232–273 | — |
| W-5 | Builder-Two | handed back 77595cc; in Adversary code review | stage-2 UI | Builder-Two self-test 38/38 (not evidence) |
| W-6 | Builder-Two | 73beaa0 → f074486 (D-11) → 93f3606 (fixes PF-A1..A4, survivor-11 test); in Adversary re-review | stage-2 UI | Builder-Two drill 109/109 (not evidence) |
| W-D | Builder | open (starts when W-1 accepted) | stage-2 direction | — |

## Blockers and exceptions

- Identity exception: main merge commit 370fdb5 (ledger merge) carries the repository's default git identity, not Checker's. History is not rewritten; reported by Checker.

## Checks

- Checker checks on main at 72c24d2: W-1 59, W-2 97, W-3 27, W-4 42 (items in force: checker/items.json). 247/254 stage-1 entries referenced; unreferenced: 2, 3 (process), 23, 32 (harness isolated mode), 35 (from stage 2), 219, 251 (permissions).

## Seeded faults

- W-5 at 77595cc, seed 5 (Adversary, `adversary/pocketful/measure.py --revision 77595cc --item 5`, test = Builder-Two's selftest 38 cases, as Checker had no W-5 check yet): 20 valid, 13 caught, 7 survived (65%). Report /Volumes/SSD/overflow/darkfactory/pf-w5-77595cc-mutants.json.
  - Survivor 11 (key generation radix in the getRandomValues fallback collapses distinct entropy into one key): a real blind spot in the checks; sent to Builder-Two as a selftest gap (keys from different entropy must differ). Product at 77595cc is correct.
  - Survivors 1, 2, 4, 9, 14 and 19 are equivalent or outside the input domain per Adversary's triage (reason text, copy, zero-total split, fallback entropy length, negative formatting, globalThis detection).
  - The seventh survivor's triage is pending.
- W-6 at 73beaa0, seed 6: no valid score. The unmodified baseline (Builder-Two's browser drill) took longer than 120 s, so 0 mutants were generated and the catch rate is null, not 0%. Report /Volumes/SSD/overflow/darkfactory/pf-w6-73beaa0-mutants.json. Adversary's own pinned-Chrome review: 10/14 pass; the 4 failures are PF-A1/PF-A2 at 1280 and 375. Holding: Unicode and markup notes and names render inertly, unchanged-form replay, a double submit debits once, no horizontal scroll, safe manual retry after an empty receipt.
