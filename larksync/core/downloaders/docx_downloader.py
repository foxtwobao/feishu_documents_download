"""DocX downloader implementation."""

from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple
from urllib.parse import unquote

import httpx

from ...utils.filesystem import safe_add_suffix, sanitize_filename
from ..reference_cache import lookup_resolved_path, register_resolved_path
from ..api_client import FeishuAPIError
from ..models import SyncTask
from ..parsers.docx_parser import (
    DocxParseResult,
    DocxResource,
    SheetExport,
    WhiteboardExport,
    WikiCatalogExport,
)
from .base_downloader import BaseDownloader


@dataclass(frozen=True, slots=True)
class ReferencedDownload:
    """Metadata about a downloaded nested reference."""

    ref_type: str
    token: str
    url: Optional[str]
    path: Path


class DocxDownloader(BaseDownloader):
    """Download DocX documents and convert them to Markdown."""

    file_type = "docx"
    _ATTACHMENT_PREFIX = "Attachment"
    _IMAGE_PREFIX = "Image"
    _REFERENCE_PATTERN = re.compile(
        r"https://[^/]+/(docx|doc|sheets|sheet|base|mindnotes|slides|file)/([A-Za-z0-9]+)",
        re.IGNORECASE,
    )
    _TYPE_MAP = {
        "doc": "docx",
        "docx": "docx",
        "sheets": "sheet",
        "sheet": "sheet",
        "base": "bitable",
        "mindnotes": "mindnote",
        "slides": "slides",
        "file": "file",
    }

    def download(self, task: SyncTask) -> None:  # noqa: D401 - doc inherited
        document = self.docx_adapter.get_document(task.token)
        blocks = list(self.docx_adapter.iter_blocks(task.token))
        data = document.get("data", {})
        doc_meta: Mapping[str, object] = data.get("document") or data

        parse_result = self.docx_parser.parse(doc_meta, blocks)

        output_name = self._resolve_output_name(task, doc_meta)
        relative_base = task.parent_path / output_name
        assets_root, larkfiles_root = self._refer_roots(task)

        history: Set[str] = set()
        depth = 0
        if isinstance(task.extra, dict):
            history.update(task.extra.get("_history", []))
            raw_depth = task.extra.get("_depth")
            if isinstance(raw_depth, int):
                depth = raw_depth
            else:
                try:
                    depth = int(raw_depth)
                except (TypeError, ValueError):
                    depth = 0
        history.add(task.token)

        # Markdown 文件路径（用于计算相对路径）
        # 使用 safe_add_suffix 避免 .with_suffix() 把 '产品2.0' 变成 '产品2.md'
        markdown_path = self.storage.target_path(safe_add_suffix(relative_base, ".md"))

        markdown = self._finalize_markdown(
            task,
            doc_meta,
            parse_result,
            assets_root,
            larkfiles_root,
            markdown_path,
        )

        self.storage.write_text(markdown_path, markdown)
        register_resolved_path(task.token, markdown_path)

        references = self._extract_references(parse_result)
        referenced = self._download_referenced_docx(
            references,
            assets_root,
            larkfiles_root,
            depth,
            history,
            task,
            markdown_path,
        )
        if referenced:
            self._replace_reference_links(markdown_path, referenced)

    # ------------------------------------------------------------------ helpers

    def _resolve_output_name(self, task: SyncTask, doc_meta: Mapping[str, object]) -> str:
        # 优先使用指定的输出文件名（可能带 token 后缀以避免同名文件冲突）
        if task.output_filename:
            # 去掉扩展名，因为后面会添加 .md
            return Path(task.output_filename).stem
        title = doc_meta.get("title")
        if isinstance(title, str) and title.strip():
            return sanitize_filename(title)
        return task.target_path.name

    def _refer_roots(self, task: SyncTask) -> tuple[Path, Path]:
        refer_base = None
        if isinstance(task.extra, dict):
            refer_base = task.extra.get("entry_root")
        if isinstance(refer_base, Path):
            refer_root = self.storage.root / refer_base / "refer"
        elif isinstance(refer_base, str) and refer_base:
            refer_root = self.storage.root / Path(refer_base) / "refer"
        else:
            refer_root = self.storage.root / "refer"
        assets_root = refer_root / "assets"
        larkfiles_root = refer_root / "larkfiles"
        assets_root.mkdir(parents=True, exist_ok=True)
        larkfiles_root.mkdir(parents=True, exist_ok=True)
        return assets_root, larkfiles_root

    def _finalize_markdown(
        self,
        task: SyncTask,
        doc_meta: Mapping[str, object],
        parse_result: DocxParseResult,
        assets_root: Path,
        larkfiles_root: Path,
        markdown_path: Path,
    ) -> str:
        placeholder_map: Dict[str, str] = {}
        placeholder_map.update(self._materialize_images(parse_result.images, assets_root, markdown_path))
        placeholder_map.update(self._materialize_attachments(parse_result.attachments, assets_root, markdown_path))
        placeholder_map.update(self._materialize_whiteboards(parse_result.whiteboards, assets_root, markdown_path))
        placeholder_map.update(self._materialize_sheets(parse_result.sheets, larkfiles_root))
        placeholder_map.update(self._materialize_wiki_catalogs(task, parse_result.wiki_catalogs, markdown_path))

        markdown = parse_result.markdown
        for placeholder, replacement in placeholder_map.items():
            markdown = markdown.replace(placeholder, replacement)

        markdown = self._cleanup_placeholders(markdown)

        if parse_result.nested_links:
            self._logger.info(
                "Detected nested Feishu links",
                extra={"count": len(parse_result.nested_links), "links": parse_result.nested_links[:5]},
            )
        return markdown

    def _materialize_sheets(self, sheets: Iterable[SheetExport], larkfiles_root: Path) -> Dict[str, str]:
        resources = list(sheets)
        if not resources:
            return {}
        substitutions: Dict[str, str] = {}
        for sheet in resources:
            try:
                csv_content = self._export_sheet_csv(sheet)
                table = self._csv_to_markdown(csv_content)
                substitutions[sheet.placeholder] = table
                target_dir = larkfiles_root / sheet.spreadsheet_token
                target_path = target_dir / "content.md"
                self.storage.write_text(target_path, f"{table}\n")
            except FeishuAPIError as exc:
                self._logger.warning(
                    "Failed to export sheet block",
                    extra={
                        "token": sheet.spreadsheet_token,
                        "sheet_id": sheet.sheet_id,
                        "block_id": sheet.block_id,
                        "status_code": exc.status_code,
                        "error_message": exc.message,
                    },
                )
                note = f"API {exc.status_code}: {exc.message}"
                note_text = f"<!-- Sheet export failed: {note} -->"
                substitutions[sheet.placeholder] = note_text
                target_dir = larkfiles_root / sheet.spreadsheet_token
                target_path = target_dir / "content.md"
                self.storage.write_text(target_path, f"{note_text}\n")
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning(
                    "Unexpected error when exporting sheet block",
                    extra={
                        "token": sheet.spreadsheet_token,
                        "sheet_id": sheet.sheet_id,
                        "block_id": sheet.block_id,
                        "error": str(exc),
                    },
                )
                note_text = f"<!-- Sheet export failed: {exc} -->"
                substitutions[sheet.placeholder] = note_text
                target_dir = larkfiles_root / sheet.spreadsheet_token
                target_path = target_dir / "content.md"
                self.storage.write_text(target_path, f"{note_text}\n")
        return substitutions

    def _materialize_wiki_catalogs(
        self,
        task: SyncTask,
        catalogs: Iterable[WikiCatalogExport],
        markdown_path: Path,
    ) -> Dict[str, str]:
        resources = list(catalogs)
        if not resources:
            return {}

        substitutions: Dict[str, str] = {}
        known_paths = self._load_known_paths(task)
        for catalog in resources:
            substitutions[catalog.placeholder] = self._render_wiki_catalog(
                catalog,
                markdown_path,
                known_paths,
            )
        return substitutions

    def _render_wiki_catalog(
        self,
        catalog: WikiCatalogExport,
        markdown_path: Path,
        known_paths: Mapping[str, Path],
    ) -> str:
        fallback = f"[WikiCatalog: {catalog.wiki_token}]"
        try:
            payload = self.client.get(
                "/open-apis/wiki/v2/spaces/get_node",
                params={"token": catalog.wiki_token},
            )
        except FeishuAPIError as exc:
            self._logger.warning(
                "Failed to fetch wiki catalog node",
                extra={
                    "wiki_token": catalog.wiki_token,
                    "status_code": exc.status_code,
                    "error_message": exc.message,
                },
            )
            return fallback

        node = (payload.get("data") or {}).get("node") or {}
        space_id = node.get("space_id")
        if not isinstance(space_id, str) or not space_id:
            return fallback

        lines: List[str] = []
        visited: Set[str] = set()

        def walk(parent_token: str, level: int) -> None:
            page_token: Optional[str] = None
            while True:
                params: Dict[str, object] = {
                    "parent_node_token": parent_token,
                    "page_size": 50,
                }
                if page_token:
                    params["page_token"] = page_token
                response = self.client.get(
                    f"/open-apis/wiki/v2/spaces/{space_id}/nodes",
                    params=params,
                )
                data = response.get("data") or {}
                items = data.get("items") or []

                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    node_token = str(item.get("node_token") or "")
                    if not node_token or node_token in visited:
                        continue
                    visited.add(node_token)

                    title = str(item.get("title") or node_token)
                    obj_token = item.get("obj_token")
                    if isinstance(obj_token, str):
                        resolved_token = obj_token
                    else:
                        resolved_token = None
                    url = item.get("origin_url")
                    if not isinstance(url, str) or not url:
                        obj_type = item.get("obj_type")
                        if isinstance(obj_type, str):
                            url = self._build_wiki_url(obj_type, resolved_token, node_token)
                        else:
                            url = self._build_wiki_url(None, resolved_token, node_token)
                    link = self._resolve_catalog_link(markdown_path, known_paths, resolved_token, url)
                    lines.append(f"{'  ' * level}- [{title}]({link})")

                    if bool(item.get("has_child")):
                        walk(node_token, level + 1)

                if not data.get("has_more"):
                    break
                next_page = data.get("page_token")
                if not isinstance(next_page, str) or not next_page:
                    break
                page_token = next_page

        try:
            walk(catalog.wiki_token, 0)
        except FeishuAPIError as exc:
            self._logger.warning(
                "Failed to fetch wiki catalog children",
                extra={
                    "wiki_token": catalog.wiki_token,
                    "space_id": space_id,
                    "status_code": exc.status_code,
                    "error_message": exc.message,
                },
            )
            return fallback

        if lines:
            return "\n".join(lines)

        root_title = str(node.get("title") or catalog.title or catalog.wiki_token)
        root_obj_token = node.get("obj_token")
        if not isinstance(root_obj_token, str):
            root_obj_token = None
        root_url = node.get("origin_url")
        if not isinstance(root_url, str) or not root_url:
            obj_type = node.get("obj_type")
            if isinstance(obj_type, str):
                root_url = self._build_wiki_url(obj_type, root_obj_token, catalog.wiki_token)
            else:
                root_url = self._build_wiki_url(None, root_obj_token, catalog.wiki_token)
        root_link = self._resolve_catalog_link(markdown_path, known_paths, root_obj_token, root_url)
        return f"- [{root_title}]({root_link})"

    @staticmethod
    def _build_wiki_url(obj_type: Optional[str], obj_token: Optional[str], node_token: str) -> str:
        if obj_type and obj_token:
            return f"https://feishu.cn/{obj_type}/{obj_token}"
        return f"https://feishu.cn/wiki/{node_token}"

    def _resolve_catalog_link(
        self,
        markdown_path: Path,
        known_paths: Mapping[str, Path],
        obj_token: Optional[str],
        fallback_url: str,
    ) -> str:
        if obj_token:
            local_path = known_paths.get(obj_token)
            if local_path and local_path.exists():
                return self._resolve_relative_link(markdown_path, local_path)
        return fallback_url

    def _export_sheet_csv(self, sheet: SheetExport) -> str:
        ticket = self.drive_adapter.create_export_task(
            token=sheet.spreadsheet_token,
            doc_type="sheet",
            file_extension="csv",
            sub_id=sheet.sheet_id,
        )

        for attempt in range(30):
            payload = self.drive_adapter.get_export_task(ticket, sheet.spreadsheet_token)
            result = payload.get("data", {}).get("result") or {}
            status = result.get("job_status")
            if status in (0, "success"):
                file_token = result.get("file_token")
                if not file_token:
                    raise RuntimeError("Export task succeeded but file token missing")
                response = self.drive_adapter.download_export_file(file_token)
                try:
                    data = response.read()
                finally:
                    response.close()
                return self._decode_csv_bytes(data)
            if status in (1, 2, "init", "initializing", "processing", "pending", None):
                time.sleep(1.0)
                continue
            error_msg = result.get("job_error_msg") or f"Unexpected export status {status}"
            status_code = int(status) if isinstance(status, int) else -1
            raise FeishuAPIError(status_code, str(error_msg))

        raise TimeoutError("Timed out waiting for sheet export task to complete")

    @staticmethod
    def _decode_csv_bytes(data: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _csv_to_markdown(csv_text: str) -> str:
        reader = csv.reader(io.StringIO(csv_text))
        rows = [row for row in reader]
        if not rows:
            return "[Empty sheet]"
        column_count = max((len(row) for row in rows), default=0)
        if column_count == 0:
            return "[Empty sheet]"

        def normalize_row(row: list[str]) -> list[str]:
            return row + [""] * (column_count - len(row))

        def escape_cell(value: str) -> str:
            text = value.replace("\r", "").replace("\n", "<br>")
            return text.replace("|", "\\|").strip() or " "

        header = [escape_cell(cell) for cell in normalize_row(rows[0])]
        lines = ["| " + " | ".join(header) + " |"]
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in rows[1:]:
            cells = [escape_cell(cell) for cell in normalize_row(row)]
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    def _fetch_metadata_map_by_type(
        self, references: Iterable[Tuple[str, str, Optional[str]]]
    ) -> Dict[Tuple[str, str], Mapping[str, object]]:
        grouped: Dict[str, Set[str]] = {}
        for ref_type, token, _ in references:
            if not token:
                continue
            grouped.setdefault(ref_type, set()).add(token)

        mapping: Dict[Tuple[str, str], Mapping[str, object]] = {}
        for doc_type, tokens in grouped.items():
            docs = [(token, doc_type) for token in tokens]
            try:
                payload = self.drive_adapter.batch_get_metadata(docs)
            except FeishuAPIError:
                continue
            metas = payload.get("data", {}).get("metas") or []
            for meta in metas:
                meta_token = meta.get("doc_token") or meta.get("token")
                if meta_token:
                    mapping[(doc_type, meta_token)] = meta
        return mapping

    def _materialize_images(
        self,
        resources: Iterable[DocxResource],
        assets_root: Path,
        markdown_path: Path,
    ) -> Dict[str, str]:
        """Download images concurrently for better performance."""
        resources_list = list(resources)
        if not resources_list:
            return {}
        
        substitutions: Dict[str, str] = {}
        
        # 并发下载图片（最多 5 个并发）
        max_workers = min(5, len(resources_list))
        
        def download_single_image(index: int, resource: DocxResource) -> Tuple[str, str]:
            try:
                response = self.drive_adapter.download_media(resource.token)
            except FeishuAPIError as exc:
                self._logger.warning(
                    "Failed to download image resource",
                    extra={
                        "token": resource.token,
                        "block_id": resource.block_id,
                        "resource_type": resource.resource_type,
                        "resource_name": resource.name,
                        "status_code": exc.status_code,
                        "error": exc.message,
                    },
                )
                return (resource.placeholder, self._image_error_placeholder(resource, exc))
            
            try:
                assets_dir = assets_root / resource.token
                assets_dir.mkdir(parents=True, exist_ok=True)
                suffix = self._resolve_original_extension(
                    resource,
                    response,
                    fallback_ext=".png",
                )
                path = assets_dir / f"original{suffix}"
                self.storage.write_stream(path, response.iter_bytes())
                return (resource.placeholder, self._image_markdown(resource, path, markdown_path))
            finally:
                response.close()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(download_single_image, idx, res): res
                for idx, res in enumerate(resources_list, start=1)
            }
            
            for future in as_completed(futures):
                try:
                    placeholder, markdown = future.result()
                    substitutions[placeholder] = markdown
                except Exception as exc:
                    resource = futures[future]
                    self._logger.error(
                        "Unexpected error downloading image",
                        extra={
                            "token": resource.token,
                            "block_id": resource.block_id,
                            "resource_type": resource.resource_type,
                            "resource_name": resource.name,
                            "error": str(exc),
                        },
                    )
                    substitutions[resource.placeholder] = f"![{resource.name or 'image'}](#image-error)"
        
        return substitutions

    def _materialize_attachments(
        self,
        resources: Iterable[DocxResource],
        assets_root: Path,
        markdown_path: Path,
    ) -> Dict[str, str]:
        """Download attachments concurrently for better performance."""
        resources_list = list(resources)
        if not resources_list:
            return {}
        
        substitutions: Dict[str, str] = {}
        
        # 并发下载附件（最多 5 个并发）
        max_workers = min(5, len(resources_list))
        
        def download_single_attachment(index: int, resource: DocxResource) -> Tuple[str, str]:
            response: httpx.Response | None = None
            try:
                response = self.drive_adapter.download_file(resource.token)
            except FeishuAPIError as exc:
                fallback_exc: FeishuAPIError | None = None
                if exc.status_code in {400, 403, 404}:
                    try:
                        response = self.drive_adapter.download_media(resource.token)
                    except FeishuAPIError as media_exc:
                        fallback_exc = media_exc
                if response is None:
                    self._logger.warning(
                        "Failed to download attachment resource",
                        extra={
                            "token": resource.token,
                            "status_code": (fallback_exc or exc).status_code,
                            "error": (fallback_exc or exc).message,
                        },
                    )
                    return (resource.placeholder, self._attachment_error_placeholder(resource, fallback_exc or exc))
            
            try:
                assets_dir = assets_root / resource.token
                assets_dir.mkdir(parents=True, exist_ok=True)
                suffix = self._resolve_original_extension(
                    resource,
                    response,
                    fallback_ext=".bin",
                )
                path = assets_dir / f"original{suffix}"
                self.storage.write_stream(path, response.iter_bytes())
                return (resource.placeholder, self._attachment_markdown(resource, path, markdown_path))
            finally:
                response.close()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(download_single_attachment, idx, res): res
                for idx, res in enumerate(resources_list, start=1)
            }
            
            for future in as_completed(futures):
                try:
                    placeholder, markdown = future.result()
                    substitutions[placeholder] = markdown
                except Exception as exc:
                    resource = futures[future]
                    self._logger.error(
                        "Unexpected error downloading attachment",
                        extra={"token": resource.token, "error": str(exc)},
                    )
                    substitutions[resource.placeholder] = f"[{resource.name or 'attachment'} (error)](#attachment-error)"
        
        return substitutions

    def _materialize_whiteboards(
        self,
        resources: Iterable[WhiteboardExport],
        assets_root: Path,
        markdown_path: Path,
    ) -> Dict[str, str]:
        substitutions: Dict[str, str] = {}
        for resource in resources:
            whiteboard_token = resource.whiteboard_id or resource.block_id or "whiteboard"
            assets_dir = assets_root / whiteboard_token
            assets_dir.mkdir(parents=True, exist_ok=True)
            json_path = assets_dir / "original.json"

            image_replacement = ""
            json_replacement = ""

            try:
                response = self.client.download(
                    f"/open-apis/board/v1/whiteboards/{resource.whiteboard_id}/download_as_image"
                )
                try:
                    suffix = self._resolve_whiteboard_image_extension(response)
                    image_path = assets_dir / f"original{suffix}"
                    self.storage.write_stream(image_path, response.iter_bytes())
                    image_replacement = self._whiteboard_image_markdown(resource, image_path, markdown_path)
                finally:
                    response.close()
            except FeishuAPIError as exc:
                self._logger.warning(
                    "Failed to download whiteboard thumbnail",
                    extra={
                        "whiteboard_id": resource.whiteboard_id,
                        "status_code": exc.status_code,
                        "error": exc.message,
                    },
                )
                image_replacement = self._whiteboard_image_error(resource, exc.status_code, exc.message)
            except Exception as exc:  # pragma: no cover - unexpected errors
                self._logger.warning(
                    "Unexpected error when downloading whiteboard thumbnail",
                    extra={"whiteboard_id": resource.whiteboard_id, "error": str(exc)},
                )
                image_replacement = self._whiteboard_image_error(resource, None, str(exc))

            try:
                nodes = self.client.get(f"/open-apis/board/v1/whiteboards/{resource.whiteboard_id}/nodes")
                serialized = json.dumps(nodes, ensure_ascii=False, indent=2)
                self.storage.write_text(json_path, serialized)
                json_replacement = self._whiteboard_json_markdown(resource, json_path, markdown_path)
            except FeishuAPIError as exc:
                self._logger.warning(
                    "Failed to fetch whiteboard nodes",
                    extra={
                        "whiteboard_id": resource.whiteboard_id,
                        "status_code": exc.status_code,
                        "error": exc.message,
                    },
                )
                json_replacement = self._whiteboard_json_error(resource, exc.status_code, exc.message)
            except Exception as exc:  # pragma: no cover - unexpected errors
                self._logger.warning(
                    "Unexpected error when fetching whiteboard nodes",
                    extra={"whiteboard_id": resource.whiteboard_id, "error": str(exc)},
                )
                json_replacement = self._whiteboard_json_error(resource, None, str(exc))

            substitutions[resource.image_placeholder] = image_replacement
            substitutions[resource.json_placeholder] = json_replacement

        return substitutions

    def _extract_references(self, parse_result: DocxParseResult) -> List[Tuple[str, str, Optional[str]]]:
        seen: Set[Tuple[str, str]] = set()
        references: List[Tuple[str, str, Optional[str]]] = []
        for link in parse_result.nested_links:
            match = self._REFERENCE_PATTERN.search(link)
            if not match:
                continue
            raw_type = match.group(1).lower()
            token = match.group(2)
            doc_type = self._TYPE_MAP.get(raw_type)
            if not doc_type:
                continue
            key = (doc_type, token)
            if key in seen:
                continue
            seen.add(key)
            references.append((doc_type, token, link))
        return references

    def _download_referenced_docx(
        self,
        references: List[Tuple[str, str, Optional[str]]],
        assets_root: Path,
        larkfiles_root: Path,
        current_depth: int,
        history: Set[str],
        task: SyncTask,
        markdown_path: Path,
    ) -> List[ReferencedDownload]:
        if not references:
            return []

        max_depth = self.config.sync.max_nested_depth
        if max_depth is not None and current_depth >= max_depth:
            self._logger.info(
                "Skip referenced downloads - reached depth limit",
                extra={
                    "token": task.token,
                    "current_depth": current_depth,
                    "max_depth": max_depth,
                    "reference_count": len(references),
                },
            )
            return []

        try:
            registry = self.registry
        except RuntimeError:
            self._logger.warning("Registry unavailable; skip referenced downloads")
            return []

        results: List[ReferencedDownload] = []
        known_paths = self._load_known_paths(task)
        known_paths.setdefault(task.token, markdown_path)

        # fetch metadata grouped by type
        meta_map = self._fetch_metadata_map_by_type(references)

        for ref_type, token, url in references:
            if not token:
                continue

            cached_path = lookup_resolved_path(token)
            if cached_path and cached_path.exists():
                known_paths[token] = cached_path

            if token in history:
                path = known_paths.get(token)
                if path:
                    results.append(
                        ReferencedDownload(
                            ref_type=ref_type,
                            token=token,
                            url=url,
                            path=path,
                        )
                    )
                continue

            existing = known_paths.get(token)
            if existing:
                results.append(
                    ReferencedDownload(
                        ref_type=ref_type,
                        token=token,
                        url=url,
                        path=existing,
                    )
                )
                continue

            if ref_type == "docx" and token == task.token:
                results.append(
                    ReferencedDownload(
                        ref_type=ref_type,
                        token=token,
                        url=url,
                        path=markdown_path,
                    )
                )
                known_paths[token] = markdown_path
                continue

            target_dir = self._resolve_reference_dir(ref_type, token, assets_root, larkfiles_root)

            display_name = self._resolve_reference_name(meta_map, ref_type, token)
            safe_name = sanitize_filename(display_name) or token

            child_paths = self._serialize_known_paths(known_paths)
            extra: Dict[str, object] = {"_history": list(history), "_depth": current_depth + 1}
            if child_paths:
                extra["_resolved_paths"] = child_paths
            if url:
                extra["source_url"] = url
            if isinstance(task.extra, dict) and task.extra.get("entry_root"):
                extra["entry_root"] = task.extra.get("entry_root")

            output_filename = self._reference_output_filename(ref_type)
            if ref_type == "file":
                extra["force_original_name"] = True

            subtask = SyncTask(
                token=token,
                file_type=ref_type,
                name=safe_name,
                parent_path=target_dir.relative_to(self.storage.root),
                extra=extra,
                output_filename=output_filename,
            )

            try:
                downloader = registry.build(ref_type, self._context)
                downloader.execute(subtask)
                path = lookup_resolved_path(token)
                if path is None or not path.exists():
                    path = self._resolve_reference_output(ref_type, token, safe_name, target_dir)
                if ref_type in {"sheet", "sheets", "bitable", "base"}:
                    content_md = target_dir / "content.md"
                    xlsx_name = path.name if path else "content.xlsx"
                    link_label = display_name or token
                    content = "\n".join(
                        [
                            f"# {link_label}",
                            "",
                            f"[下载表格]({xlsx_name})",
                            "",
                        ]
                    )
                    self.storage.write_text(content_md, content)
                    path = content_md
                if path is None:
                    path = target_dir / f"{safe_name}.md"
                register_resolved_path(token, path)
                results.append(
                    ReferencedDownload(
                        ref_type=ref_type,
                        token=token,
                        url=url,
                        path=path,
                    )
                )
                known_paths[token] = path
                continue
            except FeishuAPIError as exc:
                self._logger.warning(
                    "Failed to download referenced document",
                    extra={
                        "parent": task.token,
                        "reference": token,
                        "file_type": ref_type,
                        "status_code": exc.status_code,
                        "error_message": exc.message,
                    },
                )
                note = f"API {exc.status_code}: {exc.message}"
            except KeyError:
                self._logger.warning(
                    "No downloader registered for referenced document",
                    extra={"parent": task.token, "reference": token, "file_type": ref_type},
                )
                note = "未找到下载器"
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning(
                    "Unexpected error while downloading referenced document",
                    extra={"parent": task.token, "reference": token, "file_type": ref_type, "error": str(exc)},
                )
                note = str(exc)

            placeholder_name = sanitize_filename(display_name) or sanitize_filename(token) or "refer_doc"
            placeholder = target_dir / f"{placeholder_name}.md"
            lines = [
                f"# {display_name}",
                "",
                "引用文档下载失败。",
                "",
                f"- 原始链接：{url or '未知'}",
                f"- 错误信息：{note}",
            ]
            self.storage.write_text(placeholder, "\n".join(lines) + "\n")
            register_resolved_path(token, placeholder)
            results.append(
                ReferencedDownload(
                    ref_type=ref_type,
                    token=token,
                    url=url,
                    path=placeholder,
                )
            )
            known_paths[token] = placeholder
        return results

    def _resolve_reference_dir(
        self,
        ref_type: str,
        token: str,
        assets_root: Path,
        larkfiles_root: Path,
    ) -> Path:
        if ref_type == "file":
            target = assets_root / token
        else:
            target = larkfiles_root / token
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _reference_output_filename(ref_type: str) -> Optional[str]:
        if ref_type == "file":
            return None
        if ref_type in {"sheet", "sheets", "bitable", "base"}:
            return "content.xlsx"
        return "content.md"

    def _load_known_paths(self, task: SyncTask) -> Dict[str, Path]:
        known: Dict[str, Path] = {}
        if isinstance(task.extra, dict):
            raw = task.extra.get("_resolved_paths")
            if isinstance(raw, Mapping):
                for token, serialized in raw.items():
                    if not isinstance(token, str) or not isinstance(serialized, str):
                        continue
                    candidate = Path(serialized)
                    if not candidate.is_absolute():
                        candidate = self.storage.root / candidate
                    known[token] = candidate
        return known

    def _serialize_known_paths(self, mapping: Mapping[str, Path]) -> Dict[str, str]:
        serialized: Dict[str, str] = {}
        for token, path in mapping.items():
            try:
                relative = path.relative_to(self.storage.root)
                serialized[token] = relative.as_posix()
            except ValueError:
                serialized[token] = path.as_posix()
        return serialized

    def _resolve_reference_name(
        self,
        meta_map: Mapping[Tuple[str, str], Mapping[str, object]],
        ref_type: str,
        token: str,
    ) -> str:
        meta = meta_map.get((ref_type, token))
        if meta:
            for key in ("name", "title"):
                if meta.get(key):
                    return str(meta[key])
        return token

    def _resolve_reference_output(
        self,
        ref_type: str,
        token: str,
        safe_name: str,
        target_dir: Path,
    ) -> Optional[Path]:
        if ref_type == "file":
            candidates = sorted(target_dir.glob("original.*"))
        elif ref_type in {"sheet", "sheets", "bitable", "base"}:
            candidates = [target_dir / "content.md", target_dir / "content.xlsx"]
        elif ref_type in {"docx", "slides", "mindnote"}:
            candidates = [target_dir / "content.md"]
        else:
            candidates = [target_dir / "content.md"]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # Fallback: pick the most recently modified file within the directory.
        newest: Optional[Path] = None
        try:
            for entry in target_dir.iterdir():
                if newest is None:
                    newest = entry
                    continue
                try:
                    if entry.stat().st_mtime >= newest.stat().st_mtime:
                        newest = entry
                except FileNotFoundError:
                    continue
        except FileNotFoundError:
            return None

        if newest is None:
            return None
        if newest.is_file():
            return newest
        if newest.is_dir():
            markdown = newest / f"{newest.name}.md"
            if markdown.exists():
                return markdown
        return None

    def _replace_reference_links(self, markdown_path: Path, downloads: Iterable[ReferencedDownload]) -> None:
        text = markdown_path.read_text(encoding="utf-8")
        updated = text
        processed: Set[str] = set()

        for entry in downloads:
            key = f"{entry.ref_type}:{entry.token}"
            if key in processed:
                continue
            processed.add(key)

            replacement_url = self._resolve_relative_link(markdown_path, entry.path)
            updated = self._substitute_reference_occurrences(
                updated,
                token=entry.token,
                replacement_url=replacement_url,
                original_url=entry.url,
            )

        if updated != text:
            markdown_path.write_text(updated, encoding="utf-8")

    def _resolve_relative_link(self, markdown_path: Path, target_path: Path) -> str:
        if target_path == markdown_path:
            return markdown_path.name

        try:
            relative = target_path.relative_to(markdown_path.parent)
            relative_str = relative.as_posix()
        except ValueError:
            relative_str = Path(os.path.relpath(target_path, start=markdown_path.parent)).as_posix()

        if relative_str in {"", "."}:
            return markdown_path.name
        return relative_str

    def _substitute_reference_occurrences(
        self,
        content: str,
        *,
        token: str,
        replacement_url: str,
        original_url: Optional[str],
    ) -> str:
        patterns = [
            re.compile(
                rf"https://[^/]+/(?:docx|docs|doc|sheet|sheets|base|bitable|mindnotes|mindnote|slides|file)/{re.escape(token)}[^\s)\]]*",
                re.IGNORECASE,
            ),
            re.compile(
                rf"<https://[^/]+/(?:docx|docs|doc|sheet|sheets|base|bitable|mindnotes|mindnote|slides|file)/{re.escape(token)}[^>]*>",
                re.IGNORECASE,
            ),
        ]

        updated = content
        for pattern in patterns[:-1]:
            updated = pattern.sub(replacement_url, updated)

        # Handle angle-bracket autolinks separately
        updated = patterns[-1].sub(lambda match: f"<{replacement_url}>", updated)

        if original_url:
            escaped = re.escape(original_url)
            updated = re.sub(escaped, replacement_url, updated)

        md_pattern = re.compile(rf"\[([^\]]*?)\]\(([^)]*{re.escape(token)}[^)]*)\)")

        def _replace_markdown_link(match: re.Match[str]) -> str:
            label = match.group(1).strip() or token
            return f"[{label}]({replacement_url})"

        updated = md_pattern.sub(_replace_markdown_link, updated)
        return updated

    def _resolve_resource_filename(
        self,
        resource: DocxResource,
        response: httpx.Response,
        *,
        fallback: str,
    ) -> str:
        name = sanitize_filename(resource.name)
        if not name or name == "untitled":
            name = fallback

        disposition = response.headers.get("Content-Disposition")
        header_filename = self._parse_content_disposition(disposition)
        if header_filename:
            name = sanitize_filename(header_filename)

        if "." not in name:
            mime_type = response.headers.get("Content-Type") or resource.mime_type or ""
            ext = mimetypes.guess_extension(mime_type.split(";")[0].strip()) if mime_type else None
            if not ext and resource.resource_type == "image":
                ext = ".png"
            if ext:
                name = f"{name}{ext}"
        return name

    def _resolve_original_extension(
        self,
        resource: DocxResource,
        response: httpx.Response,
        *,
        fallback_ext: str,
    ) -> str:
        filename = self._resolve_resource_filename(resource, response, fallback="original")
        suffix = Path(filename).suffix
        if not suffix:
            return fallback_ext
        return suffix

    @staticmethod
    def _resolve_whiteboard_image_extension(response: httpx.Response) -> str:
        mime_type = response.headers.get("Content-Type") or ""
        ext = mimetypes.guess_extension(mime_type.split(";")[0].strip()) if mime_type else None
        return ext or ".png"

    def _unique_path(self, directory: Path, filename: str) -> Path:
        base = sanitize_filename(Path(filename).stem)
        suffix = Path(filename).suffix
        candidate = directory / f"{base}{suffix}"
        counter = 1
        while candidate.exists():
            candidate = directory / f"{base}_{counter}{suffix}"
            counter += 1
        return candidate

    def _image_markdown(self, resource: DocxResource, path: Path, markdown_path: Path) -> str:
        # 计算相对于 markdown 文件的相对路径
        try:
            relative = os.path.relpath(path, markdown_path.parent)
        except ValueError:
            # 如果路径在不同的驱动器上，使用绝对路径
            relative = path.as_posix()
        alt_text = resource.name or "image"
        return f"![{alt_text}]({relative})"

    def _attachment_markdown(self, resource: DocxResource, path: Path, markdown_path: Path) -> str:
        # 计算相对于 markdown 文件的相对路径
        try:
            relative = os.path.relpath(path, markdown_path.parent)
        except ValueError:
            # 如果路径在不同的驱动器上，使用绝对路径
            relative = path.as_posix()
        display_name = resource.name or path.name
        return f"[{display_name}]({relative})"

    def _whiteboard_image_markdown(self, resource: WhiteboardExport, path: Path, markdown_path: Path) -> str:
        # 计算相对于 markdown 文件的相对路径
        try:
            relative = os.path.relpath(path, markdown_path.parent)
        except ValueError:
            relative = path.as_posix()
        label = resource.name or resource.whiteboard_id or "whiteboard"
        return f"![{label}]({relative})"

    def _whiteboard_json_markdown(self, resource: WhiteboardExport, path: Path, markdown_path: Path) -> str:
        # 计算相对于 markdown 文件的相对路径
        try:
            relative = os.path.relpath(path, markdown_path.parent)
        except ValueError:
            relative = path.as_posix()
        label = resource.name or resource.whiteboard_id or "whiteboard"
        return f"[{label} JSON]({relative})"

    def _image_error_placeholder(self, resource: DocxResource, error: FeishuAPIError) -> str:
        alt_text = resource.name or resource.block_id or "image"
        return f"![{alt_text}](#image-download-error-{error.status_code})"

    def _attachment_error_placeholder(self, resource: DocxResource, error: FeishuAPIError) -> str:
        name = resource.name or resource.block_id or "attachment"
        return f"[{name} (下载失败: {error.status_code})](#attachment-download-error-{error.status_code})"

    def _whiteboard_image_error(
        self, resource: WhiteboardExport, status_code: int | None, message: str
    ) -> str:
        label = resource.name or resource.whiteboard_id or "whiteboard"
        suffix = f"-{status_code}" if status_code else ""
        return f"![{label}](#whiteboard-image-error{suffix})"

    def _whiteboard_json_error(
        self, resource: WhiteboardExport, status_code: int | None, message: str
    ) -> str:
        label = resource.name or resource.whiteboard_id or "whiteboard"
        suffix = f"-{status_code}" if status_code else ""
        note = f"{status_code}: {message}" if status_code else message
        return f"[{label} JSON 下载失败: {note}](#whiteboard-json-error{suffix})"

    @staticmethod
    def _parse_content_disposition(value: str | None) -> str | None:
        if not value:
            return None
        filename_star_match = re.search(r'filename\*\s*=\s*[^\'"]*\'\'([^;]+)', value)
        if filename_star_match:
            return unquote(filename_star_match.group(1))
        filename_match = re.search(r'filename="([^"]+)"', value)
        if filename_match:
            return filename_match.group(1)
        return None

    @staticmethod
    def _cleanup_placeholders(markdown: str) -> str:
        pattern = re.compile(r"\{\{(image|attachment|whiteboard_image|whiteboard_json):([^}]+)\}\}")

        def repl(match: re.Match[str]) -> str:
            kind, identifier = match.groups()
            if kind == "image":
                return f"![{identifier}](#missing-image)"
            if kind == "attachment":
                return f"[Attachment {identifier}](#missing-attachment)"
            if kind == "whiteboard_image":
                return f"![Whiteboard {identifier}](#missing-whiteboard-image)"
            return f"[Whiteboard {identifier} JSON](#missing-whiteboard-json)"

        return pattern.sub(repl, markdown)
