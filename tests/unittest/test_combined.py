from __future__ import annotations

import os
import signal
from collections.abc import Sequence

import pytest

from app.core.config import get_settings
from app.runtime.combined import CombinedRunner


class FakeProcess:
    def __init__(self, pid: int, poll_results: Sequence[int | None] | None = None) -> None:
        self.pid = pid
        self._poll_results = list(poll_results or [None])
        self.sent_signals: list[int] = []
        self.kill_called = False

    def poll(self) -> int | None:
        if len(self._poll_results) > 1:
            return self._poll_results.pop(0)
        return self._poll_results[0]

    def send_signal(self, signum: int) -> None:
        self.sent_signals.append(signum)
        self._poll_results = [0]

    def kill(self) -> None:
        self.kill_called = True
        self._poll_results = [-9]


class FakePopenFactory:
    def __init__(self, processes: list[FakeProcess]) -> None:
        self.processes = processes
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, command: list[str], env: dict[str, str]) -> FakeProcess:
        process = self.processes[len(self.calls)]
        self.calls.append((command, env))
        return process


def test_combined_runner_starts_api_and_worker_with_expected_commands() -> None:
    settings = get_settings()
    processes = [FakeProcess(101), FakeProcess(202)]
    popen_factory = FakePopenFactory(processes)
    runner = CombinedRunner(
        settings=settings,
        queue_name="slow",
        concurrency=3,
        popen_factory=popen_factory,
    )

    runner._start_children()

    assert len(popen_factory.calls) == 2
    assert popen_factory.calls[0][0][-1] == "api"
    assert popen_factory.calls[1][0][-5:] == [
        "worker",
        "--queue",
        "slow",
        "--concurrency",
        "3",
    ]
    assert popen_factory.calls[1][1]["WORKER_ID"] == "worker-test"


def test_combined_runner_passes_current_environment_to_children() -> None:
    settings = get_settings()
    runner = CombinedRunner(settings=settings, queue_name="default", concurrency=2)

    env = runner._build_child_env()

    assert env["WORKER_ID"] == os.environ["WORKER_ID"]
    assert env["POD_NAME"] == os.environ["POD_NAME"]


def test_combined_runner_stops_other_child_when_one_exits() -> None:
    settings = get_settings()
    api_process = FakeProcess(101, poll_results=[12])
    worker_process = FakeProcess(202, poll_results=[None, 0])
    runner = CombinedRunner(
        settings=settings,
        queue_name="default",
        concurrency=2,
        popen_factory=FakePopenFactory([api_process, worker_process]),
    )
    runner.api_process = api_process
    runner.worker_process = worker_process

    with pytest.raises(SystemExit) as exc_info:
        runner._handle_child_exit(api_return_code=12, worker_return_code=None)

    assert exc_info.value.code == 12
    assert worker_process.sent_signals == [signal.SIGTERM]


def test_combined_runner_handle_signal_stops_children() -> None:
    settings = get_settings()
    api_process = FakeProcess(101)
    worker_process = FakeProcess(202)
    runner = CombinedRunner(
        settings=settings,
        queue_name="default",
        concurrency=2,
        popen_factory=FakePopenFactory([api_process, worker_process]),
    )
    runner.api_process = api_process
    runner.worker_process = worker_process

    runner._handle_signal(signal.SIGTERM, None)

    assert api_process.sent_signals == [signal.SIGTERM]
    assert worker_process.sent_signals == [signal.SIGTERM]
