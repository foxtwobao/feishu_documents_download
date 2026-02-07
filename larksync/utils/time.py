"""Time-related helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Union


def normalize_timestamp(value: Union[str, int, float, None]) -> Optional[str]:
    """
    Canonicalize timestamps to ISO 8601 with timezone information.

    Args:
        value: Raw timestamp value from Feishu (string or epoch seconds).

    Returns:
        ISO 8601 string in UTC, or ``None`` if the input is empty/invalid.
    """

    if value is None:
        return None

    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        return dt.isoformat()

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        text = text.replace(" ", "T")
        if text.isdigit():
            return text
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        elif not re.search(r"[+-]\d\d:\d\d$", text):
            # 缺少时区信息时默认视为 UTC，避免 API 轮询时格式差异造成重复下载
            text = f"{text}+00:00"

        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return text

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc).isoformat()

    return str(value)
