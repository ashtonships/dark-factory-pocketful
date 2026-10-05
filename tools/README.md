# Factory measurement tools

These Python 3 standard-library tools help audit the ledger, checker references,
possible test fitting, and a sampled set of product faults. Their JSON output is a
trace for review, not proof that the factory met its specification.

Every command below runs from the repository root. Paths outside this repository use
placeholders: `<KIT>` is the event kit (harness, `<KIT>/<track>/spec`,
`<KIT>/<track>/test`), `<WORKSPACE>` is the seats' common working directory (the
parent of the result repository), and `<CHECKS>` is a scratch folder for output. The
examples use this run's own `room.json`, `ledger/`, `checker/`, `receipts/` and
`stage-1/`, so their output reproduces `measurements/`; with `<track>` = `pocketful`
they reproduce this run.

Run `python3 tools/<tool>.py --help` for current CLI options. The tools use
paths supplied by the caller, do not need network access, and do not write to the
input product.

| Tool | What it answers | When |
|---|---|---|
| `gate.py` | is this exact commit acceptable for stage N? (receipt chain, freeze rule) | every acceptance; config in `gate.json`, documented in `gate.example.json` |
| `spec_coverage.py` | does every specification sentence have a ledger entry and a check reference? | each stage, final report |
| `overfit_scan.py` | does product code reuse shipped-test literals? | inside every gate run |
| `seeded_faults.py` | do the checks catch small planted faults? | after a stage is accepted |
| `room_audit.py` | human messages after the dispatch; builder reads of the shipped tests | after the run |
| `factory_numbers.py` | commits, shares, stage timing, receipts, handoffs | after the run |
| `seat_usage.py` | tokens per seat and model, from local session logs | after the run |
| `liveness.py` | which seat owes a reply while the room is silent | during the run (added after the submitted run) |
| `model_pin.py` | did every seat run on its mandate's model? | during the run, before each gate (added after the submitted run) |

## The gate

`gate.py` and its config are described in its own docstring (`python3 tools/gate.py --help`)
and, key by key, in `gate.example.json`; copy that file to `gate.json` and fill it in.

```sh
python3 tools/gate.py run --stage 1 --rev <commit>            # a stage acceptance
python3 tools/gate.py run --stage 2 --rev <commit> --level item  # a work item inside stage 2
python3 tools/gate.py show --last 5
python3 tools/gate.py verify                                   # chain intact; every stage tree main held had a green receipt
```

## Spec ledger and check references

`spec_coverage.py` counts every prose sentence and every table body row outside
fenced code in `.md` and `.txt` specification files. This intentionally includes
descriptive text. A ledger entry must quote a contiguous, normalized span of a
specification obligation. Add an explicit `N/A` waiver quoting a sentence or row
and giving a reason when it does not impose a requirement. Review the extracted
list and the waivers before publishing a completeness rate.

The output distinguishes ledger coverage, waivers, and references in checker-authored
files. A check reference is only a source reference to a ledger ID. It does not prove
that a test passes or asserts the right behavior. The optional CSV input is a list of
**unverified claims** and does not raise a checker-authored coverage rate. The
headline counts obligations with a matching ledger entry that has a checker-authored
reference; it is a check-reference rate, not verified behavioral coverage.

```sh
python3 tools/spec_coverage.py \
  --spec <KIT>/<track>/spec \
  --ledger ledger/<track>.md \
  --checks checker \
  --format markdown
```

`--evidence-csv FILE` may replace `--checks`; such a CSV cannot establish authorship.

For a real run, point `--checks` at the checker's committed files and inspect Git
provenance. Untracked files, hidden folders, and files with any non-Checker author
cannot supply checker-authored references. Check results still need to be recorded
separately. Read the complete specification and ledger alongside the report; parsing
Markdown cannot decide which prose is normative.

## Possible test fitting

`overfit_scan.py` finds identifiers, literals, numbers, and routes in shipped tests
that are absent from the specification and also appear in product files. Each finding
is a review lead, not a finding of misconduct. Numeric comparisons, branch literals,
and routes receive higher severity than generic identifiers. The scanner skips common
syntax, builtins, and likely import names, but it can still miss a hard-coded spec
example or flag legitimate product behavior. In particular, a special case using a
value already present in the spec is outside its detection method.

