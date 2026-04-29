from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.setLevel(level.upper())
        return

    logging.basicConfig(
        level=level.upper(),
        format=(
            "%(asctime)s %(levelname)s %(name)s "
            "[request_id=%(request_id)s task_id=%(task_id)s worker_id=%(worker_id)s] "
            "%(message)s"
        ),
    )


class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        extra = kwargs.setdefault("extra", {})
        merged = {
            "request_id": "-",
            "task_id": "-",
            "worker_id": "-",
        }
        merged.update(self.extra)
        merged.update(extra)
        kwargs["extra"] = merged
        return msg, kwargs


def get_logger(name: str, **context: str | int | None) -> ContextAdapter:
    normalized = {key: value if value is not None else "-" for key, value in context.items()}
    return ContextAdapter(logging.getLogger(name), normalized)

