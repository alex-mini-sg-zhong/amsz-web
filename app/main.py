from __future__ import annotations

import argparse

import uvicorn

from app.bootstrap.logging import configure_bootstrap_logging, configure_runtime_logging
from app.bootstrap.migration import run_migration
from app.bootstrap.runtime import load_runtime_settings
from app.core.config import DEFAULT_LOG_LEVEL
from app.core.app_logging import get_logger
from app.infrastructure.runtime.combined import CombinedRunner
from app.infrastructure.runtime.worker_runner import WorkerRunner
from app.interfaces.http.app import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task service runtime")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    subparsers.add_parser("api", help="Run FastAPI server")
    subparsers.add_parser("migrate", help="Run schema migrations")

    worker_parser = subparsers.add_parser("worker", help="Run task worker")
    worker_parser.add_argument("--queue", dest="queue_name", default=None)
    worker_parser.add_argument("--concurrency", dest="concurrency", type=int, default=None)

    combined_parser = subparsers.add_parser("combined", help="Run API and worker together")
    combined_parser.add_argument("--queue", dest="queue_name", default=None)
    combined_parser.add_argument("--concurrency", dest="concurrency", type=int, default=None)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    configure_bootstrap_logging(DEFAULT_LOG_LEVEL)
    logger = get_logger("app.main")

    try:
        if args.mode == "migrate":
            run_migration()
            return

        settings = load_runtime_settings()
        configure_runtime_logging(settings)
        logger = get_logger("app.main")

        if args.mode == "api":
            uvicorn.run(
                create_app(),
                host=settings.api_host,
                port=settings.api_port,
                access_log=False,
                log_config=None,
            )
            return

        queue_name = args.queue_name or settings.worker_queue
        concurrency = args.concurrency or settings.worker_concurrency

        if args.mode == "combined":
            runner = CombinedRunner(
                settings=settings,
                queue_name=queue_name,
                concurrency=concurrency,
            )
            runner.run_forever()
            return

        runner = WorkerRunner(queue_name=queue_name, concurrency=concurrency)
        runner.run_forever()
    except KeyboardInterrupt:
        logger.info("Service stopped by user interrupt")
        return


if __name__ == "__main__":
    main()
