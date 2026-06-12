from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class LocalS3Client:
    bucket: str
    root_dir: Path

    def put_json(self, key: str, payload: dict[str, Any] | list[Any]) -> str:
        relative_key = self._normalize_key(key)
        path = self.root_dir / self.bucket / relative_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
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


@dataclass
class S3ClientProvider:
    endpoint: str = "local"
    bucket: str = "amsz-local"
    root_dir: str = "data/s3"

    def build(self) -> LocalS3Client:
        return LocalS3Client(bucket=self.bucket, root_dir=Path(self.root_dir))
