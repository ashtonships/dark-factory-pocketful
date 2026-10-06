# Agent Teamwork: the evidence

This page is for judging **Agent Teamwork** (participant guide, "Rubric" and "Agent Teamwork evidence"). Every number
below comes from `room.json` and the Git history in this repository. Each one has the command that measured it. Run
them from the root of a clone that has all six branches (`git fetch origin '+refs/heads/*:refs/heads/*'`).

Room fields used: `insertedAt`, `messageType`, `senderName`, `senderType`, `content`. Mentions look like `@[[uuid]]`.
Times are UTC, as Band recorded them. A room message can be recorded a few seconds to minutes after the commit it
reports.

## (a) Human input: one message, the dispatch

The run has exactly one message from a human: the dispatch, `ce2a5988…`, at 2026-10-03 16:49:58Z. After it, no
human sent anything (0 messages).

```sh
python3 -c "import json;m=json.load(open('room.json'))['messages'];u=[x for x in m if x['senderType']=='User'];print(len(u),u[0]['id'],u[0]['insertedAt'],sum(x['insertedAt']>u[0]['insertedAt'] for x in u))"
# 1 ce2a5988-7e6c-46eb-bd72-0168cd4b0082 2026-10-03T16:49:58.269Z 0
```

## (b) Who did the work

| Seat | Text messages | Share | Non-merge commits on `main` | stage-1 lines | stage-2 lines | stage-3 lines |
|---|---:|---:|---:|---:|---:|---:|
| Coordinator | 132 | 39.3% | 42 (+20 as "Dark Factory band", see (e)) | 0 | 0 | 0 |
| Builder | 62 | 18.5% | 17 | 1,173 (100%) | 1,584 (46.3%) | 1,992 (50.2%) |
| Checker | 56 | 16.7% | 27 | 0 | 0 | 0 |
| Adversary | 48 | 14.3% | 0 (works on branch `adversary`) | 0 | 0 | 0 |
| Builder-Two | 38 | 11.3% | 14 | 0 | 1,834 (53.7%) | 1,976 (49.8%) |
| **Total** | **336** | | 120 seat commits + the "Factory Setup" commits | 1,173 | 3,418 | 3,968 |

The seats split the work like this. Builder wrote stage 1 alone. The two builders split stages 2 and 3 about evenly.
The Checker wrote the checks: 4,968 lines in `checker/`, plus 27 commits. The Coordinator wrote the ledger: 797 lines
in `ledger/` as itself, and 123 more as "Dark Factory band". The Adversary's own scripts are on branch `adversary`.

```sh
# text messages per seat
python3 -c "import json,collections;m=json.load(open('room.json'))['messages'];print(collections.Counter(x['senderName'] for x in m if x['messageType']=='text' and x['senderType']=='Agent'))"
# non-merge commits on main by author
git log main --no-merges --format=%an | sort | uniq -c
# product lines per stage folder, copy-aware (run once per stage folder)
git ls-files -z stage-2 | xargs -0 -n1 git blame -C -C -M --line-porcelain main -- | sed -n 's/^author //p' | sort | uniq -c
```

Use `-C -C -M`. Each stage starts with a builder copying the previous stage folder forward. Plain `git blame` credits
the copied lines to that copy commit, so for stage 3 it shows Builder 3,826 and Builder-Two 142. Builder made the
stage-3 copy commit, `6ffaf19`. The copy-aware blame follows each line back to the seat that wrote it.

Every commit that touches product code can be found in the room. That is 47 non-merge commits on any branch that
touch `stage-*/` or `ui-core/`: Builder 22, Builder-Two 24, and one "Dark Factory band" commit (see (e)). Each one's
7-character sha appears in `room.json`.

```sh
git log --full-history --no-merges --format=%h main builder builder-two checker coordinator adversary -- stage-1 stage-2 stage-3 stage-4 ui-core | while read h; do grep -q "$h" room.json && echo found || echo "MISSING $h"; done | sort | uniq -c
```

## (c) Review changed the work: five chains

Each chain runs from a finding posted in the room, through the ledger, to a fix commit, and then to a re-review or
gate receipt. Receipt times are the `time` field in `receipts/chain.jsonl`.

