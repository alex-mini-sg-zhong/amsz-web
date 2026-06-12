from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# LocalS3Client — filesystem-backed implementation (dev / test)
# ---------------------------------------------------------------------------

@dataclass
class LocalS3Client:
    bucket: str
    root_dir: Path

    def put_json(self, key: str, payload: dict[str, Any] | list[Any]) -> str:
        relative_key = self._normalize_key(key)
        path = self.root_dir / self.bucket / relative_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        return self.to_uri(relative_key)

    def get_json(self, key_or_uri: str) -> dict[str, Any] | list[Any]:
        path = self.root_dir / self.bucket / self._normalize_key(key_or_uri)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_json_keys(self, prefix: str) -> list[str]:
        relative_prefix = self._normalize_key(prefix).rstrip("/")
        base = self.root_dir / self.bucket / relative_prefix
        if not base.exists():
            return []
        keys = [
            str(path.relative_to(self.root_dir / self.bucket))
            for path in base.rglob("*.json")
            if path.is_file()
        ]
        return sorted(keys)

    def to_uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._normalize_key(key)}"

    def _normalize_key(self, key_or_uri: str) -> str:
        prefix = f"s3://{self.bucket}/"
        if key_or_uri.startswith(prefix):
            return key_or_uri[len(prefix):]
        if key_or_uri.startswith("s3://"):
            parts = key_or_uri.split("/", 3)
            return parts[3] if len(parts) > 3 else ""
        return key_or_uri.lstrip("/")


# ---------------------------------------------------------------------------
# Boto3S3Client — real S3 via boto3  (AWS S3 / HWS3 / any S3-compatible)
# ---------------------------------------------------------------------------

@dataclass
class Boto3S3Client:
    bucket: str
    region: str
    endpoint_url: str | None
    _client: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        import boto3

        client_kwargs: dict[str, Any] = {
            "service_name": "s3",
            "region_name": self.region,
        }
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url
        self._client = boto3.client(**client_kwargs)

    # -- public API ----------------------------------------------------------

    def put_json(self, key: str, payload: dict[str, Any] | list[Any]) -> str:
        relative_key = self._normalize_key(key)
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self._client.put_object(
            Bucket=self.bucket,
            Key=relative_key,
            Body=body,
            ContentType="application/json",
        )
        return self.to_uri(relative_key)

    def get_json(self, key_or_uri: str) -> dict[str, Any] | list[Any]:
        relative_key = self._normalize_key(key_or_uri)
        resp = self._client.get_object(Bucket=self.bucket, Key=relative_key)
        return json.loads(resp["Body"].read().decode("utf-8"))

    def list_json_keys(self, prefix: str) -> list[str]:
        relative_prefix = self._normalize_key(prefix).rstrip("/")
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(
            Bucket=self.bucket,
            Prefix=relative_prefix + "/" if relative_prefix else "",
        )
        for page in page_iterator:
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                if key.endswith(".json"):
                    keys.append(key)
        return sorted(keys)

    def to_uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._normalize_key(key)}"

    # -- internal ------------------------------------------------------------

    def _normalize_key(self, key_or_uri: str) -> str:
        prefix = f"s3://{self.bucket}/"
        if key_or_uri.startswith(prefix):
            return key_or_uri[len(prefix):]
        if key_or_uri.startswith("s3://"):
            parts = key_or_uri.split("/", 3)
            return parts[3] if len(parts) > 3 else ""
        return key_or_uri.lstrip("/")


# ---------------------------------------------------------------------------
# Provider — builds the right client based on runtime config
# ---------------------------------------------------------------------------

@dataclass
class S3ClientProvider:
    provider: str = "local"
    bucket: str = "amsz-local"
    root_dir: str = "data/s3"
    region: str = "us-east-1"
    endpoint_url: str = ""

    def build(self) -> LocalS3Client | Boto3S3Client:
        if self.provider == "local":
            return LocalS3Client(bucket=self.bucket, root_dir=Path(self.root_dir))
        if self.provider == "aws":
            return Boto3S3Client(
                bucket=self.bucket,
                region=self.region,
                endpoint_url=self.endpoint_url or None,
            )
        raise ValueError(
            f"Unknown S3 provider '{self.provider}'. Expected 'local' or 'aws'."
        )
