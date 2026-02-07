"""Tests for DocxMarkdownParser."""

from larksync.core.parsers.docx_parser import DocxMarkdownParser


def test_parse_simple_docx():
    parser = DocxMarkdownParser()
    document_meta = {"title": "Sample Document"}
    blocks = [
        {
            "block_id": "blk1",
            "block_type": "paragraph",
            "paragraph": {"elements": [{"text_run": {"content": "Hello world"}}]},
        },
        {
            "block_id": "blk2",
            "block_type": "heading2",
            "heading": {"elements": [{"text_run": {"content": "Section"}}]},
        },
        {
            "block_id": "blk3",
            "block_type": "image",
            "image": {"token": "img123", "name": "Diagram"},
        },
    ]

    result = parser.parse(document_meta, blocks)

    assert "# Sample Document" in result.markdown
    assert "Hello world" in result.markdown
    assert "{{image:blk3}}" in result.markdown
    assert any(resource.token == "img123" for resource in result.images)


def test_board_block_produces_whiteboard_placeholders():
    parser = DocxMarkdownParser()
    document_meta = {"title": "Board Showcase"}
    blocks = [
        {
            "block_id": "blk_board",
            "block_type": 43,
            "board": {
                "token": "GzJAwhQKCh8rACbPoFRcTQVynJg",
                "title": "画板",
            },
        },
    ]

    result = parser.parse(document_meta, blocks)

    assert "{{whiteboard_image:blk_board}}" in result.markdown
    assert "{{whiteboard_json:blk_board}}" in result.markdown
    assert any(w.whiteboard_id == "GzJAwhQKCh8rACbPoFRcTQVynJg" for w in result.whiteboards)


def test_sheet_block_collects_sheet_export():
    parser = DocxMarkdownParser()
    document_meta = {"title": "Sheet Links"}
    sheet_url = "https://foo.feishu.cn/sheets/Sheet123?table=1"
    blocks = [
        {
            "block_id": "blk_sheet",
            "block_type": "sheet",
            "sheet": {
                "token": "Sheet123",
                "title": "Budget",
                "url": sheet_url,
            },
        }
    ]

    result = parser.parse(document_meta, blocks)

    assert "{{sheet:blk_sheet}}" in result.markdown
    assert not result.nested_links
    assert result.sheets and result.sheets[0].spreadsheet_token == "Sheet123"


def test_sheet_block_splits_sheet_token():
    parser = DocxMarkdownParser()
    document_meta = {"title": "Sheet Links"}
    blocks = [
        {
            "block_id": "blk_sheet",
            "block_type": "sheet",
            "sheet": {
                "token": "Sheet123_SheetId",
                "title": "Budget",
            },
        }
    ]

    result = parser.parse(document_meta, blocks)

    assert "{{sheet:blk_sheet}}" in result.markdown
    assert not result.nested_links
    assert result.sheets
    assert result.sheets[0].spreadsheet_token == "Sheet123"
    assert result.sheets[0].sheet_id == "SheetId"
