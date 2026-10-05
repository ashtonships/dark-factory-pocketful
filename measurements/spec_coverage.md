# Spec coverage (tools/spec_coverage.py, measured 5 Oct after the run)

Command: `python3 tools/spec_coverage.py --spec <kit>/spec --ledger ledger/pocketful.md --checks checker --format markdown` (`<kit>` = the event kit's pocketful spec folder: stage-1.md … stage-4.md).

| Measure | Covered | Total | Rate |
|---|---:|---:|---:|
| Ledger completeness (entries + waivers) | 656 | 656 | 100% |
| Checker-authored check-reference coverage of entries | 609 | 637 | 96% |
| Obligations with checker-authored check references | 600 | 656 | 91% |
| CSV-asserted references (unverified) | 0 | 637 | 0% |

Per stage: every specification sentence is ledgered (an entry quoting it, or a waiver for a sentence with no behaviour such as a stage introduction). An obligation counts as checked when a check the Checker wrote from the specification names its entry.

| Stage | Sentences | Waived (no behaviour) | Obligations | With a Checker-written check |
|---|---:|---:|---:|---:|
| 1 | 273 | 21 | 252 | 246 (98%) |
| 2 | 222 | 11 | 211 | 204 (97%) |
| 3 | 116 | 7 | 109 | 109 (100%) |
| 4 | 45 | 0 | 45 | 41 (91%) |
| 1-3 (submitted) | 611 | 39 | 572 | 559 (98%) |

For comparison, the shipped checks for stages 1-3 number 188. Stage 4 was ledgered and checked but never accepted, so it is not submitted.
