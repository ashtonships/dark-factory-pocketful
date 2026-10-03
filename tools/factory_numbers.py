#!/usr/bin/env python3
"""Compute factory measurements from local git history and saved evidence."""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable

import room_audit


ZERO_HASH = "0" * 64
WORK_ITEM = re.compile(r"\bW-\d+[a-z]?\b")
MENTION = re.compile(r"@\[\[([^\[\]]+)\]\]")
REJECT = re.compile(r"\breject\w*", re.IGNORECASE)


class Git:
    """Read-only git commands with a pinned tip and no lazy network fetching."""

    def __init__(self, repo: str | Path):
        self.repo = Path(repo).resolve()
        if not self.repo.is_dir():
            raise ValueError(f"missing repository: {self.repo}")
        self.env = dict(os.environ)
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_NAMESPACE"):
            self.env.pop(key, None)
        self.env.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1",
                        GIT_ALLOW_PROTOCOL="", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
        bare = self.run("rev-parse", "--is-bare-repository").strip() == b"true"
        if not bare and Path(self.run("rev-parse", "--show-toplevel").decode().strip()).resolve() != self.repo:
            raise ValueError(f"not a repository root: {self.repo}")

    def run(self, *args: str) -> bytes:
        try:
            result = subprocess.run(
                ["git", "--no-pager", "-C", str(self.repo), "-c", "core.fsmonitor=false", *args],
                env=self.env, capture_output=True, check=False)
        except OSError as exc:
            raise ValueError(f"cannot run git for {self.repo}: {exc}") from exc
        if result.returncode:
            raise ValueError(f"git in {self.repo}: {result.stderr.decode('utf-8', errors='replace').strip()}")
        return result.stdout

    def stage_trees(self, sha: str) -> dict[str, str]:
        trees = {}
        for entry in self.run("ls-tree", "-z", sha).split(b"\0"):
            if not entry:
                continue
            metadata, path = entry.split(b"\t", 1)
            _, kind, tree = metadata.decode().split()
            name = path.decode("utf-8")
            if kind == "tree" and re.fullmatch(r"stage-[1-9]", name):
                trees[name] = tree
        return trees

    def numstat(self, sha: str) -> tuple[int, int]:
        # NUL records preserve tabs/newlines in filenames; renames have two extra paths.
        tokens = iter(self.run("log", "-1", "--no-merges", "--numstat", "--find-renames", "-z", "--format=",
                               "--no-ext-diff", "--no-textconv", sha, "--").split(b"\0"))
        added = removed = 0
        for token in tokens:
            if not token:
                continue
            plus, minus, path = token.split(b"\t", 2)
            added += 0 if plus.strip() == b"-" else int(plus)
            removed += 0 if minus.strip() == b"-" else int(minus)
            if path == b"":
                next(tokens)
                next(tokens)
        return added, removed


