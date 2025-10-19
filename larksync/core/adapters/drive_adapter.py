"""Drive adapter encapsulating file and export operations."""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional

import httpx

from ..api_client import FeishuAPIClient


class DriveAdapter:
    """Interact with Feishu Drive APIs for files, medias and export tasks."""

    def __init__(self, client: FeishuAPIClient):
        self._client = client

    def download_file(self, file_token: str) -> httpx.Response:
        return self._client.download(f"/open-apis/drive/v1/files/{file_token}/download")

    def download_media(self, image_token: str) -> httpx.Response:
        return self._client.download(f"/open-apis/drive/v1/medias/{image_token}/download")

    def download_export_file(self, file_token: str) -> httpx.Response:
        return self._client.download(f"/open-apis/drive/v1/export_tasks/file/{file_token}/download")

    def create_export_task(
        self,
        token: str,
        doc_type: str,
        file_extension: str,
        *,
        sub_id: str | None = None,
    ) -> str:
        payload: dict[str, object] = {"token": token, "type": doc_type, "file_extension": file_extension}
        if sub_id:
            payload["sub_id"] = sub_id
        response = self._client.post("/open-apis/drive/v1/export_tasks", json=payload)
        return response.get("data", {}).get("ticket")

    def get_export_task(self, ticket: str, token: str) -> Mapping[str, Any]:
        return self._client.get(f"/open-apis/drive/v1/export_tasks/{ticket}", params={"token": token})

    def batch_get_metadata(self, docs: Iterable[tuple[str, str]]) -> Mapping[str, Any]:
        request_docs = [{"doc_token": token, "doc_type": doc_type} for token, doc_type in docs]
        payload = {"request_docs": request_docs}
        return self._client.post("/open-apis/drive/v1/metas/batch_query", json=payload)

    def list_folder_children(
        self,
        folder_token: Optional[str] = None,
        *,
        page_token: Optional[str] = None,
        page_size: int = 200,
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {"page_size": page_size}
        if folder_token:
            params["folder_token"] = folder_token
        if page_token:
            params["page_token"] = page_token
        return self._client.get("/open-apis/drive/v1/files", params=params)

    def get_root_folder_meta(self) -> Mapping[str, Any]:
        return self._client.get("/open-apis/drive/explorer/v2/root_folder/meta")
