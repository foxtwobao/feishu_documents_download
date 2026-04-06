from pathlib import Path
from typing import cast

from larksync.config import LarkSyncConfig, StorageSettings
from larksync.core.api_client import FeishuAPIClient
from larksync.core.downloaders.base_downloader import DownloaderContext
from larksync.core.downloaders.docx_downloader import DocxDownloader, ReferencedDownload
from larksync.core.downloaders.file_downloader import FileDownloader
from larksync.core.models import SyncTask
from larksync.core.parsers.docx_parser import WhiteboardExport
from larksync.core.reference_cache import clear_cache
from larksync.core.registry import DownloaderRegistry
from larksync.storage.manager import StorageManager


def _build_downloader(tmp_path: Path, *, client: FeishuAPIClient | None = None) -> DocxDownloader:
    config = LarkSyncConfig()
    storage = StorageManager(StorageSettings(root=tmp_path))
    dummy_drive = type(
        "DummyDrive",
        (),
        {"batch_get_metadata": staticmethod(lambda docs: {"data": {"metas": []}})},
    )
    context = DownloaderContext(
        config=config,
        client=client or cast(FeishuAPIClient, object()),
        storage=storage,
        registry=DownloaderRegistry(),
        drive_adapter=dummy_drive(),  # type: ignore[arg-type]
    )
    return DocxDownloader(context)


def _build_file_downloader(tmp_path: Path) -> FileDownloader:
    config = LarkSyncConfig()
    storage = StorageManager(StorageSettings(root=tmp_path))
    context = DownloaderContext(
        config=config,
        client=cast(FeishuAPIClient, object()),
        storage=storage,
        registry=DownloaderRegistry(),
        drive_adapter=cast(object, object()),
    )
    return FileDownloader(context)


class _StubResponse:
    def __init__(self, data: bytes = b"data", headers: dict[str, str] | None = None) -> None:
        self._data = data
        self.headers = headers or {}

    def iter_bytes(self):
        yield self._data

    def close(self) -> None:
        pass


def test_reference_output_filename_uses_flat_refer_names():
    assert DocxDownloader._reference_output_filename("docx", "产品文档", "abc123") == "产品文档_abc123.md"
    assert DocxDownloader._reference_output_filename("sheet", "数据表", "sheet123") == "数据表_sheet123.xlsx"
    assert DocxDownloader._reference_output_filename("slides", "演示", "slide123") == "演示_slide123.md"
    assert DocxDownloader._reference_output_filename("file", "附件", "file123") is None


def test_resolve_reference_output_uses_flat_refer_files(tmp_path: Path):
    downloader = _build_downloader(tmp_path)
    refer_root = tmp_path / "refer"
    refer_root.mkdir()

    doc_path = refer_root / "产品文档_abc123.md"
    doc_path.write_text("# doc", encoding="utf-8")
    result = downloader._resolve_reference_output("docx", "abc123", "产品文档", refer_root)
    assert result == doc_path

    xlsx_path = refer_root / "数据表_sheet123.xlsx"
    xlsx_path.write_bytes(b"xlsx")
    result = downloader._resolve_reference_output("sheet", "sheet123", "数据表", refer_root)
    assert result == xlsx_path


