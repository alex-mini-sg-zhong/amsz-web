from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ElasticsearchClientProvider:
    endpoint: str

    def build(self) -> object:
        raise NotImplementedError("Elasticsearch datasource integration is not implemented yet")
