from __future__ import annotations

import pytest

from app.core.config import RuntimeConfigError, build_runtime_settings, default_runtime_config_template


def test_runtime_config_resolves_allowed_placeholders() -> None:
    settings = build_runtime_settings(default_runtime_config_template())

    assert settings.api_key == "test-key"
    assert settings.worker_id == "worker-test"
    assert settings.pod_name == "pod-test"


def test_runtime_config_rejects_missing_env_placeholder(monkeypatch) -> None:
    monkeypatch.delenv("WORKER_ID", raising=False)
    template = default_runtime_config_template()

    with pytest.raises(RuntimeConfigError, match="WORKER_ID"):
        build_runtime_settings(template)


def test_runtime_config_rejects_non_whitelisted_placeholder() -> None:
    template = default_runtime_config_template()
    template["worker_id"] = "${UNSAFE_ENV}"

    with pytest.raises(RuntimeConfigError, match="not allowed"):
        build_runtime_settings(template)
