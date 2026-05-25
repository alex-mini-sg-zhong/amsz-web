from __future__ import annotations

from collections.abc import Mapping

from app.workers.contracts import TaskHandler
from app.workers.modules.batch import HANDLERS as BATCH_HANDLERS
from app.workers.modules.basic import HANDLERS as BASIC_HANDLERS

PROFILE_MODULE_MAP: dict[str, tuple[Mapping[str, TaskHandler], ...]] = {
    "default": (BASIC_HANDLERS, BATCH_HANDLERS),
    "all": (BASIC_HANDLERS, BATCH_HANDLERS),
    "basic": (BASIC_HANDLERS,),
    "batch": (BATCH_HANDLERS,),
}


def build_handler_registry(profile: str = "default") -> dict[str, TaskHandler]:
    handler_groups = PROFILE_MODULE_MAP.get(profile)
    if handler_groups is None:
        known_profiles = ", ".join(sorted(PROFILE_MODULE_MAP))
        raise ValueError(
            f"Unknown worker profile '{profile}'. Expected one of: {known_profiles}"
        )

    registry: dict[str, TaskHandler] = {}
    for handlers in handler_groups:
        _merge_handler_map(registry, handlers)
    return registry


def _merge_handler_map(
    registry: dict[str, TaskHandler],
    handlers: Mapping[str, TaskHandler],
) -> None:
    duplicates = set(registry).intersection(handlers)
    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise ValueError(f"Duplicate worker task type registrations: {duplicate_list}")
    registry.update(handlers)
