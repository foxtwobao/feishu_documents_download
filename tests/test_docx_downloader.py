"""Tests for DocxDownloader helpers."""

from pathlib import Path
from typing import cast

from larksync.config import LarkSyncConfig, StorageSettings
from larksync.core.api_client import FeishuAPIClient
from larksync.core.downloaders.base_downloader import DownloaderContext
from larksync.core.downloaders.docx_downloader import DocxDownloader, ReferencedDownload
from larksync.core.models import SyncTask
from larksync.core.registry import DownloaderRegistry
from larksync.core.parsers.docx_parser import WhiteboardExport
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
        client=client or cast(FeishuAPIClient, object()),  # client not needed for this test
        storage=storage,
        registry=DownloaderRegistry(),
        drive_adapter=dummy_drive(),  # type: ignore[arg-type]
    )
    return DocxDownloader(context)


def test_replace_reference_links_handles_multiple_types(tmp_path):
    downloader = _build_downloader(tmp_path)

    doc_dir = downloader.storage.ensure_document_dir(Path("SampleDoc"))
    markdown_path = downloader.storage.target_path(Path("SampleDoc.md"))

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
        ReferencedDownload(
            ref_type="docx",
            token="Doc111",
            url="https://foo.feishu.cn/docx/Doc111",
            path=doc_dir / "referdocx" / "ChildDoc" / "ChildDoc.md",
        ),
        ReferencedDownload(
            ref_type="sheet",
            token="Sheet123",
            url="https://foo.feishu.cn/sheets/Sheet123?table=1",
            path=doc_dir / "refer_sheet" / "Budget.xlsx",
        ),
        ReferencedDownload(
            ref_type="bitable",
            token="Base456",
            url="https://foo.feishu.cn/base/Base456",
            path=doc_dir / "refer_bitable" / "Tasks.xlsx",
        ),
        ReferencedDownload(
            ref_type="slides",
            token="Slide789",
            url="https://foo.feishu.cn/slides/Slide789",
            path=doc_dir / "refer_slides" / "Deck.md",
        ),
        ReferencedDownload(
            ref_type="mindnote",
            token="Mindnote000",
            url="https://foo.feishu.cn/mindnotes/Mindnote000",
            path=doc_dir / "refer_mindnote" / "Ideas.md",
        ),
        ReferencedDownload(
            ref_type="file",
            token="File321",
            url="https://foo.feishu.cn/file/File321",
            path=doc_dir / "refer_file" / "Archive.zip",
        ),
    ]

    downloader._replace_reference_links(markdown_path, downloads)

    content = markdown_path.read_text(encoding="utf-8")
    assert "https://foo.feishu.cn" not in content
    assert "[Child Doc](SampleDoc/referdocx/ChildDoc/ChildDoc.md)" in content
    assert "SampleDoc/refer_sheet/Budget.xlsx" in content
    assert "[Bitable](SampleDoc/refer_bitable/Tasks.xlsx)" in content
    assert "SampleDoc/refer_slides/Deck.md" in content
    assert "SampleDoc/refer_mindnote/Ideas.md" in content
    assert "[File](SampleDoc/refer_file/Archive.zip)" in content


def test_download_referenced_docx_uses_known_paths_for_history(tmp_path):
    downloader = _build_downloader(tmp_path)

    storage_root = downloader.storage.root
    root_path = downloader.storage.target_path(Path("Root.md"))
    root_path.write_text("root\n", encoding="utf-8")

    doc_dir = downloader.storage.ensure_document_dir(Path("NestedDoc"))
    refer_dir = doc_dir / "referdocx"
    refer_dir.mkdir(parents=True, exist_ok=True)

    markdown_path = downloader.storage.target_path(Path("NestedDoc.md"))
    markdown_path.write_text("nested\n", encoding="utf-8")

    task = SyncTask(
        token="token-b",
        file_type="docx",
        name="NestedDoc",
        parent_path=Path("NestedDoc"),
        extra={"_history": ["token-root"], "_resolved_paths": {"token-root": "Root.md"}},
    )
    references = [("docx", "token-root", "https://foo.feishu.cn/docx/token-root")]
    history = {"token-root", "token-b"}

    downloads = downloader._download_referenced_docx(references, refer_dir, 0, history, task, markdown_path)

    assert len(downloads) == 1
    assert downloads[0].token == "token-root"
    assert downloads[0].path == storage_root / "Root.md"


