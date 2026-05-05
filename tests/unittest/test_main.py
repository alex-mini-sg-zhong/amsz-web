from __future__ import annotations

import sys

from app import main


def test_main_handles_worker_keyboard_interrupt(monkeypatch, caplog) -> None:
    monkeypatch.setattr(sys, "argv", ["app.main", "worker"])

    class FakeWorkerRunner:
        def __init__(self, queue_name: str, concurrency: int) -> None:
            self.queue_name = queue_name
            self.concurrency = concurrency

        def run_forever(self) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(main, "WorkerRunner", FakeWorkerRunner)

    with caplog.at_level("INFO"):
        main.main()

    assert "Service stopped by user interrupt" in caplog.text
