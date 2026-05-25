from __future__ import annotations

from dataclasses import dataclass


@dataclass
class S3ClientProvider:
    endpoint: str
    bucket: str

    def build(self) -> object:
        raise NotImplementedError("S3 datasource integration is not implemented yet")