def test_download_referenced_docx_respects_depth_limit(tmp_path):
    downloader = _build_downloader(tmp_path)
    downloader.config.sync.max_nested_depth = 1

    class StubRegistry:
        def build(self, *_args, **_kwargs):
            raise AssertionError("Nested downloader should not be built when depth limit is reached")

    downloader._context.registry = StubRegistry()  # type: ignore[assignment]

    doc_dir = downloader.storage.ensure_document_dir(Path("DepthLimited"))
    refer_dir = doc_dir / "referdocx"
    markdown_path = downloader.storage.target_path(Path("DepthLimited.md"))
    markdown_path.write_text("content\n", encoding="utf-8")

    task = SyncTask(
        token="token-parent",
        file_type="docx",
        name="DepthLimited",
        parent_path=Path("DepthLimited"),
    )

    references = [("docx", "token-child", None)]
    history = {"token-parent"}

    downloads = downloader._download_referenced_docx(
        references,
        refer_dir,
        1,
        history,
        task,
        markdown_path,
    )

    assert downloads == []
    assert not refer_dir.exists()


def test_materialize_whiteboards_downloads_assets(tmp_path):
    class StubResponse:
        def __init__(self, data: bytes):
            self._data = data
            self.headers: dict[str, str] = {}

        def iter_bytes(self):
            yield self._data

        def close(self) -> None:
            pass

    class StubClient:
        def __init__(self) -> None:
            self.download_calls: list[str] = []
            self.get_calls: list[str] = []

        def download(self, path: str) -> StubResponse:
            self.download_calls.append(path)
            return StubResponse(b"fake-png-bytes")

        def get(self, path: str) -> dict[str, object]:
            self.get_calls.append(path)
            return {"nodes": [{"id": "n1"}]}

    stub_client = StubClient()
    downloader = _build_downloader(tmp_path, client=cast(FeishuAPIClient, stub_client))

    markdown_path = downloader.storage.target_path(Path("Boards/Boards.md"))
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    resource = WhiteboardExport(
        whiteboard_id="TFjowjZXghkRAkbUFnrcRlysncd",
        block_id="blk_flow",
        name="流程图",
        image_placeholder="{{whiteboard_image:blk_flow}}",
        json_placeholder="{{whiteboard_json:blk_flow}}",
    )

    image_dir = tmp_path / "Boards" / "whiteboards" / "images"
    json_dir = tmp_path / "Boards" / "whiteboards" / "json"

    substitutions = downloader._materialize_whiteboards(
        [resource],
        image_dir,
        json_dir,
        markdown_path,
    )

    image_path = image_dir / "流程图.png"
    json_path = json_dir / "流程图.json"

    assert image_path.exists()
    assert json_path.exists()

    image_markdown = substitutions["{{whiteboard_image:blk_flow}}"]
    json_markdown = substitutions["{{whiteboard_json:blk_flow}}"]

    assert "![流程图]" in image_markdown
    assert "(whiteboards/images/流程图.png)" in image_markdown
    assert "[流程图 JSON]" in json_markdown
    assert "(whiteboards/json/流程图.json)" in json_markdown

    # ensure client endpoints were invoked
    assert stub_client.download_calls == [
        "/open-apis/board/v1/whiteboards/TFjowjZXghkRAkbUFnrcRlysncd/download_as_image"
    ]
    assert stub_client.get_calls == [
        "/open-apis/board/v1/whiteboards/TFjowjZXghkRAkbUFnrcRlysncd/nodes"
    ]