| # | Finding (room id, time) | Ledger | Fix | Re-review / receipt |
|---|---|---|---|---|
| 1 | Adversary **PF-A1** `d856ef8e` 20:59:32Z and **PF-A2** `bb90999a` 20:59:38Z (3 Oct). A lost payment response showed a confirmed outcome. An edited amount reused the old payment identity. | `c3a68d8` (entry 9009), `d3dd3fc` (9010) | Builder-Two `93f3606` 21:17:42Z, handback `fd2bd76a` | Coordinator asks for a re-review: `93dc1703`. Adversary re-reviews: 11/11 core, 32/32 browser (task update `cebd97ed` 21:50:37Z, room text `a992351e`). Closed in ledger `5226a98`. |
| 2 | Adversary **PF-A5** `74e45227` 01:46:38Z (4 Oct). A non-boolean capture `final` returned 422, not 400. | `aaa6c98` (entry 9018). Coordinator orders the fix: `c7cc4e4d`. | Builder `f60ba6f` 02:04:30Z | Still in force on `main` (`stage-2/server.py` line 635, `stage-3/server.py` line 660). Accepted in stage-2 GATE GREEN #6 (rev `bc4cc1c`, 06:09:50Z). |
| 3 | Builder's broader patch `80c511a` (02:26:54Z) broke stage-1 §11 / D-9. The Coordinator rejects it: `2be13b59` 02:33:41Z. | `597556d` ("revert requested") | Builder reverts with `124477e` 02:52:05Z. The revert keeps PF-A5. | Adversary reviews the revert: `c26ddd5b`. Included in GREEN #6 (`bc4cc1c`). |
| 4 | Checker **GATE RED #3** on `1f882ff`: 50 concurrent logins, slowest 6.09 s against a 5 s limit. Room `c915a0a7` 00:28:39Z, receipt `239bc21`. The Coordinator decides the fix: `cf4d5cb8`. | `a8582cc` | Builder `86a0196` 00:44:15Z (PBKDF2 at 5,000 iterations) | **GATE GREEN #4** at `57cc82e`, 02:59:37Z (receipt `fa85767`, room `bd402564`). |
| 5 | Checker **GATE RED #8** on `2132717`: a token repeated inside one export was accepted on import. Room `02b16d1f` 07:53:50Z. | `96d12ab`, then `d24f489` | Builder-Two `a3f0daa` (stage 3) and `06d4eea` (stage 4), 07:54:26Z, handback `b2f22600` | **GATE GREEN #9**, 08:01:42Z, rev `06d4eea`, receipt `4a88227`, room `e0971d92` |

**About chain 5: this fix is not on `main`.** `a3f0daa` and `06d4eea` exist only on branches `builder` and
`builder-two`. The Checker held the merge on purpose: merging `06d4eea` would have put stage-4 code onto `main` before
stage 4 was accepted. The plan was to merge the fix together with stage 4. The run then stalled (see FACTORY.md), so
that merge never happened. `main`'s `stage-3/` is the tree from receipt #7 (`276ec0a…`), not the tree from #9
(`739ba73…`).

```sh
git show --stat c3a68d8 93f3606 5226a98 | grep -E '^(commit|Author|    )'
git merge-base --is-ancestor 06d4eea main || echo "06d4eea not on main"; git branch --contains 06d4eea
git rev-parse main:stage-3      # 276ec0a8…, the stage_tree of receipt seq 7
python3 -c "import json;[print(r['seq'],r['stage'],r['verdict'],r['rev'][:7],r['stage_tree'][:7],r['time']) for r in map(json.loads,open('receipts/chain.jsonl'))]"
```

## (d) Handoffs carried the whole task

The Coordinator pasted the complete stage specification into the room as direct messages that @mention each seat.
Long specifications went as numbered parts. Every non-empty line of the event's `pocketful/spec/stage-N.md` appears
word for word in the messages listed for that seat. 0 lines are missing in every group.

| Stage | To | Message ids |
|---|---|---|
| 1 | Builder, Builder-Two, Checker, Adversary | `c5ea3cc8`, `9c44dc52`, `affbeb9e` (parts 1-3 of 3; 451 of 451 lines) |
| 2 | Builder-Two, Adversary | `0d11cb4c`, `58b4990c` (parts 1-2; 304 of 304) |
| 2 | Checker | `87025a1b`, `fbd7866c` |
| 2 | Builder | `e0a9950c`, `5fe18219` |
| 3 | Checker, Adversary | `08a9eacd` (139 of 139) |
| 3 | Builder, Builder-Two | `92b7543d` (read-only preview), `6f94bdcb` (go) |
| 4 | Builder (W-11), Builder-Two (W-12), Checker | `2b492fc5`, `731d40b9`, `51fe82ea`. Each contains the task, its ledger entries and all 58 lines of stage-4.md. |

The Adversary got no stage-4 specification. Its stage-4 job was to review W-12, and it stalled before that review.

```sh
# with the event kit checked out next to this repo; run once per group: list the ids, then the spec file
python3 - c5ea3cc8 9c44dc52 affbeb9e ../dark-factory-wearedevs/pocketful/spec/stage-1.md <<'EOF'
import json,sys
m=json.load(open('room.json'))['messages'];ids=sys.argv[1:-1]
txt={l.strip() for x in m if x['id'][:8] in ids for l in x['content'].splitlines()}
spec=[l.strip() for l in open(sys.argv[-1]) if l.strip()]
print(len(spec),'lines,',sum(l not in txt for l in spec),'missing')
EOF
```

## (e) Authorship notes

