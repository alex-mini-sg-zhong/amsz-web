from __future__ import annotations

import argparse

import uvicorn

from app.api.app import create_app
from app.core.config import get_settings
from app.core.app_logging import configure_logging, get_logger
from app.runtime.combined import CombinedRunner
from app.worker.runner import WorkerRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task service runtime")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    subparsers.add_parser("api", help="Run FastAPI server")

    worker_parser = subparsers.add_parser("worker", help="Run task worker")
    worker_parser.add_argument("--queue", dest="queue_name", default=None)
    worker_parser.add_argument("--concurrency", dest="concurrency", type=int, default=None)

    combined_parser = subparsers.add_parser("combined", help="Run API and worker together")
    combined_parser.add_argument("--queue", dest="queue_name", default=None)
    combined_parser.add_argument("--concurrency", dest="concurrency", type=int, default=None)

    return parser


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger("app.main")

    parser = build_parser()
    args = parser.parse_args()

    try:
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
