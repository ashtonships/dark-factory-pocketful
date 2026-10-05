# Seat usage, 2026-10-03T16:49:58.000Z to 2026-10-04T08:20:00.000Z

cwd `/Users/ashton/DarkFactory/band-work`; allowed models: claude-opus-5-5, gpt-6.1-sol

| Seat | Provider | Models (turns) | Input | Cache write | Cached input | Output | Sessions |
|---|---|---|---:|---:|---:|---:|---:|
| Coordinator | claude | claude-opus-5-5 (366) | 736 | 860,422 | 70,238,227 | 236,326 | 4 |
| Builder | codex | gpt-6-sol (2) ⚠, gpt-6.1-sol (38) | 1,972,532 | 0 | 65,750,272 | 350,188 | 5 |
| Builder-Two | claude | claude-opus-5-5 (364) | 730 | 1,134,229 | 81,029,978 | 382,602 | 3 |
| Checker | claude | claude-opus-5-5 (352) | 720 | 1,347,259 | 84,933,488 | 319,648 | 3 |
| Adversary | codex | gpt-6-sol (1) ⚠, gpt-6.1-sol (29) | 1,397,124 | 0 | 35,424,000 | 157,155 | 2 |
| unattributed | claude | claude-opus-5-5 (42) | 84 | 376,688 | 919,708 | 13,633 | 14 |
| **Total** | | | 3,371,926 | 3,718,598 | 338,295,673 | 1,459,552 | 31 |

Off-allowlist turns: 3
- Builder (codex): gpt-6-sol, 1 turns, output 2,620, 2026-10-03T19:57:53.297Z to 2026-10-03T20:02:09.885Z
- Adversary (codex): gpt-6-sol, 1 turns, output 178, 2026-10-03T20:03:20.420Z to 2026-10-03T20:03:44.048Z
- Builder (codex): gpt-6-sol, 1 turns, output 44,505, 2026-10-03T20:06:16.563Z to 2026-10-03T20:37:50.172Z
Unattributed sessions: 14
- claude `09c9b79f-1cbf-4d41-b128-c6e6f9d0eaaf.jsonl`: no agent name or seat mandate found
- claude `24093fe1-54b4-498f-90aa-a00438cf4287.jsonl`: no agent name or seat mandate found
- claude `25801d28-2f46-4abb-9c7f-65ecfcd903b8.jsonl`: no agent name or seat mandate found
- claude `3b89ba36-1b2b-4900-aef1-26ff0029099c.jsonl`: no agent name or seat mandate found
- claude `8c66e11c-3196-40e4-b3f5-604573843bfb.jsonl`: no agent name or seat mandate found
- claude `96a45ed5-e3ff-4e8b-bf5f-25be41059837.jsonl`: no agent name or seat mandate found
- claude `d7e25060-ee83-46e5-a134-c5184a90ad45.jsonl`: no agent name or seat mandate found
- claude `153eaaa6-4106-422c-949e-4b9f22bc2092.jsonl`: no agent name or seat mandate found
- claude `ba3cf5b9-d267-4248-badc-99e62de45a40.jsonl`: no agent name or seat mandate found
- claude `d936c474-7974-4d9b-bee0-a1b86ed81c29.jsonl`: no agent name or seat mandate found
- claude `ea3802ad-498d-494f-bd83-303278a20fe6.jsonl`: no agent name or seat mandate found
- claude `002fbe45-ccb3-4ef2-8797-4a50ea304505.jsonl`: no agent name or seat mandate found
- claude `d2210c3b-f943-44a5-ad4e-4ebc9d166d1c.jsonl`: no agent name or seat mandate found
- claude `ee91922e-e420-458b-9c7c-1c026152e5bc.jsonl`: no agent name or seat mandate found

- input = uncached input; cache_write = Claude cache creation; cached_input = read from cache; output includes reasoning tokens
- Claude turns = assistant API responses (deduplicated by message id); Codex turns = turn_context records in the window

