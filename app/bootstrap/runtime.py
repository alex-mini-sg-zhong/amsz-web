from __future__ import annotations

from app.core.config import (
    BootstrapSettings,
    RuntimeConfigError,
    RuntimeSettings,
    clear_settings_caches,
    get_bootstrap_settings,
    get_settings,
)


def load_bootstrap_settings() -> BootstrapSettings:
    return get_bootstrap_settings()


def load_runtime_settings() -> RuntimeSettings:
    return get_settings()


__all__ = [
    "BootstrapSettings",
    "RuntimeConfigError",
    "RuntimeSettings",
    "clear_settings_caches",
    "load_bootstrap_settings",
    "load_runtime_settings",
]
