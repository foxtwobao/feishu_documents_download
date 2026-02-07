"""DocX to Markdown parser."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, MutableMapping, Sequence


@dataclass(slots=True)
class DocxResource:
    """Represents an external resource referenced inside a DocX document."""

    resource_type: str
    token: str
    name: str
    block_id: str
    placeholder: str
    mime_type: str | None = None


@dataclass(slots=True)
class WhiteboardExport:
    """Represents a whiteboard block that needs additional exports."""

    whiteboard_id: str
    block_id: str
    name: str
    image_placeholder: str
    json_placeholder: str


@dataclass(slots=True)
class SheetExport:
    """Represents a sheet block that can be rendered as a table."""

    spreadsheet_token: str
    sheet_id: str | None
    block_id: str
    name: str
    placeholder: str


@dataclass(slots=True)
class WikiCatalogExport:
    """Represents a wiki catalog block to be materialized."""

    wiki_token: str
    block_id: str
    title: str
    placeholder: str


@dataclass(slots=True)
class DocxParseResult:
    """Structured result of parsing a DocX document."""

    markdown: str
    images: List[DocxResource] = field(default_factory=list)
    attachments: List[DocxResource] = field(default_factory=list)
    nested_links: List[str] = field(default_factory=list)
    whiteboards: List[WhiteboardExport] = field(default_factory=list)
    sheets: List[SheetExport] = field(default_factory=list)
    wiki_catalogs: List[WikiCatalogExport] = field(default_factory=list)


class MarkdownBuilder:
    """Small helper for assembling Markdown content."""

    def __init__(self) -> None:
        self._lines: List[str] = []
        self._in_list = False

    def reset(self) -> None:
        self._lines.clear()
        self._in_list = False

    def add_heading(self, level: int, text: str) -> None:
        self._flush_block()
        level = max(1, min(level, 6))
        self._lines.append(f"{'#' * level} {text.strip()}")
        self._lines.append("")

    def add_paragraph(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self._lines:
            self._lines.append(text)
        else:
            if self._in_list and self._lines and self._lines[-1] != "":
                self._lines.append("")
            self._lines.append(text)
        self._lines.append("")
        self._in_list = False

    def add_list_item(self, text: str, ordered: bool, indent: int = 0) -> None:
        text = text.strip()
        if not text:
            return
        indent = max(indent, 0)
        if not self._in_list and self._lines and self._lines[-1] != "":
            self._lines.append("")
        marker = "1." if ordered else "-"
        indent_str = "  " * indent
        self._lines.append(f"{indent_str}{marker} {text}")
        self._in_list = True

    def add_todo(self, text: str, checked: bool, indent: int = 0) -> None:
        text = text.strip()
        indent = max(indent, 0)
        if not text:
            text = "(empty)"
        if not self._in_list and self._lines and self._lines[-1] != "":
            self._lines.append("")
        indent_str = "  " * indent
        marker = "x" if checked else " "
        self._lines.append(f"{indent_str}- [{marker}] {text}")
        self._in_list = True

    def add_quote(self, text: str) -> None:
        self._flush_block()
        lines = text.splitlines() or [""]
        for line in lines:
            self._lines.append(f"> {line}")
        self._lines.append("")

    def add_code_block(self, text: str, language: str | None) -> None:
        self._flush_block()
        fence = f"```{language or ''}".rstrip()
        self._lines.append(fence)
        code_lines = text.splitlines()
        self._lines.extend(code_lines)
        self._lines.append("```")
        self._lines.append("")

    def add_divider(self) -> None:
        self._flush_block()
        self._lines.append("---")
        self._lines.append("")

    def add_equation(self, latex: str) -> None:
        self._flush_block()
        self._lines.append("$$")
        self._lines.append(latex.strip())
        self._lines.append("$$")
        self._lines.append("")

    def add_comment(self, text: str) -> None:
        self._flush_block()
        self._lines.append(f"<!-- {text} -->")
        self._lines.append("")

    def add_raw_line(self, text: str) -> None:
        self._flush_block()
        self._lines.append(text)
        self._lines.append("")

    def _flush_block(self) -> None:
        if self._in_list and self._lines and self._lines[-1] != "":
            self._lines.append("")
        self._in_list = False

    def build(self) -> str:
        out = list(self._lines)
        while out and out[-1] == "":
            out.pop()
        return "\n".join(out) + ("\n" if out else "")


class DocxMarkdownParser:
    """Translate DocX blocks into Markdown output."""

    _BLOCK_TYPE_ALIASES = {
        "1": "page",
        "2": "paragraph",
        "3": "heading1",
        "4": "heading2",
        "5": "heading3",
        "6": "heading4",
        "7": "heading5",
        "8": "heading6",
        "9": "heading7",
        "10": "heading8",
        "11": "heading9",
        "12": "bullet",
        "13": "ordered",
        "14": "code",
        "15": "quote",
        "16": "equation",
        "17": "todo",
        "18": "bitable",
        "19": "callout",
        "20": "chat_card",
        "21": "diagram",
        "22": "divider",
        "23": "file",
        "24": "grid",
        "25": "grid_column",
        "26": "iframe",
        "27": "image",
        "28": "isv",
        "29": "mindnote",
        "30": "sheet",
        "31": "table",
        "32": "table_cell",
        "33": "view",
        "34": "quote_container",
        "35": "task",
        "36": "okr",
        "37": "okr_objective",
        "38": "okr_key_result",
        "39": "okr_progress",
        "40": "add_ons",
        "41": "jira_issue",
        "42": "wiki_catalog",
        "43": "board",
        "44": "agenda",
        "45": "agenda_item",
        "46": "agenda_item_title",
        "47": "agenda_item_content",
        "48": "link_preview",
        "49": "source_synced",
        "50": "reference_synced",
        "51": "sub_page_list",
        "52": "ai_template",
        "999": "undefined",
    }

    def __init__(self) -> None:
        self._builder = MarkdownBuilder()
        self._images: List[DocxResource] = []
        self._attachments: List[DocxResource] = []
        self._nested_links: set[str] = set()
        self._block_index: Dict[str, Mapping[str, object]] = {}
        self._consumed_blocks: set[str] = set()
        self._children_index: Dict[str, List[Mapping[str, object]]] = {}
        self._list_block_types = {"bullet", "ordered", "todo"}
        self._whiteboards: List[WhiteboardExport] = []
        self._sheets: List[SheetExport] = []
        self._wiki_catalogs: List[WikiCatalogExport] = []

    def parse(self, document_meta: Mapping[str, object], blocks: Sequence[Mapping[str, object]]) -> DocxParseResult:
        self._builder.reset()
        self._images.clear()
        self._attachments.clear()
        self._nested_links.clear()
        self._consumed_blocks.clear()
        self._whiteboards.clear()
        self._sheets.clear()
        self._wiki_catalogs.clear()
        self._block_index = {
            str(block.get("block_id")): block for block in blocks if isinstance(block.get("block_id"), str)
        }
        self._children_index.clear()
        for block in blocks:
            parent_id = str(block.get("parent_id") or "")
            self._children_index.setdefault(parent_id, []).append(block)

        title = str(document_meta.get("title") or "").strip()
        if title:
            self._builder.add_heading(1, title)

        roots = [block for block in blocks if self._normalise_block_type(block) == "page"]
        if roots:
            for root in roots:
                self._render_block_tree(root, parent_type=None, list_level=0)
        for block in self._children_index.get("", []):
            self._render_block_tree(block, parent_type=None, list_level=0)

        markdown = self._builder.build()
        return DocxParseResult(
            markdown=markdown,
            images=list(self._images),
            attachments=list(self._attachments),
            nested_links=sorted(self._nested_links),
            whiteboards=list(self._whiteboards),
            sheets=list(self._sheets),
            wiki_catalogs=list(self._wiki_catalogs),
        )

    # ------------------------------------------------------------------ parsing

    def _render_block_tree(self, block: Mapping[str, object], parent_type: str | None, list_level: int) -> None:
        block_id = str(block.get("block_id") or "")
        if block_id and block_id in self._consumed_blocks:
            return

        original_type = block.get("block_type")
        block_type = self._normalise_block_type(block)

        if block_type == "grid":
            self._render_grid(block)
            self._consumed_blocks.add(block_id)
            for child in self._children_index.get(block_id, []):
                self._render_block_tree(child, parent_type=block_type, list_level=list_level)
            return

        if block_type == "grid_column":
            self._render_grid_column(block, list_level)
            return

        next_list_level = self._render_block(block, parent_type, list_level)

        self._consumed_blocks.add(block_id)

        for child in self._children_index.get(block_id, []):
            self._render_block_tree(child, parent_type=block_type, list_level=next_list_level)

    def _render_block(self, block: Mapping[str, object], parent_type: str | None, list_level: int) -> int:
        block_type = self._normalise_block_type(block)
        original_type = block.get("block_type")
        next_list_level = list_level if parent_type in self._list_block_types else 0

        if block_type == "page":
            return 0

        if block_type.startswith("heading"):
            level = self._extract_heading_level(block_type, block)
            text = self._render_rich_text(self._extract_elements(block))
            if text:
                self._builder.add_heading(level, text)
            return 0

        if block_type == "paragraph":
            text = self._render_rich_text(self._extract_elements(block))
            if text:
                self._builder.add_paragraph(text)
            return next_list_level

        if block_type in {"bullet", "bullet_list"}:
            text = self._render_rich_text(self._extract_elements(block))
            indent = self._resolve_list_indent(block, parent_type, list_level)
            self._builder.add_list_item(text, ordered=False, indent=indent)
            return indent + 1

        if block_type in {"ordered", "ordered_list", "numbered"}:
            text = self._render_rich_text(self._extract_elements(block))
            indent = self._resolve_list_indent(block, parent_type, list_level)
            self._builder.add_list_item(text, ordered=True, indent=indent)
            return indent + 1

        if block_type == "todo":
            todo = self._as_dict(block.get("todo"))
            text = self._render_rich_text(self._extract_elements(todo))
            checked = bool(todo.get("checked"))
            indent = self._resolve_list_indent(block, parent_type, list_level)
            self._builder.add_todo(text, checked, indent)
            return indent + 1

        if block_type == "quote":
            text = self._render_rich_text(self._extract_elements(block))
            self._builder.add_quote(text)
            return next_list_level

        if block_type == "code":
            code = self._as_dict(block.get("code"))
            language = code.get("language") or code.get("lang") or ""
            code_text = self._extract_code_text(code)
            self._builder.add_code_block(code_text, str(language))
            return next_list_level

        if block_type == "divider":
            self._builder.add_divider()
            return next_list_level

        if block_type == "equation":
            equation = self._as_dict(block.get("equation"))
            latex = str(equation.get("latex") or equation.get("content") or "").strip()
            if latex:
                self._builder.add_equation(latex)
            return next_list_level

        if block_type == "image":
            placeholder = self._handle_image_block(block)
            self._builder.add_paragraph(placeholder)
            return next_list_level

        if block_type in {"file", "file_attachment"}:
            placeholder = self._handle_attachment_block(block)
            self._builder.add_paragraph(placeholder)
            return next_list_level

        if block_type in {"whiteboard", "board"}:
            image_placeholder, json_placeholder = self._handle_whiteboard(block)
            if image_placeholder:
                self._builder.add_raw_line(image_placeholder)
            if json_placeholder:
                self._builder.add_raw_line(json_placeholder)
            return next_list_level

        if block_type in {"table", "grid_container"}:
            rendered = self._render_table(block)
            self._builder.add_paragraph(rendered)
            return next_list_level

        if block_type in {"page_container", "view", "quote_container", "table_cell"}:
            return next_list_level

        if block_type == "chat_card":
            chat_card = self._as_dict(block.get("chat_card"))
            title = chat_card.get("title") or "会话卡片"
            description = chat_card.get("description") or ""
            text = f"**[ChatCard]** {title}"
            if description:
                text += f"\n> {description}"
            self._builder.add_paragraph(text)
            return next_list_level

        if block_type == "callout":
            callout = self._as_dict(block.get("callout"))
            background_color = callout.get("background_color")
            emoji_id = callout.get("emoji_id")
            text = self._render_rich_text(self._extract_elements(block))
            prefix = f"{emoji_id} " if emoji_id else ""
            self._builder.add_quote(f"{prefix}{text}")
            return next_list_level

        if block_type == "diagram":
            diagram = self._as_dict(block.get("diagram"))
            diagram_type = diagram.get("diagram_type") or "流程图"
            self._builder.add_paragraph(f"[Diagram: {diagram_type}]")
            return next_list_level

        if block_type == "iframe":
            iframe = self._as_dict(block.get("iframe"))
            component = self._as_dict(iframe.get("component"))
            url = component.get("url") or ""
            self._builder.add_paragraph(f"[Iframe: {url}]")
            return next_list_level

        if block_type == "bitable":
            bitable = self._as_dict(block.get("bitable"))
            token = bitable.get("token") or "Bitable"
            self._builder.add_paragraph(f"[Bitable: {token}]")
            return next_list_level

        if block_type == "sheet":
            sheet = self._as_dict(block.get("sheet"))
            token = sheet.get("token") or sheet.get("sheet_token") or sheet.get("sheet_id") or "Sheet"
            title = sheet.get("title") or sheet.get("name") or ""
            label = title or token
            block_id = str(block.get("block_id") or token)
            spreadsheet_token, sheet_id = self._split_sheet_token(str(token))
            placeholder = f"{{{{sheet:{block_id}}}}}"
            self._sheets.append(
                SheetExport(
                    spreadsheet_token=spreadsheet_token,
                    sheet_id=sheet_id,
                    block_id=block_id,
                    name=str(label),
                    placeholder=placeholder,
                )
            )
            self._builder.add_paragraph(placeholder)
            return next_list_level

        if block_type == "mindnote":
            mindnote = self._as_dict(block.get("mindnote"))
            token = mindnote.get("token") or "Mindnote"
            self._builder.add_paragraph(f"[Mindnote: {token}]")
            return next_list_level

        if block_type == "okr":
            okr = self._as_dict(block.get("okr"))
            okr_id = okr.get("okr_id") or "OKR"
            self._builder.add_paragraph(f"[OKR: {okr_id}]")
            return next_list_level

        if block_type == "task":
            task = self._as_dict(block.get("task"))
            task_id = task.get("task_id") or "Task"
            self._builder.add_paragraph(f"[Task: {task_id}]")
            return next_list_level

        if block_type == "add_ons":
            add_ons = self._as_dict(block.get("add_ons"))
            component_type_id = add_ons.get("component_type_id") or "AddOns"
            self._builder.add_paragraph(f"[AddOns: {component_type_id}]")
            return next_list_level

        if block_type == "jira_issue":
            jira = self._as_dict(block.get("jira_issue"))
            key = jira.get("key") or "Jira Issue"
            self._builder.add_paragraph(f"[Jira: {key}]")
            return next_list_level

        if block_type == "wiki_catalog":
            wiki = self._as_dict(block.get("wiki_catalog"))
            wiki_token = wiki.get("wiki_token") or "Wiki Catalog"
            title = wiki.get("title") or wiki.get("name") or "Wiki Catalog"
            block_id = str(block.get("block_id") or wiki_token)
            placeholder = f"{{{{wikicatalog:{block_id}}}}}"
            self._wiki_catalogs.append(
                WikiCatalogExport(
                    wiki_token=str(wiki_token),
                    block_id=block_id,
                    title=str(title),
                    placeholder=placeholder,
                )
            )
            self._builder.add_paragraph(placeholder)
            return next_list_level

        if block_type == "agenda":
            self._builder.add_paragraph("[Agenda]")
            return next_list_level

        if block_type == "link_preview":
            link_preview = self._as_dict(block.get("link_preview"))
            url = link_preview.get("url") or ""
            self._builder.add_paragraph(f"[LinkPreview: {url}]")
            return next_list_level

        if block_type == "ai_template":
            self._builder.add_paragraph("[AITemplate]")
            return next_list_level

        if block_type == "sub_page_list":
            # 子页面列表 - 在 Wiki 中自动生成的子页面目录
            self._builder.add_paragraph("[子页面列表]")
            return next_list_level

        if block_type == "source_synced":
            # 源同步块 - 被其他文档引用的同步块
            text = self._render_rich_text(self._extract_elements(block))
            if text:
                self._builder.add_paragraph(text)
            else:
                self._builder.add_paragraph("[同步块源]")
            return next_list_level

        if block_type == "reference_synced":
            # 引用同步块 - 引用其他文档的同步块
            text = self._render_rich_text(self._extract_elements(block))
            if text:
                self._builder.add_paragraph(text)
            else:
                self._builder.add_paragraph("[同步块引用]")
            return next_list_level

        if block_type in {"agenda_item", "agenda_item_title", "agenda_item_content"}:
            # 会议议程项
            text = self._render_rich_text(self._extract_elements(block))
            if text:
                self._builder.add_paragraph(text)
            return next_list_level

        if block_type == "isv":
            # 小组件 - 第三方集成
            self._builder.add_paragraph("[小组件]")
            return next_list_level

        if block_type == "undefined":
            self._builder.add_comment(f"Undefined block type: {original_type}")
            return next_list_level

        # Fallback
        text = self._render_rich_text(self._extract_elements(block))
        if text:
            self._builder.add_paragraph(text)
        else:
            self._builder.add_comment(f"Unsupported block type: {original_type}")
        return next_list_level

    # ------------------------------------------------------------------ helpers

    def _extract_elements(self, parent: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
        normalized = self._normalise_block_type(parent) if isinstance(parent, Mapping) else ""
        candidates = (
            "paragraph",
            "heading",
            "heading1",
            "heading2",
            "heading3",
            "heading4",
            "heading5",
            "heading6",
            "quote",
            "todo",
            "list",
            str(parent.get("block_type") or ""),
            normalized,
            "bullet",
            "ordered",
            "code",
            "elements",
            "rich_text",
            "text",
        )
        data = self._as_dict(parent)
        for key in candidates:
            value = parent.get(key) if isinstance(parent, MutableMapping) else None
            if isinstance(value, Mapping):
                maybe = value.get("elements")
                if isinstance(maybe, Sequence):
                    return [self._as_dict(item) for item in maybe]
                maybe = value.get("rich_text")
                if isinstance(maybe, Mapping) and isinstance(maybe.get("elements"), Sequence):
                    return [self._as_dict(item) for item in maybe["elements"]]
            if isinstance(value, Sequence) and value and isinstance(value[0], Mapping):
                return [self._as_dict(item) for item in value]
        # direct elements key
        elements = data.get("elements")
        if isinstance(elements, Sequence) and elements and isinstance(elements[0], Mapping):
            return [self._as_dict(item) for item in elements]
        return []

    @staticmethod
    def _split_sheet_token(token: str) -> tuple[str, str | None]:
        if "_" in token:
            spreadsheet_token, sheet_id = token.split("_", 1)
            return spreadsheet_token, sheet_id or None
        return token, None

    def _extract_indent(self, block: Mapping[str, object]) -> int:
        indent = block.get("indent") or block.get("indent_level")
        try:
            return int(str(indent or "0"))
        except (TypeError, ValueError):
            return 0

    def _resolve_list_indent(self, block: Mapping[str, object], parent_type: str | None, list_level: int) -> int:
        indent = self._extract_indent(block)
        if indent == 0 and list_level and parent_type in self._list_block_types:
            return list_level
        return indent

    def _extract_heading_level(self, block_type: str, block: Mapping[str, object]) -> int:
        if block_type.startswith("heading"):
            try:
                return int(block_type.replace("heading", ""))
            except ValueError:
                pass
        heading = block.get("heading")
        if isinstance(heading, Mapping):
            level = heading.get("level") or heading.get("heading_level")
            if isinstance(level, int):
                return level
        return 1

    def _render_rich_text(self, elements: Sequence[Mapping[str, object]]) -> str:
        parts: List[str] = []
        for element in elements:
            if "text_run" in element:
                parts.append(self._render_text_run(self._as_dict(element["text_run"])))
            elif "link" in element:
                parts.append(self._render_link(self._as_dict(element["link"])))
            elif "inline_code" in element:
                inline = self._as_dict(element["inline_code"])
                text = inline.get("text") or ""
                parts.append(f"`{text}`")
            elif "mention" in element:
                parts.append(self._render_mention(self._as_dict(element["mention"])))
            elif "mention_doc" in element:
                parts.append(self._render_mention_doc(self._as_dict(element["mention_doc"])))
            elif "mention_user" in element:
                parts.append(self._render_mention_user(self._as_dict(element["mention_user"])))
            elif "equation" in element:
                eq = self._as_dict(element["equation"])
                latex = eq.get("latex") or eq.get("content") or ""
                parts.append(f"${latex}$")
            elif "image" in element:
                # Inline image within paragraph.
                inline_image = self._as_dict(element["image"])
                block_id = inline_image.get("block_id") or inline_image.get("image_id") or inline_image.get("token")
                placeholder = f"{{{{image:{block_id}}}}}"
                resource = DocxResource(
                    resource_type="image",
                    token=str(inline_image.get("token") or inline_image.get("image_token") or block_id),
                    name=str(inline_image.get("caption") or inline_image.get("name") or "Image"),
                    block_id=str(block_id),
                    placeholder=placeholder,
                )
                self._images.append(resource)
                parts.append(placeholder)
            else:
                text = element.get("text") or ""
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)

    def _render_text_run(self, run: Mapping[str, object]) -> str:
        text = str(run.get("content") or "")
        style = self._as_dict(run.get("text_element_style"))
        if not text:
            return ""

        link_info = self._as_dict(style.get("link"))
        url = link_info.get("url") or link_info.get("href")
        if url:
            self._nested_links.add(str(url))

        text = html.escape(text, quote=False)
        if style.get("code_inline"):
            text = f"`{text}`"
        if style.get("bold"):
            text = f"**{text}**"
        if style.get("italic"):
            text = f"*{text}*"
        if style.get("strikethrough") or style.get("strike"):
            text = f"~~{text}~~"
        if style.get("underline"):
            text = f"<u>{text}</u>"
        if url:
            text = f"[{text}]({url})"
        return text

    def _render_link(self, link: Mapping[str, object]) -> str:
        url = link.get("url") or link.get("href") or ""
        text = link.get("text") or url
        if url:
            self._nested_links.add(str(url))
        return f"[{text}]({url})" if url else str(text)

    def _render_mention(self, mention: Mapping[str, object]) -> str:
        mention_type = mention.get("mention_type") or mention.get("type")
        name = mention.get("user_name") or mention.get("text") or mention.get("name") or mention_type or "mention"
        return f"@{name}"

    def _render_mention_doc(self, data: Mapping[str, object]) -> str:
        title = data.get("title") or data.get("token") or "document"
        url = data.get("url")
        if url:
            self._nested_links.add(str(url))
            return f"[{title}]({url})"
        token = data.get("token")
        if token:
            return f"[{title}](#doc-{token})"
        return str(title)

    def _render_mention_user(self, data: Mapping[str, object]) -> str:
        name = data.get("user_name") or data.get("name") or data.get("text")
        user_id = data.get("user_id") or data.get("open_id") or data.get("union_id")
        label = name or user_id or "user"
        return f"@{label}"

    def _extract_code_text(self, code: Mapping[str, object]) -> str:
        if "text" in code and isinstance(code["text"], str):
            return code["text"]
        lines = code.get("lines")
        if isinstance(lines, Sequence):
            return "\n".join(str(line) for line in lines)
        elements = code.get("elements")
        if isinstance(elements, Sequence):
            parts: List[str] = []
            for element in elements:
                data = self._as_dict(element)
                if "text_run" in data:
                    run = self._as_dict(data["text_run"])
                    parts.append(str(run.get("content") or ""))
                elif "text" in data:
                    parts.append(str(data.get("text") or ""))
            return "".join(parts)
        return ""

    def _handle_image_block(self, block: Mapping[str, object]) -> str:
        image = self._as_dict(block.get("image"))
        block_id = str(block.get("block_id") or image.get("block_id") or image.get("image_id") or image.get("token"))
        token = str(image.get("token") or image.get("image_token") or image.get("file_token") or block_id)
        name = str(image.get("caption") or image.get("name") or image.get("alt") or f"Image {block_id}")
        placeholder = f"{{{{image:{block_id}}}}}"

        resource = DocxResource(
            resource_type="image",
            token=token,
            name=name,
            block_id=block_id,
            placeholder=placeholder,
            mime_type=str(image.get("mime_type") or ""),
        )
        self._images.append(resource)
        return placeholder

    def _handle_attachment_block(self, block: Mapping[str, object]) -> str:
        attachment = self._as_dict(block.get("file_attachment") or block.get("file"))
        block_id = str(block.get("block_id") or attachment.get("block_id") or attachment.get("file_token"))
        token = str(attachment.get("file_token") or attachment.get("token") or block_id)
        name = str(attachment.get("file_name") or attachment.get("name") or f"Attachment {block_id}")
        placeholder = f"{{{{attachment:{block_id}}}}}"
        resource = DocxResource(
            resource_type="attachment",
            token=token,
            name=name,
            block_id=block_id,
            placeholder=placeholder,
            mime_type=str(attachment.get("mime_type") or ""),
        )
        self._attachments.append(resource)
        return placeholder

    def _handle_whiteboard(self, block: Mapping[str, object]) -> tuple[str, str]:
        board = self._as_dict(block.get("board") or block.get("whiteboard"))
        block_id = str(block.get("block_id") or board.get("block_id") or board.get("token") or "")
        whiteboard_id = str(
            board.get("token") or board.get("whiteboard_token") or board.get("whiteboard_id") or block_id
        )
        name = str(board.get("title") or block_id or whiteboard_id or "whiteboard")

        image_placeholder = f"{{{{whiteboard_image:{block_id}}}}}"
        json_placeholder = f"{{{{whiteboard_json:{block_id}}}}}"

        self._whiteboards.append(
            WhiteboardExport(
                whiteboard_id=whiteboard_id,
                block_id=block_id or whiteboard_id,
                name=name or whiteboard_id,
                image_placeholder=image_placeholder,
                json_placeholder=json_placeholder,
            )
        )
        return image_placeholder, json_placeholder

    def _render_grid(self, block: Mapping[str, object]) -> None:
        # Grid acts as a column container; handled by individual columns.
        return

    def _render_grid_column(self, block: Mapping[str, object], list_level: int) -> None:
        block_id = str(block.get("block_id") or "")
        if block_id in self._consumed_blocks:
            return
        parent_id = str(block.get("parent_id") or "")
        siblings = self._children_index.get(parent_id, [])
        index = 1
        for idx, sibling in enumerate(siblings, start=1):
            if sibling is block:
                index = idx
                break
        if len(siblings) > 1:
            self._builder.add_paragraph(f"**Column {index}**")
        self._consumed_blocks.add(block_id)
        for child in self._children_index.get(block_id, []):
            self._render_block_tree(child, parent_type="grid_column", list_level=0)

    def _render_table(self, block: Mapping[str, object]) -> str:
        table = self._as_dict(block.get("table") or block.get("grid") or block.get("grid_container"))
        cells = table.get("cells")
        if isinstance(cells, Sequence) and cells and isinstance(cells[0], str):
            column_size = int(str(self._as_dict(table.get("property")).get("column_size") or "0"))
            if column_size <= 0:
                column_size = len(cells)
            rows = [list(cells[i : i + column_size]) for i in range(0, len(cells), column_size)]
        else:
            rows = table.get("rows")

        if not isinstance(rows, Sequence):
            return "[Table content not available]"

        rendered_rows: List[List[str]] = []
        for row in rows:
            if isinstance(row, Mapping) and "cells" in row:
                cell_ids = row["cells"]
            else:
                cell_ids = row

            if isinstance(cell_ids, Sequence):
                rendered_row = [self._render_table_cell(cell_id) for cell_id in cell_ids]
                rendered_rows.append(rendered_row)
                for cell_id in cell_ids:
                    if isinstance(cell_id, str):
                        self._consumed_blocks.add(cell_id)

        if not rendered_rows:
            return "[Empty table]"
        # build markdown table
        header = rendered_rows[0]
        lines = ["| " + " | ".join(cell or " " for cell in header) + " |"]
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in rendered_rows[1:]:
            lines.append("| " + " | ".join(cell or " " for cell in row) + " |")
        return "\n".join(lines)

    @staticmethod
    def _as_dict(value: object) -> MutableMapping[str, object]:
        if isinstance(value, MutableMapping):
            return value  # type: ignore[return-value]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, MutableMapping):
                    return parsed  # type: ignore[return-value]
            except json.JSONDecodeError:
                pass
        return {}

    def _normalise_block_type(self, block: Mapping[str, object]) -> str:
        raw = block.get("block_type")
        if isinstance(raw, int):
            key = str(raw)
        elif isinstance(raw, str):
            key = raw.lower()
        else:
            key = str(raw or "")

        if key in self._BLOCK_TYPE_ALIASES:
            return self._BLOCK_TYPE_ALIASES[key]

        # If block_type exists but not in aliases, return it directly
        # to avoid misidentification through payload inference
        if raw is not None and raw != "":
            return key

        # Attempt to infer from payload keys ONLY when block_type is completely missing.
        # This is a fallback mechanism for edge cases.
        for candidate in (
            "page",
            "paragraph",
            "heading1",
            "heading2",
            "heading3",
            "heading4",
            "heading5",
            "heading6",
            "bullet",
            "ordered",
            "todo",
            "quote",
            "code",
            "divider",
            "table",
            "grid",
            "grid_column",
            "view",
            "quote_container",
            "file",
            "image",
            "board",
        ):
            if candidate in block:
                return candidate
        return key

    def _render_table_cell(self, cell: object) -> str:
        if isinstance(cell, Mapping):
            elements = self._extract_elements(cell)
            if elements:
                return self._render_rich_text(elements).strip()
            cell_id = cell.get("block_id")
        else:
            cell_id = cell

        if not isinstance(cell_id, str):
            return ""

        cell_block = self._block_index.get(cell_id)
        if not isinstance(cell_block, Mapping):
            return ""

        child_ids = cell_block.get("children")
        if not isinstance(child_ids, Sequence):
            return ""

        parts: List[str] = []
        for child_id in child_ids:
            if not isinstance(child_id, str):
                continue
            child_block = self._block_index.get(child_id)
            if not isinstance(child_block, Mapping):
                continue
            self._consumed_blocks.add(child_id)
            text = self._render_rich_text(self._extract_elements(child_block)).strip()
            if text:
                parts.append(text)
        return "\n".join(parts)
