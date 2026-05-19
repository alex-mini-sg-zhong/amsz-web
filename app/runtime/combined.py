from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Mapping
from time import sleep

from app.core.config import RuntimeSettings
from app.core.app_logging import get_logger


class CombinedRunner:
    def __init__(
        self,
        *,
        settings: RuntimeSettings,
        queue_name: str,
        concurrency: int,
        popen_factory: type[subprocess.Popen[bytes]] | object = subprocess.Popen,
        poll_interval_seconds: float = 1.0,
        shutdown_timeout_seconds: float = 10.0,
    ) -> None:
        self.settings = settings
        self.queue_name = queue_name
        self.concurrency = concurrency
        self.popen_factory = popen_factory
        self.poll_interval_seconds = poll_interval_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.logger = get_logger("app.runtime.combined")
        self.api_process: subprocess.Popen[bytes] | None = None
        self.worker_process: subprocess.Popen[bytes] | None = None
        self._stopping = False

    def run_forever(self) -> None:
        self._install_signal_handlers()
        self._start_children()
        self._monitor_children()

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum: int, _frame: object) -> None:
        signal_name = signal.Signals(signum).name
        self.logger.info(f"Received shutdown signal signal={signal_name}")
        self.stop_children(signum)

    def _start_children(self) -> None:
        self.logger.info("Starting combined runtime")
        shared_env = self._build_child_env()
        self.api_process = self._spawn_process(
            name="api",
            command=self._build_api_command(),
            env=shared_env,
        )
        self.worker_process = self._spawn_process(
            name="worker",
            command=self._build_worker_command(),
            env=shared_env,
        )

    def _spawn_process(
        self,
        *,
        name: str,
        command: list[str],
        env: Mapping[str, str],
    ) -> subprocess.Popen[bytes]:
        process = self.popen_factory(command, env=dict(env))
        self.logger.info(
            f"Child process started name={name} pid={process.pid} command={' '.join(command)}"
        )
        return process

    def _build_api_command(self) -> list[str]:
        return [sys.executable, "-m", "app.main", "api"]

    def _build_worker_command(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "app.main",
            "worker",
            "--queue",
            self.queue_name,
            "--concurrency",
            str(self.concurrency),
        ]

    def _build_child_env(self) -> dict[str, str]:
        return dict(os.environ)

    def _monitor_children(self) -> None:
        while True:
            if self.api_process is None or self.worker_process is None:
                raise RuntimeError("Combined runtime children are not started")

            api_return_code = self.api_process.poll()
            worker_return_code = self.worker_process.poll()

            if api_return_code is not None or worker_return_code is not None:
                self._handle_child_exit(
                    api_return_code=api_return_code,
                    worker_return_code=worker_return_code,
                )
                return

            sleep(self.poll_interval_seconds)

    def _handle_child_exit(
        self,
        *,
        api_return_code: int | None,
        worker_return_code: int | None,
    ) -> None:
        if self.api_process is None or self.worker_process is None:
            raise RuntimeError("Combined runtime children are not started")

        if self._stopping:
            self.stop_children(signal.SIGTERM)
            raise SystemExit(0)

        exited_name = "api" if api_return_code is not None else "worker"
        exited_code = api_return_code if api_return_code is not None else worker_return_code
        self.logger.error(
            f"Child process exited unexpectedly name={exited_name} exit_code={exited_code}"
        )
        self.stop_children(signal.SIGTERM)
        raise SystemExit(exited_code or 1)

    def stop_children(self, signum: int) -> None:
        if self._stopping:
            return

        self._stopping = True
        for name, process in (("api", self.api_process), ("worker", self.worker_process)):
            if process is None or process.poll() is not None:
                continue
            signal_name = signal.Signals(signum).name
            self.logger.info(
                f"Forwarding signal to child process name={name} pid={process.pid} "
                f"signal={signal_name}"
            )
            process.send_signal(signum)

        deadline = self.shutdown_timeout_seconds
        while deadline > 0:
            alive = [
                process
                for process in (self.api_process, self.worker_process)
                if process is not None and process.poll() is None
            ]
            if not alive:
                return
            sleep(0.1)
            deadline -= 0.1

        for name, process in (("api", self.api_process), ("worker", self.worker_process)):
            if process is None or process.poll() is not None:
                continue
            self.logger.warning(f"Force killing child process name={name} pid={process.pid}")
            process.kill()
