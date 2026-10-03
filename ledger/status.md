# Ledger status

Updated by Coordinator. Ledger: `ledger/pocketful.md`. Time box: final report by Sun 4 Oct 18:00 CDT.

| Stage | State | Accepted revision | Gate receipt |
|---|---|---|---|
| 1 | in progress (ledger 273/273 sentences, 251 entries + 22 waivers + 9001–9003) | — | — |
| 2 | not started | — | — |
| 3 | not started | — | — |
| 4 | not started | — | — |

| Item | Seat | State | Entries | Evidence |
|---|---|---|---|---|
| W-1 | Builder | in progress (assigned Sat 3 Oct 15:00) | see ledger table | — |
| W-2 | Builder | open (after W-1) | 62–79, 131–204, 217–220 | — |
| W-3 | Builder | open | 205–216, 221–231 | — |
| W-4 | Builder | open | 232–273 | — |
| W-5 | Builder-Two | handed back 77595cc; in Adversary code review | stage-2 UI | Builder-Two self-test 38/38 (not evidence) |
| W-6 | Builder-Two | in progress (screen structure and behaviour, unstyled, ui-core/) | stage-2 UI | — |
| W-D | Builder | open (starts when W-1 accepted) | stage-2 direction | — |

## Blockers and exceptions

- Identity exception: main merge commit 370fdb5 (ledger merge) carries the repository's default git identity, not Checker's. History is not rewritten; reported by Checker.

## Checks

- Checker checks on main at 72c24d2: W-1 59, W-2 97, W-3 27, W-4 42 (items in force: checker/items.json). 247/254 stage-1 entries referenced; unreferenced: 2, 3 (process), 23, 32 (harness isolated mode), 35 (from stage 2), 219, 251 (permissions).