- **"Dark Factory band" (20 non-merge commits) is the Coordinator.** This is the repository's default identity. The
  Coordinator committed under it from the shared `main` checkout, and twice from its own worktree. For 19 of the 20
  commits, the commit subject appears in a Coordinator `tool_call` in the room. Examples: `fc2a0e2` ← tool call
  `1d999a23` (07:12:37Z); `96d12ab` ← `ed16fafb` (07:53:57Z); `d24f489` ← `cec6307f` (07:55:10Z); `372374e` ←
  `fc7e94e1`, whose tool result prints `372374e`. The 20th, `5985bc7` ("Stage 4 opened"), has no matching tool call
  text, but it came in through the Coordinator's ledger merge `757013c`. After `9a7c654`, the Coordinator commits as
  itself.
- **One of those commits carried product files.** `fc2a0e2` (07:12:37Z, on branch `coordinator`) added
  `stage-3/core.py`, `server.py` and `state.py` together with a ledger line. Its command (tool call `1d999a23`) runs
  `git add ledger/status.md` only. The stage-3 files were already staged in that worktree. They are the builders'
  candidate `5413e25`: identical except 7 lines in `server.py`. Blame gives that commit 0 lines in today's `main`. It
  reached `main` only after receipt #7's merge.
- **"Factory Setup" wrote nothing in any stage folder.** Its commits are the setup before the run (`5bc84fd`:
  mandates, tools, FACTORY.md) and the operator's commits after the run (5 Oct: room.json, measurements, docs and two
  new tools; `git log --author='Factory Setup'`). Their lines are in `room.json`, `tools/`, `mandates/`, `measurements/`, `FACTORY.md`, `README.md`,
  `.gitignore`, `TEAMWORK.md`, `DISPATCH.md`, `docs/` and `receipts/` (1 line). They have 0 lines in `stage-1/`, `stage-2/` or `stage-3/`.

```sh
git log main --no-merges --author='Dark Factory band' --format='%h %s'
git log main --no-merges --author='Factory Setup' --format='%h %ad %s' --date=iso
git ls-files -z stage-1 stage-2 stage-3 | xargs -0 -n1 git blame --line-porcelain main -- | grep -c '^author Factory Setup$'   # 0
```

## (f) Room glossary: entries that can look like human input

- **"steering inbound Band message `<id>` into active turn"**: 365 `task` events. This is Band's runtime delivering
  one seat's message into another seat's Codex or Claude turn that is already running. By the seat that received it:
  Adversary 160, Builder 84, Coordinator 75, Checker 28, Builder-Two 18. By who wrote the delivered message: Coordinator
  228, Checker 49, Builder 44, Adversary 31, Builder-Two 13. Every referenced id resolves to an `Agent` message. 0
  come from the human, and 0 deliver the dispatch.
- **`@ashtonclear/coordinator`** is the Band handle of the **Coordinator seat**. It is not the human. Seats use it to
  acknowledge handoffs.
- **`eaa7b1b9` (19:49:56Z)** is the Coordinator's only message addressed to the human. It is a status note: the run
  started, the ledger was committed, and who has which item. It asks nothing, and no reply came.
- **Codex "initialized codex app-server" / "ready" events** are runtime starts. There are 31 "ready" events. They fall
  into three groups:
  - **19:27–20:06Z:** the first start of each seat, and restarts of Builder and Adversary. These came while the
    operator fixed Band's PATH and pinned the Codex model, after the room's errors at 20:04:53, 20:05:53 and 20:07:01Z.
    No new room message to those seats came before them. Times: Coordinator 19:27:05; Builder 19:57:39, 20:03:51,
    20:05:54; Builder-Two 19:58:45; Checker 20:00:11; Adversary 20:02:47, 20:04:48, 20:06:17.
  - **20:38:04 (Builder):** a restart with no message to that seat before it. This is the operator's restart with the
    model fix.
  - **All 21 others (20:18Z to 08:10Z, including 05:37:42/45 and 06:10:25/27):** each came 2–31 s after another seat
    sent a message that @mentions that seat. That matches the runtime respawning the seat to deliver the message. It
    includes 20:46:35 (Adversary, 4 s after Coordinator message `832fb464`). Band does not record the cause of a
    start, so this is an inference from timing.

```sh
python3 - <<'EOF'
import json,re,collections
m=json.load(open('room.json'))['messages'];by={x['id']:x for x in m}
st=[x for x in m if x['messageType']=='task' and x['content'].startswith('steering inbound Band message')]
src=collections.Counter(by[re.search(r'message (\S{36})',x['content'])[1]]['senderType'] for x in st)
print(len(st),collections.Counter(x['senderName'] for x in st),src)
print([(x['insertedAt'],x['senderName']) for x in m if x['messageType']=='task' and x['content'].strip()=='ready'])
EOF
```

## (g) Operator actions

During the run the operator worked only on infrastructure. They fixed the Band service's PATH and used *Restart
agent*, and they pinned the Codex model. FACTORY.md, section "Operator actions during the run", describes both. The
operator sent no message, approval or hint to any seat, as shown in (a) and (f).
