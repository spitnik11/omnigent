"""Activity feed/transcript stress self-check. Run: python test_activity.py"""
import tempfile
from collections import defaultdict, deque
from pathlib import Path

from omnigent.workflow.activity import TranscriptStore, normalize
from omnigent.workflow.webapi import FEED_LIMIT, REPLAY_LIMIT, Runner
from omnigent.web import PAGE


def main():
    runner = object.__new__(Runner)
    runner.feeds = defaultdict(lambda: deque(maxlen=FEED_LIMIT))
    runner.sequences = defaultdict(int)
    import threading
    runner.feed_lock = threading.Lock()
    runner.transcripts = TranscriptStore(Path(tempfile.mkdtemp()) / "logs")
    for i in range(20_000):
        runner._push("run_stress", {"type": "output", "agent": "codex",
                                    "task": "task", "line": f"line {i}"})
    assert len(runner.feeds["run_stress"]) == FEED_LIMIT
    assert runner.sequences["run_stress"] == 20_000
    replay = runner.replay("run_stress")
    assert len(replay) == REPLAY_LIMIT + 1 and replay[0]["synthetic"]
    assert "19200 earlier" in replay[0]["line"]
    tail = runner.replay("run_stress", 19_995)
    assert [r["seq"] for r in tail] == list(range(19_996, 20_001))
    page = runner.transcripts.page("run_stress", before=10, limit=3)
    assert [r["seq"] for r in page["items"]] == [7, 8, 9]
    restarted = object.__new__(Runner)
    restarted.feeds = defaultdict(lambda: deque(maxlen=FEED_LIMIT))
    restarted.sequences = defaultdict(int)
    restarted.feed_lock = threading.Lock()
    restarted.transcripts = runner.transcripts
    restored = restarted.replay("run_stress")
    assert len(restored) == REPLAY_LIMIT + 1 and restarted.sequences["run_stress"] == 20_000
    assert normalize({"type": "output", "line": "\x1b[33m\x1b[0m"}) is None
    tool = normalize({"type": "output", "agent": "grok", "line": "→ Read file.py"})
    assert tool["kind"] == "tool" and "\x1b" not in tool["line"]
    for required in ("feed_batch", "requestAnimationFrame", "DocumentFragment",
                     "aria-expanded", "Collapse completed", "Load earlier"):
        assert required in PAGE, required
    print("activity stress self-check ok: 20000 persisted, feed/replay bounded")


if __name__ == "__main__":
    main()
