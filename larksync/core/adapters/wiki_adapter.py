"""Wiki adapter encapsulating Feishu Wiki API operations."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..api_client import FeishuAPIClient


class WikiAdapter:
    """Interact with Feishu Wiki APIs for spaces and nodes."""

    def __init__(self, client: FeishuAPIClient):
        self._client = client

    def list_spaces(
        self,
        *,
        page_token: Optional[str] = None,
        page_size: int = 50,
    ) -> Mapping[str, Any]:
        """获取用户可访问的知识库列表。

        API: GET /open-apis/wiki/v2/spaces

        Returns:
            包含 spaces 数组和分页信息的响应数据
        """
        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        return self._client.get("/open-apis/wiki/v2/spaces", params=params)

    def get_space(self, space_id: str) -> Mapping[str, Any]:
        """获取知识库详情。

        API: GET /open-apis/wiki/v2/spaces/{space_id}

        Args:
            space_id: 知识库 ID

        Returns:
            知识库详情数据
        """
        return self._client.get(f"/open-apis/wiki/v2/spaces/{space_id}")

    def list_space_nodes(
        self,
        space_id: str,
        *,
        parent_node_token: Optional[str] = None,
        page_token: Optional[str] = None,
        page_size: int = 50,
    ) -> Mapping[str, Any]:
        """获取知识库下的节点列表。

        API: GET /open-apis/wiki/v2/spaces/{space_id}/nodes

        Args:
            space_id: 知识库 ID
            parent_node_token: 父节点 token，不传则获取一级节点
            page_token: 分页标记
            page_size: 每页数量

        Returns:
            包含 items 数组和分页信息的响应数据
        """
        params: dict[str, Any] = {"page_size": page_size}
        if parent_node_token:
            params["parent_node_token"] = parent_node_token
        if page_token:
            params["page_token"] = page_token
        return self._client.get(
            f"/open-apis/wiki/v2/spaces/{space_id}/nodes",
            params=params,
        )

    def get_node(self, token: str) -> Mapping[str, Any]:
        """获取单个节点详情。

        API: GET /open-apis/wiki/v2/spaces/get_node

        Args:
            token: 节点 token

        Returns:
            节点详情数据，包含 obj_type 和 obj_token 等信息
        """
        response = self._client.get(
            "/open-apis/wiki/v2/spaces/get_node",
            params={"token": token},
        )
        return response