def git_report(repo: str | Path, branch: str = "main") -> dict:
    git = Git(repo)
    tip = git.run("rev-parse", "--verify", "--end-of-options", branch + "^{commit}").decode().strip()
    fields = git.run("log", "--reverse", "--topo-order", "-z",
                     "--format=%H%x00%an%x00%aI%x00%cI%x00%P%x00%s", tip, "--").decode("utf-8").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 6:
        raise ValueError("cannot parse git commit metadata")
    commits = []
    authors: dict[str, dict] = {}
    trees = {}
    for offset in range(0, len(fields), 6):
        sha, author, author_time, stamp, parents, subject = fields[offset:offset + 6]
        parents = parents.split()
        is_merge = len(parents) > 1
        added, removed = (0, 0) if is_merge else git.numstat(sha)
        commit = {"sha": sha, "author": author, "time": stamp, "author_time": author_time,
                  "parents": parents, "subject": subject, "is_merge": is_merge,
                  "lines_added": added, "lines_removed": removed}
        commits.append(commit)
        trees[sha] = git.stage_trees(sha)
        totals = authors.setdefault(author, {"commits": 0, "merge_commits": 0,
                                            "lines_added": 0, "lines_removed": 0})
        totals["merge_commits" if is_merge else "commits"] += 1
        totals["lines_added"] += added
        totals["lines_removed"] += removed
    totals = {key: sum(author[key] for author in authors.values())
              for key in ("commits", "merge_commits", "lines_added", "lines_removed")}
    for author in authors.values():
        author["commit_share_percent"] = round(100 * author["commits"] / totals["commits"], 2) if totals["commits"] else 0.0
        author["added_lines_share_percent"] = round(100 * author["lines_added"] / totals["lines_added"], 2) if totals["lines_added"] else 0.0
    first_parent = set(git.run("rev-list", "--first-parent", tip, "--").decode().splitlines())
    stages = {}
    tree_changes = []
    folders = sorted({folder for snapshot in trees.values() for folder in snapshot})
    for folder in folders:
        changes = []
        for commit in commits:
            parent = commit["parents"][0] if commit["parents"] else None
            if parent is not None and parent not in trees:
                raise ValueError(f"incomplete git history: missing parent {parent}")
            before = trees[parent].get(folder) if parent else None
            after = trees[commit["sha"]].get(folder)
            if before != after:
                changes.append({"sha": commit["sha"], "time": commit["time"], "author": commit["author"],
                                "subject": commit["subject"], "is_merge": commit["is_merge"],
                                "before_tree": before, "after_tree": after,
                                "first_parent": commit["sha"] in first_parent})
        tree_changes.extend({"folder": folder, "stage": int(folder[-1]), **change} for change in changes)
        if folder not in trees[tip]:
            continue
        first = changes[0]
        main_changes = [change for change in changes if change["first_parent"]]
        stages[folder] = {"stage": int(folder[-1]), "tip_tree": trees[tip][folder],
                          "first_touch": {key: first[key] for key in ("time", "sha", "author")},
                          "commits_by_author": dict(sorted(Counter(change["author"] for change in changes).items())),
                          "first_parent_tree_changes": len(main_changes),
                          "changes": changes}
    return {"branch": branch, "tip_sha": tip, "totals": totals,
            "authors": dict(sorted(authors.items())), "stages": stages,
            "commits": commits, "stage_tree_changes": tree_changes,
            "reopens": {"count": 0, "items": []},
            "time_basis": "committer time; author_time is also retained",
            "first_touch_definition": "first stage tree change in reverse topological history",
            "stage_touch_definition": "stage tree differs from the first parent, including root creation and merges"}


def _read_input(path: str | Path, role: str, files: list[dict], name: str | None = None) -> bytes:
    path = Path(path).resolve()
    try:
        contents = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read {role} {path}: {exc}") from exc
    entry = {"role": role, "path": str(path), "sha256": hashlib.sha256(contents).hexdigest()}
    if name is not None:
        entry["name"] = name
    files.append(entry)
    return contents


