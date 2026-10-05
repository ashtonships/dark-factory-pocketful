import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_pin  # noqa: E402


class ModelPinTests(unittest.TestCase):
    def test_pins_come_from_each_mandate_heading_and_model_line(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "builder.md").write_text("Harness: Codex\nModel: gpt-6.1-sol\n\n# Builder\n\nbody\n")
            Path(folder, "notes.md").write_text("# Notes\n")
            self.assertEqual(model_pin.mandate_models(Path(folder)), {"Builder": "gpt-6.1-sol"})

    def test_turns_on_another_model_are_reported_per_seat(self):
        sessions = [{"seat": "Builder", "models": {"gpt-6-sol": {"turns": 1, "output": 2620, "first": "t1", "last": "t2"},
                                                   "gpt-6.1-sol": {"turns": 38, "output": 9, "first": "t3", "last": "t4"}}},
                    {"seat": "Checker", "models": {"claude-opus-5-5": {"turns": 3, "output": 1, "first": "t0", "last": "t5"}}},
                    {"seat": None, "models": {"other": {"turns": 1, "output": 1, "first": "t0", "last": "t0"}}}]
        rows = model_pin.mismatches(sessions, {"Builder": "gpt-6.1-sol", "Checker": "claude-opus-5-5"})
        self.assertEqual([(r["seat"], r["ran"], r["turns"]) for r in rows], [("Builder", "gpt-6-sol", 1)])

    def test_room_errors_rejecting_a_model_are_listed(self):
        room = {"messages": [
            {"insertedAt": "2026-10-03T20:05:07Z", "messageType": "error", "senderName": "Builder",
             "content": "The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."},
            {"insertedAt": "2026-10-03T20:04:53Z", "messageType": "task", "senderName": "Builder",
             "content": "error: The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."},
            {"insertedAt": "2026-10-03T20:07:01Z", "messageType": "task", "senderName": "Adversary",
             "content": "error: The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."},
            {"insertedAt": "2026-10-03T21:00:00Z", "messageType": "error", "senderName": "Checker",
             "content": "workspace routing discovery timed out"}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "room.json")
            path.write_text(json.dumps(room))
            self.assertEqual([e["seat"] for e in model_pin.room_model_errors(path)], ["Builder", "Adversary"])


if __name__ == "__main__":
    unittest.main()