```sh
python3 tools/overfit_scan.py \
  --spec <KIT>/<track>/spec \
  --tests <KIT>/<track>/test \
  --product stage-1
```

The gate runs exactly this on `stage-N/` and is red on any `high` finding whose token
`gate.json`'s `overfit_allow` does not list with a reason.

Read the surrounding code and the source requirement before deciding any finding.

## Seeded faults

`seeded_faults.py` enumerates mutation candidates in product source, excludes test
paths, samples candidates using a reported seed, and copies the product into isolated
temporary directories. It checks the unmodified baseline, applies one edit per copy,
runs an optional build command before each test command, and rechecks the baseline.
Use `{product}` in an argv element if a command needs the absolute copy path.

```sh
python3 tools/seeded_faults.py \
  --product stage-1 \
  --seed 42 --count 6 --timeout 900 \
  --test-command <KIT>/.venv/bin/python "$PWD/checker/run_checks.py" \
    --stage-dir {product} --stage 1 --out <CHECKS>/mutants
```

This scores the Checker's own checks: `run_checks.py --stage-dir` builds and starts the
mutated copy in Docker, so each mutant takes minutes. Hold the check lock while it runs.

For any non-Python mutation, pass `--build-command` as one quoted command string,
such as `--build-command 'node --check index.js'`. Without it, the tool returns
`build_required` and no rate. Python candidates are AST-validated; pass a build
command as well when the project has additional import or build checks. Build failures
are `invalid` and excluded from the rate's denominator. JSON reports
`candidates_total`, per-kind candidate counts, the sample seed, selected and mutated
files, valid kills, invalid mutants, survivors, and diffs. A failed initial or final
baseline, or an unstable environment, suppresses the rate. The tool starts commands
in its own process group and cleans up that group after each command; inspect any
timed-out or unstable run before relying on the numbers.

The rate applies only to valid sampled edits. It says nothing about mutation sites
not sampled or faults outside the mutation classes. Read survivors and invalid diffs
before deciding what additional checks are needed.

## Recording a real run

Save the three JSON outputs outside any deliverable folder. In `FACTORY.md`,
record the product and checker revisions, exact commands, checker test results, manual
waiver review, scanner decisions, valid mutation denominator, invalid count, and
survivors. Do not label a reference rate as behavioral coverage or a compile failure
as a caught behavioral fault.

Run the tool regression suite with:

```sh
python3 -m unittest discover -s tools/tests
```

Only `liveness.py` and `model_pin.py` have tests in this repository (`tools/tests/`).
The other tools' regression tests and fixtures stayed with the factory's source and
were not copied here.

## `room_audit.py`

Audit saved Band full-session JSON, CLI pages, or arrays of pages/messages. Records
are deduplicated by id and sorted by time, then id. Every counted builder tool call
and every human message after the first human dispatch includes its evidence.
Builder names default to names containing `builder`; repeat `--builder NAME` to
select display names explicitly. Argument values are decoded recursively, including
JSON strings inside JSON strings. A reference to a forbidden path is counted without
inferring what the tool actually read or why it was called.

```sh
python3 tools/room_audit.py room.json \
  --forbidden <KIT>/<track>/test \
  --forbidden-regex '\btest/stage_\d' \
  --builder Builder --builder Builder-Two \
  --format markdown
```

JSON is the default output. At least one absolute
`--forbidden` directory is required by the CLI. Both absolute and `~/` spellings of
a configured path under the home folder match. `--fail-on-reads` and `--fail-on-human`
return 1 when their count is positive; a completed audit otherwise returns 0, and
unreadable or malformed input returns 2. The importable `load_messages(paths)` and
`audit(messages, forbidden, forbidden_regex, builders)` functions do not write files.
API callers may pass an empty forbidden list when only room counts are needed.

## `factory_numbers.py`

Compute factory totals from the history reachable from a result repository's branch,
saved room JSON, gate receipts and hook refusals. The report pins the branch tip SHA
and hashes every supplied input file. Commit, stage-tree and receipt-line evidence
accompanies the totals. All commands are local and read-only; the tool disables git
lazy fetching and optional locks and writes its report to stdout.

