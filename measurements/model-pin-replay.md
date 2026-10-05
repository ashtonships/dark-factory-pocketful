# Model-pin replay of the submitted run (tools/model_pin.py, added after the run)

Command: `python3 tools/model_pin.py --cwd <band-work> --since 2026-10-03T16:49:58Z --until 2026-10-04T08:20:00Z --room room.json` (exit 1).

```
pins: Adversary=gpt-6.1-sol, Builder-Two=claude-opus-5-5, Builder=gpt-6.1-sol, Checker=claude-opus-5-5, Coordinator=claude-opus-5-5
MISMATCH Builder: pinned gpt-6.1-sol, ran gpt-6-sol for 1 turn(s), 2,620 output tokens, 2026-10-03T19:57:53.297Z to 2026-10-03T20:02:09.885Z
MISMATCH Adversary: pinned gpt-6.1-sol, ran gpt-6-sol for 1 turn(s), 178 output tokens, 2026-10-03T20:03:20.420Z to 2026-10-03T20:03:44.048Z
MISMATCH Builder: pinned gpt-6.1-sol, ran gpt-6-sol for 1 turn(s), 44,505 output tokens, 2026-10-03T20:06:16.563Z to 2026-10-03T20:37:50.172Z
ROOM ERROR 2026-10-03T20:04:53.789Z Builder: error: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."}}
ROOM ERROR 2026-10-03T20:05:53.708Z Adversary: error: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."}}
ROOM ERROR 2026-10-03T20:07:01.725Z Adversary: error: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."}}
ROOM ERROR 2026-10-03T20:18:33.088Z Adversary: error: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."}}
ROOM ERROR 2026-10-03T20:38:25.558Z Builder: error: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account."}}
```
