"""DocX adapter wrapping Feishu docx endpoints."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

from ..api_client import FeishuAPIClient


class DocxAdapter:
    """Thin adapter on top of :class:`FeishuAPIClient` for DocX APIs."""

    def __init__(self, client: FeishuAPIClient):
        self._client = client

    def get_document(self, document_id: str) -> Mapping[str, Any]:
        return self._client.get(f"/open-apis/docx/v1/documents/{document_id}")

    def get_block(self, document_id: str, block_id: str) -> Mapping[str, Any]:
        return self._client.get(f"/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}")

    def iter_blocks(self, document_id: str, page_size: int = 200) -> Iterator[Mapping[str, Any]]:
        page_token: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            response = self._client.get(f"/open-apis/docx/v1/documents/{document_id}/blocks", params=params)
            data = response.get("data", {})
            items = data.get("items", [])
            for item in items:
                yield item

            page_token = data.get("page_token") or data.get("next_page_token")
            if not page_token:
                break
