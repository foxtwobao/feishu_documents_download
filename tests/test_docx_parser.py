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
