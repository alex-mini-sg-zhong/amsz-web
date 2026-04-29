from __future__ import annotations


class TaskError(Exception):
    def __init__(self, message: str, error_code: str = "TASK_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class RetryableTaskError(TaskError):
    """Temporary failure that should be retried."""


class NonRetryableTaskError(TaskError):
    """Permanent failure that should not be retried."""

