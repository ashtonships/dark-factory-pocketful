import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import liveness  # noqa: E402

A, B, H = "a" * 8 + "-0000-0000-0000-" + "0" * 12, "b" * 8 + "-0000-0000-0000-" + "0" * 12, "h" * 8 + "-0000-0000-0000-" + "0" * 12


def msg(i, minute, sender, name, kind="text", content="", agent=True):
    return {"id": str(i), "insertedAt": f"2026-10-04T08:{minute:02d}:00Z", "messageType": kind,
            "senderId": sender, "senderName": name, "senderType": "Agent" if agent else "User", "content": content}


def run(rows, at, silence=30):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "room.json"
        path.write_text(json.dumps({"messages": rows}))
        messages = liveness.load([path])
    return liveness.state(messages, liveness.when(at), timedelta(minutes=silence))


class LivenessTests(unittest.TestCase):
    def test_quiet_room_with_held_work_is_a_stall_naming_the_error(self):
        rows = [msg(1, 0, A, "Coordinator", content=f"@[[{B}]] review W-12"),
                msg(2, 1, B, "Adversary", "tool_call", "{}"),
                msg(3, 2, B, "Adversary", "error", "flagged for possible cybersecurity risk")]
        stalled = run(rows, "2026-10-04T08:40:00Z")
        self.assertEqual([r["seat"] for r in stalled], ["Adversary"])
        self.assertIn("cybersecurity", stalled[0]["last_error"])
        self.assertEqual(stalled[0]["owes"], "Coordinator")

    def test_waiting_seat_is_fine_while_the_room_works(self):
        rows = [msg(1, 0, A, "Coordinator", content=f"@[[{B}]] review W-12")]
        rows += [msg(10 + m, m, A, "Coordinator", "tool_call", "{}") for m in range(1, 45)]
        self.assertEqual(run(rows, "2026-10-04T08:45:00Z"), [])

    def test_a_text_reply_settles_the_debt(self):
        rows = [msg(1, 0, A, "Coordinator", content=f"@[[{B}]] review W-12"),
                msg(2, 5, B, "Adversary", content=f"@[[{A}]] no findings")]
        self.assertEqual([r["seat"] for r in run(rows, "2026-10-04T08:50:00Z")], ["Coordinator"])

    def test_human_dispatch_counts_and_short_silence_does_not(self):
        rows = [msg(1, 0, H, "Owner", content=f"@[[{A}]] build it", agent=False),
                msg(2, 0, A, "Coordinator", "thought", "")]
        self.assertEqual(run(rows, "2026-10-04T08:20:00Z"), [])
        stalled = run(rows, "2026-10-04T08:31:00Z")
        self.assertEqual((stalled[0]["seat"], stalled[0]["owes"]), ("Coordinator", "the dispatch"))

    def test_live_page_shape_is_read(self):
        page = {"messages": [{"id": "1", "inserted_at": "2026-10-04T08:00:00Z", "message_type": "text",
                              "sender_id": A, "sender_name": "Coordinator", "sender_type": "Agent",
                              "content": "review", "mention_names": {B: "Adversary"}},
                             {"id": "2", "inserted_at": "2026-10-04T08:01:00Z", "message_type": "tool_call",
                              "sender_id": B, "sender_name": "Adversary", "sender_type": "Agent", "content": "{}"}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "p1.json"
            path.write_text(json.dumps(page))
            messages = liveness.load([path])
        stalled = liveness.state(messages, liveness.when("2026-10-04T08:40:00Z"), timedelta(minutes=30))
        self.assertEqual([r["seat"] for r in stalled], ["Adversary"])


if __name__ == "__main__":
    unittest.main()
