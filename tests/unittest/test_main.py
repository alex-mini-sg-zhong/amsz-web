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
    monkeypatch.setattr(main, "_run_startup_version_check", lambda: None)

    with caplog.at_level("INFO"):
        main.main()

    assert "Service stopped by user interrupt" in caplog.text


def test_main_dispatches_migrate_without_loading_runtime_settings(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["app.main", "migrate"])
    called = {"migrate": 0}

    def fail_load_runtime_settings():
        raise AssertionError("runtime settings should not be loaded for migrate")

    def fake_run_migration() -> None:
        called["migrate"] += 1

    monkeypatch.setattr(main, "load_runtime_settings", fail_load_runtime_settings)
    monkeypatch.setattr(main, "run_migration", fake_run_migration)

    main.main()

    assert called["migrate"] == 1
