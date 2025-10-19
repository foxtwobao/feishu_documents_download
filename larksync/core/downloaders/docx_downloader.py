"""DocX downloader implementation."""

from __future__ import annotations

import json
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple
from urllib.parse import unquote

import httpx

from ...utils.filesystem import sanitize_filename
from ..api_client import FeishuAPIError
from ..models import SyncTask
from ..parsers.docx_parser import DocxParseResult, DocxResource, WhiteboardExport
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
        doc_dir = self.storage.root / relative_base
        asset_dirs = self._prepare_asset_dirs(doc_dir)

        history: Set[str] = set()
        if isinstance(task.extra, dict):
            history.update(task.extra.get("_history", []))
        history.add(task.token)

        markdown = self._finalize_markdown(task, doc_meta, parse_result, asset_dirs)

        markdown_path = self.storage.target_path(relative_base.with_suffix(".md"))
        self.storage.write_text(markdown_path, markdown)

        references = self._extract_references(parse_result)
        referenced = self._download_referenced_docx(
            references,
            asset_dirs["refer_docx"],
            history,
            task,
            markdown_path,
        )
        if referenced:
            self._replace_reference_links(markdown_path, referenced)

    # ------------------------------------------------------------------ helpers

    def _resolve_output_name(self, task: SyncTask, doc_meta: Mapping[str, object]) -> str:
        title = doc_meta.get("title")
        if isinstance(title, str) and title.strip():
            return sanitize_filename(title)
        return task.target_path.name

    def _prepare_asset_dirs(self, doc_dir: Path) -> Dict[str, Path]:
        images_dir = doc_dir / "images"
        attachments_dir = doc_dir / "attachments"
        whiteboards_images_dir = doc_dir / "whiteboards" / "images"
        whiteboards_json_dir = doc_dir / "whiteboards" / "json"
        refer_docx_dir = doc_dir / "referdocx"
        return {
            "images": images_dir,
            "attachments": attachments_dir,
            "whiteboard_images": whiteboards_images_dir,
            "whiteboard_json": whiteboards_json_dir,
            "refer_docx": refer_docx_dir,
        }

    def _finalize_markdown(
        self,
        task: SyncTask,
        doc_meta: Mapping[str, object],
        parse_result: DocxParseResult,
        asset_dirs: Mapping[str, Path],
    ) -> str:
        placeholder_map: Dict[str, str] = {}
        placeholder_map.update(self._materialize_images(parse_result.images, asset_dirs["images"]))
        placeholder_map.update(
            self._materialize_attachments(parse_result.attachments, asset_dirs["attachments"])
        )
        placeholder_map.update(
            self._materialize_whiteboards(
                parse_result.whiteboards,
                asset_dirs["whiteboard_images"],
                asset_dirs["whiteboard_json"],
            )
        )

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

    def _materialize_images(self, resources: Iterable[DocxResource], images_dir: Path) -> Dict[str, str]:
        substitutions: Dict[str, str] = {}
        ensured = False
        for index, resource in enumerate(resources, start=1):
            try:
                response = self.drive_adapter.download_media(resource.token)
            except FeishuAPIError as exc:
                self._logger.warning(
                    "Failed to download image resource",
                    extra={"token": resource.token, "status_code": exc.status_code, "error": exc.message},
                )
                substitutions[resource.placeholder] = self._image_error_placeholder(resource, exc)
                continue
            try:
                if not ensured:
                    images_dir.mkdir(parents=True, exist_ok=True)
                    ensured = True
                filename = self._resolve_resource_filename(
                    resource,
                    response,
                    fallback=f"{self._IMAGE_PREFIX}-{index}",
                )
                path = self._unique_path(images_dir, filename)
                self.storage.write_stream(path, response.iter_bytes())
                substitutions[resource.placeholder] = self._image_markdown(resource, path)
            finally:
                response.close()
        return substitutions

    def _materialize_attachments(
        self,
        resources: Iterable[DocxResource],
        attachments_dir: Path,
    ) -> Dict[str, str]:
        substitutions: Dict[str, str] = {}
        ensured = False
        for index, resource in enumerate(resources, start=1):
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
                    substitutions[resource.placeholder] = self._attachment_error_placeholder(
                        resource, fallback_exc or exc
                    )
                    continue
            try:
                if not ensured:
                    attachments_dir.mkdir(parents=True, exist_ok=True)
                    ensured = True
                filename = self._resolve_resource_filename(
                    resource,
                    response,
                    fallback=f"{self._ATTACHMENT_PREFIX}-{index}",
                )
                path = self._unique_path(attachments_dir, filename)
                self.storage.write_stream(path, response.iter_bytes())
                substitutions[resource.placeholder] = self._attachment_markdown(resource, path)
            finally:
                response.close()
        return substitutions

    def _materialize_whiteboards(
        self,
        resources: Iterable[WhiteboardExport],
        image_dir: Path,
        json_dir: Path,
    ) -> Dict[str, str]:
        substitutions: Dict[str, str] = {}
        image_dir_ensured = False
        json_dir_ensured = False
        for resource in resources:
            base_name = sanitize_filename(resource.name) or sanitize_filename(resource.block_id) or sanitize_filename(
                resource.whiteboard_id
            )
            if not base_name:
                base_name = "whiteboard"

            image_path = self._unique_path(image_dir, f"{base_name}.png")
            json_path = self._unique_path(json_dir, f"{base_name}.json")

            image_replacement = ""
            json_replacement = ""

            try:
                response = self.client.download(
                    f"/open-apis/board/v1/whiteboards/{resource.whiteboard_id}/download_as_image"
                )
                try:
                    if not image_dir_ensured:
                        image_dir.mkdir(parents=True, exist_ok=True)
                        image_dir_ensured = True
                    self.storage.write_stream(image_path, response.iter_bytes())
                    image_replacement = self._whiteboard_image_markdown(resource, image_path)
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
                if not json_dir_ensured:
                    json_dir.mkdir(parents=True, exist_ok=True)
                    json_dir_ensured = True
                self.storage.write_text(json_path, serialized)
                json_replacement = self._whiteboard_json_markdown(resource, json_path)
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
        refer_dir: Path,
        history: Set[str],
        task: SyncTask,
        markdown_path: Path,
    ) -> List[ReferencedDownload]:
        if not references:
            return []

        refer_dir.mkdir(parents=True, exist_ok=True)

        try:
            registry = self.registry
        except RuntimeError:
            self._logger.warning("Registry unavailable; skip referenced downloads")
            return []

        doc_dir = refer_dir.parent
        results: List[ReferencedDownload] = []
        known_paths = self._load_known_paths(task)
        known_paths.setdefault(task.token, markdown_path)

        # fetch metadata grouped by type
        meta_map = self._fetch_metadata_map_by_type(references)

        for ref_type, token, url in references:
            if not token or token in history:
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

            target_dir = self._ensure_reference_dir(doc_dir, ref_type, refer_dir)

            display_name = self._resolve_reference_name(meta_map, ref_type, token)
            safe_name = sanitize_filename(display_name) or token

            child_paths = self._serialize_known_paths(known_paths)
            extra: Dict[str, object] = {"_history": list(history)}
            if child_paths:
                extra["_resolved_paths"] = child_paths
            if url:
                extra["source_url"] = url

            pre_snapshot = self._snapshot_files(target_dir)

            subtask = SyncTask(
                token=token,
                file_type=ref_type,
                name=safe_name,
                parent_path=target_dir.relative_to(self.storage.root),
                extra=extra,
            )

            try:
                downloader = registry.build(ref_type, self._context)
                downloader.execute(subtask)
                post_snapshot = self._snapshot_files(target_dir)
                path = self._resolve_reference_output(
                    ref_type,
                    token,
                    safe_name,
                    target_dir,
                    pre_snapshot,
                    post_snapshot,
                )
                if path is None:
                    path = target_dir / f"{safe_name}.md"
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

    def _ensure_reference_dir(self, doc_dir: Path, ref_type: str, docx_dir: Path) -> Path:
        if ref_type == "docx":
            return docx_dir
        target = doc_dir / f"refer_{ref_type}"
        target.mkdir(parents=True, exist_ok=True)
        return target

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

    def _snapshot_files(self, base_dir: Path) -> Set[Path]:
        return {path for path in base_dir.rglob("*") if path.is_file()}

    def _resolve_reference_output(
        self,
        ref_type: str,
        token: str,
        safe_name: str,
        target_dir: Path,
        pre_snapshot: Set[Path],
        post_snapshot: Set[Path],
    ) -> Optional[Path]:
        if ref_type == "docx":
            candidate = target_dir / safe_name / f"{safe_name}.md"
            if candidate.exists():
                return candidate
            candidate = target_dir / f"{safe_name}.md"
            if candidate.exists():
                return candidate
        new_files = list(post_snapshot - pre_snapshot)
        if not new_files:
            return None
        new_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return new_files[0]

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

    def _unique_path(self, directory: Path, filename: str) -> Path:
        base = sanitize_filename(Path(filename).stem)
        suffix = Path(filename).suffix
        candidate = directory / f"{base}{suffix}"
        counter = 1
        while candidate.exists():
            candidate = directory / f"{base}_{counter}{suffix}"
            counter += 1
        return candidate

    def _image_markdown(self, resource: DocxResource, path: Path) -> str:
        relative = path.relative_to(self.storage.root).as_posix()
        alt_text = resource.name or "image"
        return f"![{alt_text}]({relative})"

    def _attachment_markdown(self, resource: DocxResource, path: Path) -> str:
        relative = path.relative_to(self.storage.root).as_posix()
        display_name = resource.name or path.name
        return f"[{display_name}]({relative})"

    def _whiteboard_image_markdown(self, resource: WhiteboardExport, path: Path) -> str:
        relative = path.relative_to(self.storage.root).as_posix()
        label = resource.name or resource.whiteboard_id or "whiteboard"
        return f"![{label}]({relative})"

    def _whiteboard_json_markdown(self, resource: WhiteboardExport, path: Path) -> str:
        relative = path.relative_to(self.storage.root).as_posix()
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