def json_lines(contents: bytes, path: str | Path) -> list[tuple[int, dict]]:
    records = []
    for line, text in enumerate(contents.decode("utf-8").splitlines(), 1):
        if not text.strip():
            continue
        try:
            record = json.loads(text)
        except ValueError as exc:
            raise ValueError(f"invalid JSON in {path}, line {line}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"expected an object in {path}, line {line}")
        records.append((line, record))
    return records


def receipt_hash(receipt: dict) -> str:
    body = {key: value for key, value in receipt.items() if key != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _minutes(start: str | None, end: str) -> float | None:
    return (room_audit.parse_time(end) - room_audit.parse_time(start)).total_seconds() / 60 if start else None


def receipt_report(records: list[tuple[int, dict]], dispatch_time: str | None = None,
                   supplied: bool = True) -> dict:
    previous_hash = ZERO_HASH
    broken = None
    counts = {"total": len(records), "green": 0, "red": 0}
    per_stage = {}
    per_level = {}
    first_green = {}
    items = []
    for expected_seq, (line, receipt) in enumerate(records, 1):
        digest = receipt_hash(receipt)
        reason = None
        if receipt.get("hash") != digest:
            reason = "hash does not match receipt contents"
        elif receipt.get("prev_hash") != previous_hash:
            reason = "prev_hash does not match previous receipt"
        elif type(receipt.get("seq")) is not int or receipt["seq"] != expected_seq:
            reason = f"seq must be {expected_seq}"
        if reason and broken is None:
            broken = {"line": line, "reason": reason, "expected_hash": digest,
                      "actual_hash": receipt.get("hash")}
        previous_hash = receipt.get("hash")
        if type(receipt.get("schema")) is not int or receipt["schema"] != 1 or type(receipt.get("stage")) is not int:
            raise ValueError(f"invalid receipt schema or stage on line {line}")
        if any(not isinstance(receipt.get(key), str) or not receipt[key]
               for key in ("rev", "checks_rev", "stage_tree")):
            raise ValueError(f"invalid or missing receipt revision on line {line}")
        if not isinstance(receipt.get("reasons"), list) or not all(isinstance(reason, str) for reason in receipt["reasons"]):
            raise ValueError(f"invalid or missing receipt reasons on line {line}")
        verdict, level = receipt.get("verdict"), receipt.get("level")
        if verdict not in ("green", "red") or level not in ("stage", "item"):
            raise ValueError(f"invalid receipt verdict or level on line {line}")
        room_audit.parse_time(receipt.get("time"))
        if not isinstance(receipt.get("steps"), list) or not all(isinstance(step, dict) for step in receipt["steps"]):
            raise ValueError(f"invalid receipt steps on line {line}")
        for step in receipt["steps"]:
            if (not isinstance(step.get("name"), str) or not step["name"]
                    or type(step.get("ok")) is not bool or type(step.get("seconds")) not in (int, float)):
                raise ValueError(f"invalid receipt step fields on line {line}")
        stage = str(receipt["stage"])
        counts[verdict] += 1
        stage_counts = per_stage.setdefault(stage, {"total": 0, "green": 0, "red": 0, "levels": {}})
        stage_counts["total"] += 1
        stage_counts[verdict] += 1
        level_counts = stage_counts["levels"].setdefault(level, {"total": 0, "green": 0, "red": 0})
        level_counts["total"] += 1
        level_counts[verdict] += 1
        all_level = per_level.setdefault(level, {"total": 0, "green": 0, "red": 0})
        all_level["total"] += 1
        all_level[verdict] += 1
        items.append({"line": line, "receipt": receipt})
        if verdict == "green" and level == "stage":
            old = first_green.get(stage)
            if old is None or room_audit.parse_time(receipt["time"]) < room_audit.parse_time(old[1]["time"]):
                first_green[stage] = (line, receipt)
    stages = {}
    for stage, (line, receipt) in sorted(first_green.items(), key=lambda item: int(item[0])):
        harness = next((step.get("counts") for step in receipt["steps"] if step.get("name") == "harness"), None)
        checker = next((step.get("counts") for step in receipt["steps"] if step.get("name") == "checker"), None)
        own_suite = harness.get(stage) if isinstance(harness, dict) else None
        denominator = own_suite.get("total") if isinstance(own_suite, dict) else None
        numerator = checker.get("passed") if isinstance(checker, dict) else None
        multiplier = (numerator / denominator if isinstance(numerator, (int, float))
                      and isinstance(denominator, (int, float)) and denominator > 0 else None)
        previous_stage = first_green.get(str(int(stage) - 1))
        stages[stage] = {"first_green_time": receipt["time"], "receipt_line": line,
                         "receipt_seq": receipt.get("seq"), "receipt_hash": receipt.get("hash"),
                         "rev": receipt.get("rev"), "stage_tree": receipt.get("stage_tree"),
                         "harness_counts": harness, "checker_counts": checker,
                         "checker_multiplier": multiplier,
                         "minutes_from_dispatch": _minutes(dispatch_time, receipt["time"]),
                         "minutes_since_previous_stage": _minutes(previous_stage[1]["time"] if previous_stage else None,
                                                                   receipt["time"])}
    return {"chain_ok": broken is None if supplied else None,
            "first_broken_line": broken["line"] if broken else None, "chain_error": broken,
            "counts": counts, "per_stage": per_stage, "per_level": per_level,
            "dispatch_time": dispatch_time, "stages": stages, "items": items}


def find_reopens(git: dict, receipts: dict) -> dict:
    items = []
    for change in git["stage_tree_changes"]:
        green = receipts["stages"].get(str(change["stage"]))
        if green is None:
            continue
        if change["first_parent"] and room_audit.parse_time(green["first_green_time"]) < room_audit.parse_time(change["time"]):
            items.append({**change, "green_receipt_line": green["receipt_line"],
                          "green_receipt_time": green["first_green_time"],
                          "green_receipt_hash": green["receipt_hash"]})
    items.sort(key=lambda item: (room_audit.parse_time(item["time"]), item["sha"], item["stage"]))
    return {"count": len(items), "items": items}


def build_report(repo: str | Path, branch: str = "main", room: str | Path | None = None,
                 receipts: str | Path | None = None, refusals: str | Path | None = None,
                 forbidden: Iterable[str] = (), builders: Iterable[str] | None = None,
                 attachments: Iterable[str] = ()) -> dict:
    git = git_report(repo, branch)
    files = []
    room_data = None
    if room is not None:
        contents = _read_input(room, "room", files)
        records = room_audit.load_messages([room])
        if Path(room).read_bytes() != contents:
            raise ValueError(f"room changed while being read: {room}")
        room_data = room_report(records, git, forbidden, builders)
        room_data["input"]["files"] = [str(Path(room).resolve())]
    dispatch_time = room_data["dispatch_time"] if room_data else None
    receipt_records = json_lines(_read_input(receipts, "receipts", files), receipts) if receipts is not None else []
    receipt_data = receipt_report(receipt_records, dispatch_time, supplied=receipts is not None)
    git["reopens"] = find_reopens(git, receipt_data)
    refusal_records = json_lines(_read_input(refusals, "refusals", files), refusals) if refusals is not None else []
    for line, refusal in refusal_records:
        if not all(key in refusal for key in ("time", "ref", "old", "new", "stage", "tree", "reason")):
            raise ValueError(f"invalid refusal on line {line}")
        room_audit.parse_time(refusal["time"])
    attachment_data = {}
    for attachment in attachments:
        name, separator, path = attachment.partition("=")
        if not separator or not name.strip() or not path:
            raise ValueError("--attach requires NAME=FILE.json")
        if name in attachment_data:
            raise ValueError(f"duplicate attachment name: {name}")
        contents = _read_input(path, "attachment", files, name)
        try:
            document = json.loads(contents.decode("utf-8"))
        except ValueError as exc:
            raise ValueError(f"invalid JSON attachment {path}: {exc}") from exc
        attachment_data[name] = {"path": str(Path(path).resolve()), "sha256": files[-1]["sha256"], "document": document}
    return {
        "inputs": {"repo": str(Path(repo).resolve()), "branch": branch, "repo_tip_sha": git["tip_sha"],
                   "room": str(Path(room).resolve()) if room is not None else None,
                   "receipts": str(Path(receipts).resolve()) if receipts is not None else None,
                   "refusals": str(Path(refusals).resolve()) if refusals is not None else None,
                   "files": files},
        "git": git, "receipts": receipt_data,
        "refusals": {"count": len(refusal_records), "items": [{"line": line, "refusal": obj} for line, obj in refusal_records]},
        "room": room_data, "attachments": attachment_data,
    }


def room_report(records: Iterable[dict], git: dict, forbidden: Iterable[str] = (),
                builders: Iterable[str] | None = None) -> dict:
    records = list(records)
    report = room_audit.audit(records, forbidden, [], builders)
    report["dispatch_time"] = report["dispatch"]["time"] if report["dispatch"] else None
    seats = {record["sender_id"]: record["sender_name"] for record in records if record["sender_id"]}
    pairs = {}
    handoffs = []
    rejections = []
    for record in records:
        if record["sender_type"] != "agent" or record["message_type"] != "text":
            continue
        content = room_audit.content_text(record["content"])
        sender = record["sender_name"]
        for addressee_id in sorted((set(MENTION.findall(content)) & seats.keys()) - {record["sender_id"]}):
            pair = pairs.setdefault((record["sender_id"], addressee_id),
                                    {"sender": sender, "sender_id": record["sender_id"],
                                     "addressee": seats.get(addressee_id), "addressee_id": addressee_id,
                                     "count": 0, "message_ids": []})
            pair["count"] += 1
            pair["message_ids"].append(record["id"])
            handoffs.append({"id": record["id"], "time": record["time"], "sender": sender,
                             "sender_id": record["sender_id"], "addressee": seats.get(addressee_id),
                             "addressee_id": addressee_id, "excerpt": content[:120]})
        if REJECT.search(content):
            work_items = sorted(set(WORK_ITEM.findall(content)))
            matching_commits = []
            for commit in git["commits"]:
                if commit["is_merge"] or room_audit.parse_time(commit["time"]) <= room_audit.parse_time(record["time"]):
                    continue
                named = sorted(set(WORK_ITEM.findall(commit["subject"])) & set(work_items))
                if named:
                    matching_commits.append({**{key: commit[key] for key in ("sha", "time", "author", "subject")},
                                             "work_item_ids": named})
            rejections.append({"id": record["id"], "time": record["time"], "sender": sender,
                               "work_item_ids": work_items, "excerpt": content[:120],
                               "changed_code": bool(matching_commits), "matching_commits": matching_commits})
    report["handoffs"] = {"heuristic": True,
                          "definition": "agent text containing another known seat's @[[id]]; once per text and pair of seat ids",
                          "count": len(handoffs), "pairs": [pairs[key] for key in sorted(pairs)], "items": handoffs}
    report["rejections"] = {"heuristic": True,
                            "definition": "agent text with a word starting reject; changed_code means a later non-merge subject names an extracted work-item id",
                            "count": len(rejections), "changed_code_count": sum(item["changed_code"] for item in rejections),
                            "items": rejections}
    return report


def _handoff_rows(pairs: Iterable[dict]) -> Iterable[list]:
    for pair in pairs:
        yield [pair["sender"], pair["addressee"], pair["addressee_id"], pair["count"], ", ".join(pair["message_ids"])]


def _rejection_rows(items: Iterable[dict]) -> Iterable[list]:
    for item in items:
        yield [item["id"], item["time"], item["sender"], ", ".join(item["work_item_ids"]),
               item["changed_code"], ", ".join(commit["sha"] for commit in item["matching_commits"])]


def render_markdown(report: dict) -> str:
    table = room_audit.markdown_table
    cell = room_audit.markdown_cell
    compact = lambda obj: json.dumps(obj, ensure_ascii=False, sort_keys=True)
    inputs = report["inputs"]
    git = report["git"]
    receipts = report["receipts"]
    sections = [
        "# Factory numbers",
        "## Inputs\n\n" + table(["Repo", "Branch", "Tip SHA"], [[inputs["repo"], inputs["branch"], inputs["repo_tip_sha"]]])
        + "\n\n" + table(["Role", "Name", "Path", "SHA256"],
            ([item["role"], item.get("name"), item["path"], item["sha256"]] for item in inputs["files"])),
        f"## Git — {cell(inputs['repo'])}, {cell(inputs['branch'])}\n\n"
        + git["time_basis"] + ". " + git["stage_touch_definition"] + ".\n\n"
        + table(["Non-merge commits", "Merge commits", "Added lines", "Removed lines"],
                [[git["totals"][key] for key in ("commits", "merge_commits", "lines_added", "lines_removed")]])
        + "\n\n" + table(["Author", "Non-merge commits", "Merges", "Added", "Removed", "Commit share", "Added-line share"],
            ([name, data["commits"], data["merge_commits"], data["lines_added"], data["lines_removed"],
              f"{data['commit_share_percent']:.2f}%", f"{data['added_lines_share_percent']:.2f}%"]
             for name, data in git["authors"].items())),
        "### Commit evidence\n\n" + table(["SHA", "Time", "Author", "Subject", "Merge", "Added", "Removed"],
            ([commit[key] for key in ("sha", "time", "author", "subject", "is_merge", "lines_added", "lines_removed")]
             for commit in git["commits"])),
        "### Stage folders at the tip\n\n" + table(
            ["Folder", "First time", "First SHA", "First author", "Commits by author", "First-parent tree changes", "Tip tree"],
            ([folder, stage["first_touch"]["time"], stage["first_touch"]["sha"], stage["first_touch"]["author"],
              compact(stage["commits_by_author"]), stage["first_parent_tree_changes"], stage["tip_tree"]]
             for folder, stage in git["stages"].items())),
        f"### Re-opens: {git['reopens']['count']} — git + {cell(inputs['receipts'])}\n\n" + table(
            ["Stage", "SHA", "Time", "Author", "Before tree", "After tree", "Green receipt line", "Green time"],
            ([item[key] for key in ("stage", "sha", "time", "author", "before_tree", "after_tree", "green_receipt_line", "green_receipt_time")]
             for item in git["reopens"]["items"])),
        f"## Receipts — {cell(inputs['receipts'])}\n\n" + table(
            ["Chain OK", "First broken line", "Total", "Green", "Red", "Chain error"],
            [[receipts["chain_ok"], receipts["first_broken_line"], receipts["counts"]["total"],
              receipts["counts"]["green"], receipts["counts"]["red"], compact(receipts["chain_error"])]])
        + "\n\n" + table(["Stage", "Total", "Green", "Red", "Counts by level"],
            ([stage, data["total"], data["green"], data["red"], compact(data["levels"])]
             for stage, data in sorted(receipts["per_stage"].items(), key=lambda item: int(item[0]))))
        + "\n\n" + table(["Level", "Total", "Green", "Red"],
            ([level, data["total"], data["green"], data["red"]] for level, data in sorted(receipts["per_level"].items()))),
        f"### First green stage receipts and wall-clock — dispatch {cell(receipts['dispatch_time'])}\n\n" + table(
            ["Stage", "Time", "Receipt line", "Seq", "Rev", "Harness suites", "Checker", "Multiplier", "Minutes from dispatch", "Minutes since previous stage"],
            ([stage, data["first_green_time"], data["receipt_line"], data["receipt_seq"], data["rev"],
              compact(data["harness_counts"]), compact(data["checker_counts"]), data["checker_multiplier"],
              data["minutes_from_dispatch"], data["minutes_since_previous_stage"]]
             for stage, data in receipts["stages"].items())),
        f"## Refusals: {report['refusals']['count']} — {cell(inputs['refusals'])}\n\n"
        + table(["Line", "Recorded refusal"], ([item["line"], compact(item["refusal"])] for item in report["refusals"]["items"])),
    ]
    room = report["room"]
    if room is not None:
        audit_text = room_audit.render_markdown(room).removeprefix("# Room audit\n\n").replace("## ", "### ")
        sections.append(f"## Room — {cell(inputs['room'])}\n\n" + audit_text.rstrip())
        sections.append(f"### Handoffs (heuristic): {room['handoffs']['count']}\n\n"
                        + room["handoffs"]["definition"] + "\n\n"
                        + table(["Sender", "Addressee", "Addressee ID", "Count", "Message IDs"], _handoff_rows(room["handoffs"]["pairs"])))
        sections.append(f"### Rejections (heuristic): {room['rejections']['count']}; changed code: {room['rejections']['changed_code_count']}\n\n"
                        + room["rejections"]["definition"] + "\n\n"
                        + table(["Id", "Time", "Sender", "Work items", "Changed code", "Matching commits"], _rejection_rows(room["rejections"]["items"])))
    else:
        sections.append("## Room\n\nNo room input supplied.")
    sections.append("## Attachments\n\n" + table(["Name", "Path", "SHA256"],
        ([name, data["path"], data["sha256"]] for name, data in report["attachments"].items())))
    for name, data in report["attachments"].items():
        sections.append(f"### {cell(name)} — {cell(data['path'])}\n\n"
                        + table(["Unchanged JSON document"], [[compact(data["document"])]]))
    return "\n\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--room", type=Path)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--refusals", type=Path)
    parser.add_argument("--forbidden", action="append", default=[])
    parser.add_argument("--builder", action="append")
    parser.add_argument("--attach", action="append", default=[], metavar="NAME=FILE.json")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    options = parser.parse_args(argv)
    try:
        report = build_report(options.repo, options.branch, options.room, options.receipts,
                              options.refusals, options.forbidden, options.builder, options.attach)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        print(f"factory_numbers: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if options.format == "json"
          else render_markdown(report), end="\n" if options.format == "json" else "")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
