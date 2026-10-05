# Liveness replay of the submitted run (tools/liveness.py, added after the run)

Command: `python3 tools/liveness.py room.json --until 2026-10-04T19:00:00Z` (19:00Z = the band's 14:00 CDT stage-4 cut D-26). Each line is the minute a watchdog polling once a minute would first have reported a stall: the whole room quiet for 30 min while a seat still owed a reply.

```
2026-10-03T17:20:54Z Coordinator owes the dispatch since 2026-10-03T16:49:58Z, silent since 2026-10-03T16:49:58Z (156 min)
2026-10-04T00:18:54Z Adversary owes Checker since 2026-10-03T23:00:58Z, silent since 2026-10-03T23:00:58Z (77 min)
2026-10-04T00:18:54Z Checker owes Coordinator since 2026-10-03T23:44:59Z, silent since 2026-10-03T23:46:15Z (32 min)
2026-10-04T00:18:54Z Coordinator owes Builder since 2026-10-03T23:47:08Z, silent since 2026-10-03T23:48:21Z (30 min)
2026-10-04T08:46:54Z Adversary owes Checker since 2026-10-04T07:36:16Z, silent since 2026-10-04T08:11:16Z (648 min)
2026-10-04T08:46:54Z Builder-Two owes Coordinator since 2026-10-04T07:55:20Z, silent since 2026-10-04T07:55:26Z (664 min)
2026-10-04T08:46:54Z Builder owes Coordinator since 2026-10-04T08:10:46Z, silent since 2026-10-04T08:11:28Z (648 min)
2026-10-04T08:46:54Z Coordinator owes Checker since 2026-10-04T08:16:34Z, silent since 2026-10-04T08:16:46Z (643 min)
```