```sh
python3 tools/factory_numbers.py --repo . --branch main \
  --room room.json \
  --receipts receipts/chain.jsonl \
  --forbidden <KIT>/<track>/test \
  --builder Builder --builder Builder-Two \
  --format markdown
```

Add `--refusals receipts/refusals.jsonl` when the freeze hook wrote one, and
`--attach NAME=FILE.json` to carry another tool's JSON report along.

Only `--repo` is required; the default branch is `main` and the default format is
JSON. Optional files are read only when supplied. An absent receipt chain has
`chain_ok: null`; a supplied empty chain verifies vacuously. Broken hashes, sequence
numbers and previous-hash links report the first broken physical line and retain the
recorded evidence. They do not change the success exit code. Unreadable or malformed
input, a missing repository, or an unknown branch returns 2.

Author names are taken directly from commits. Added/removed lines and percentage
shares exclude merges; binary files contribute zero lines. Shares are rounded to two
decimal places. Event comparisons use committer time, with author time also retained.
A commit touches a stage when its tree differs from its first parent, including root
creation and merges. First touch is the first such change in reverse topological
history, so a backdated descendant cannot precede its ancestor. Only `stage-1/`
through `stage-9/` directories present at the tip are reported.
The separate first-parent count measures changes on the branch's integration history.

First green **stage-level** receipts supply suite counts, checker counts and stage
timing. Item receipts contribute to receipt counts but do not mark stage completion.
The checker multiplier uses that stage's own harness suite total; missing counts or
a zero denominator produce null. Wall-clock minutes use the room's first human
dispatch; the inter-stage interval uses the preceding numbered stage and is null if
that stage has no green stage receipt. Re-opens list first-parent stage-tree changes
strictly later than the stage's first green stage receipt, including qualifying
deletions even when that stage is absent at the tip. Receipt-derived numbers
remain explicitly accompanied by `chain_ok` when the chain is broken.

The room audit is imported from `room_audit.py`; repeat `--builder NAME` to select
builder display names. Handoffs and rejection follow-ups are labeled **heuristics**.
Repeated mentions of the same known addressee in one text count once for that pair
of seat IDs; self mentions and unknown IDs are excluded. A rejection's `changed_code` means only that a later
non-merge commit subject names an extracted work-item id; its matching commits are
listed. Attachments retain the parsed JSON unchanged under
`attachments.NAME.document`, with the original file's SHA256 and path alongside it.

## `seat_usage.py`

Tokens per seat and model from the local Claude Code transcripts and Codex rollouts of
sessions inside `--cwd`, attributed to a seat by its mandate heading. Only the machine
that ran the seats can reproduce it.

```sh
python3 tools/seat_usage.py --cwd <WORKSPACE> \
  --since 2026-10-03T16:49:58Z --until 2026-10-04T08:20:00Z --format markdown
```

## `liveness.py` (added after the submitted run)

Which seat owes the band a reply and has gone silent. A seat owes a reply from the first
text message that mentions it (the dispatch counts) until it next posts a text. A stall
is reported only when the whole room has been quiet for `--silence` minutes (default 30)
while a seat still owes a reply, and names the seat's last error when that is what it
last sent. It was written on 5 Oct, after the run, because a seat whose turns kept
ending in a provider refusal held the last review of stage 4 and nobody noticed. Read-only.

```sh
python3 tools/liveness.py room.json                              # replay: every stall and when it would have been reported
python3 tools/liveness.py room.json --at 2026-10-04T09:00Z       # state at one moment; exit 1 while a seat is stalled
```

During a run, save the room's pages with `band room messages <ROOM> --json --page N`
and pass the files instead of `room.json`; a non-model watcher can run it every minute
and post the stall to the Coordinator. Replay output for this run:
`measurements/liveness-replay.md`.

## `model_pin.py` (added after the submitted run)

Did every seat run on the model its mandate's `Model:` line names? It reads every turn of
each seat (through `seat_usage.py`'s readers) and exits 1 on any turn on another model;
`--room` also lists room errors that reject a model. It was written on 5 Oct, after the
run, because three Codex turns ran on an unpinned model and only the operator saw it.

```sh
python3 tools/model_pin.py --cwd <WORKSPACE> --since <time of the last receipt> --room room.json
```

The Checker can run it before every gate. Replay output for this run:
`measurements/model-pin-replay.md`.
