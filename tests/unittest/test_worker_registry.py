from __future__ import annotations

import pytest

from app.workers.registry import build_handler_registry


def test_default_worker_profile_loads_basic_and_batch_handlers() -> None:
    registry = build_handler_registry()

    assert "noop.success" in registry
    assert "batch.sleep.echo.shard" in registry
    assert "batch.sleep.echo.aggregate" in registry


def test_basic_worker_profile_only_loads_basic_handlers() -> None:
    registry = build_handler_registry(profile="basic")

    assert "noop.success" in registry
    assert "sleep.echo" in registry
    assert "force.retry" in registry
    assert "batch.sleep.echo.shard" not in registry
    assert "batch.sleep.echo.aggregate" not in registry


def test_batch_worker_profile_only_loads_batch_handlers() -> None:
    registry = build_handler_registry(profile="batch")

    assert "batch.sleep.echo.shard" in registry
    assert "batch.sleep.echo.aggregate" in registry
    assert "noop.success" not in registry


def test_unknown_worker_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown worker profile"):
        build_handler_registry(profile="unknown")