def test_replace_reference_links_handles_flat_refer_and_sidecar_assets(tmp_path: Path):
    downloader = _build_downloader(tmp_path)

    doc_dir = downloader.storage.ensure_document_dir(Path("SampleDoc"))
    markdown_path = downloader.storage.target_path(Path("SampleDoc/SampleDoc_aaa111.md"))
    markdown_path.write_text(
        "\n".join(
            [
                "[Child Doc](https://foo.feishu.cn/docx/Doc111)",
                "Sheet URL: https://foo.feishu.cn/sheets/Sheet123?table=1",
                "[Bitable](https://foo.feishu.cn/base/Base456)",
                "Slides: <https://foo.feishu.cn/slides/Slide789>",
                "Mindnote: https://foo.feishu.cn/mindnotes/Mindnote000",
                "[File](https://foo.feishu.cn/file/File321)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    downloads = [
        ReferencedDownload("docx", "Doc111", "https://foo.feishu.cn/docx/Doc111", tmp_path / "refer" / "ChildDoc_Doc111.md"),
        ReferencedDownload("sheet", "Sheet123", "https://foo.feishu.cn/sheets/Sheet123?table=1", tmp_path / "refer" / "Budget_Sheet123.xlsx"),
        ReferencedDownload("bitable", "Base456", "https://foo.feishu.cn/base/Base456", tmp_path / "refer" / "Tasks_Base456.xlsx"),
        ReferencedDownload("slides", "Slide789", "https://foo.feishu.cn/slides/Slide789", tmp_path / "refer" / "Deck_Slide789.md"),
        ReferencedDownload("mindnote", "Mindnote000", "https://foo.feishu.cn/mindnotes/Mindnote000", tmp_path / "refer" / "Ideas_Mindnote000.md"),
        ReferencedDownload("file", "File321", "https://foo.feishu.cn/file/File321", tmp_path / "refer" / "Archive.zip"),
    ]

    downloader._replace_reference_links(markdown_path, downloads)

    content = markdown_path.read_text(encoding="utf-8")
    assert "https://foo.feishu.cn" not in content
    assert "../refer/ChildDoc_Doc111.md" in content
    assert "../refer/Budget_Sheet123.xlsx" in content
    assert "../refer/Tasks_Base456.xlsx" in content
    assert "../refer/Deck_Slide789.md" in content
    assert "../refer/Ideas_Mindnote000.md" in content
    assert "../refer/Archive.zip" in content
    assert doc_dir.exists()


def test_download_referenced_docx_uses_known_paths_for_tree_nodes(tmp_path: Path):
    clear_cache()
    downloader = _build_downloader(tmp_path)

    storage_root = downloader.storage.root
    root_path = downloader.storage.target_path(Path("Root/Root_token-root.md"))
    root_path.parent.mkdir(parents=True, exist_ok=True)
    root_path.write_text("root\n", encoding="utf-8")

    markdown_path = downloader.storage.target_path(Path("Nested/Nested_token-b.md"))
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("nested\n", encoding="utf-8")

    task = SyncTask(
        token="token-b",
        file_type="docx",
        name="Nested",
        parent_path=Path("Nested"),
        extra={"_history": ["token-root"], "_resolved_paths": {"token-root": "Root/Root_token-root.md"}},
    )
    references = [("docx", "token-root", "https://foo.feishu.cn/docx/token-root")]
    history = {"token-root", "token-b"}

    downloads = downloader._download_referenced_docx(references, tmp_path / "refer", 0, history, task, markdown_path)

    assert len(downloads) == 1
    assert downloads[0].token == "token-root"
    assert downloads[0].path == storage_root / "Root/Root_token-root.md"


def test_download_referenced_docx_respects_depth_limit(tmp_path: Path):
    downloader = _build_downloader(tmp_path)
    downloader.config.sync.max_nested_depth = 1

    class StubRegistry:
        def build(self, *_args, **_kwargs):
            raise AssertionError("Nested downloader should not be built when depth limit is reached")

    downloader._context.registry = StubRegistry()  # type: ignore[assignment]

    markdown_path = downloader.storage.target_path(Path("DepthLimited/DepthLimited_token-parent.md"))
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("content\n", encoding="utf-8")

    task = SyncTask(
        token="token-parent",
        file_type="docx",
        name="DepthLimited",
        parent_path=Path("DepthLimited"),
    )

    downloads = downloader._download_referenced_docx(
        [("docx", "token-child", None)],
        tmp_path / "refer",
        1,
        {"token-parent"},
        task,
        markdown_path,
    )

    assert downloads == []
    assert not (tmp_path / "refer").exists()


def test_materialize_whiteboards_downloads_assets_to_sidecar(tmp_path: Path):
    class StubClient:
        def __init__(self) -> None:
            self.download_calls: list[str] = []
            self.get_calls: list[str] = []

        def download(self, path: str) -> _StubResponse:
            self.download_calls.append(path)
            return _StubResponse(b"fake-png-bytes", headers={"Content-Type": "image/png"})

        def get(self, path: str) -> dict[str, object]:
            self.get_calls.append(path)
            return {"nodes": [{"id": "n1"}]}

    stub_client = StubClient()
    downloader = _build_downloader(tmp_path, client=cast(FeishuAPIClient, stub_client))

    markdown_path = downloader.storage.target_path(Path("Boards/Boards_abc123.md"))
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    assets_root = tmp_path / "Boards" / "Boards_abc123.assets"
    resource = WhiteboardExport(
        whiteboard_id="TFjowjZXghkRAkbUFnrcRlysncd",
        block_id="blk_flow",
        name="流程图",
        image_placeholder="{{whiteboard_image:blk_flow}}",
        json_placeholder="{{whiteboard_json:blk_flow}}",
    )

    substitutions = downloader._materialize_whiteboards([resource], assets_root, markdown_path)

    assert (assets_root / "流程图_TFjowjZXghkRAkbUFnrcRlysncd.png").exists()
    assert (assets_root / "流程图_TFjowjZXghkRAkbUFnrcRlysncd.json").exists()

    image_markdown = substitutions["{{whiteboard_image:blk_flow}}"]
    json_markdown = substitutions["{{whiteboard_json:blk_flow}}"]
    assert "Boards_abc123.assets/流程图_TFjowjZXghkRAkbUFnrcRlysncd.png" in image_markdown
    assert "Boards_abc123.assets/流程图_TFjowjZXghkRAkbUFnrcRlysncd.json" in json_markdown

    assert stub_client.download_calls == [
        "/open-apis/board/v1/whiteboards/TFjowjZXghkRAkbUFnrcRlysncd/download_as_image"
    ]
    assert stub_client.get_calls == [
        "/open-apis/board/v1/whiteboards/TFjowjZXghkRAkbUFnrcRlysncd/nodes"
    ]


def test_file_downloader_prefers_original_filename_for_reference_download(tmp_path: Path):
    downloader = _build_file_downloader(tmp_path)
    response = _StubResponse(headers={"Content-Disposition": 'attachment; filename="合同扫描件.pdf"'})
    task = SyncTask(token="file123", file_type="file", name="合同附件", parent_path=Path("refer"), extra={"force_original_name": True})

    filename = downloader._resolve_reference_filename(response, task)

    assert filename == "合同扫描件.pdf"


def test_file_downloader_falls_back_to_readable_name_when_header_missing(tmp_path: Path):
    downloader = _build_file_downloader(tmp_path)
    response = _StubResponse(headers={"Content-Type": "application/pdf"})
    task = SyncTask(token="file123", file_type="file", name="合同附件", parent_path=Path("refer"), extra={"force_original_name": True})

    filename = downloader._resolve_reference_filename(response, task)

    assert filename == "合同附件_file123.pdf"
