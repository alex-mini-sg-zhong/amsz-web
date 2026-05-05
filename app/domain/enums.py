from __future__ import annotations

from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DISPATCHING = "DISPATCHING"
    PARTIALLY_RUNNING = "PARTIALLY_RUNNING"
    AGGREGATING = "AGGREGATING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    DEAD = "DEAD"


class AttemptStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    TIMEOUT = "TIMEOUT"


class TaskRole(str, Enum):
    STANDALONE = "standalone"
    PARENT = "parent"
    CHILD = "child"
    AGGREGATE = "aggregate"
