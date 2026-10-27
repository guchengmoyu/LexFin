"""时间工具：统一 Asia/Shanghai 本地时间口径（docs/06 §1）。"""
from __future__ import annotations

import random
import string
from datetime import date, datetime
from typing import Any, Optional


def now() -> datetime:
    """应用层统一使用本地时间（UTC+8），存储口径一致。"""
    return datetime.now()


def fmt_datetime(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def fmt_date(d: Optional[date]) -> Optional[str]:
    return d.strftime("%Y-%m-%d") if d else None


def parse_date(value: Any) -> Optional[date]:
    """解析日期：兼容 Excel 日期对象、ISO 8601（含 Z 时区）与常见中文/分隔符写法。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Excel 写出的 ISO 8601，如 2018-07-01T00:00:00.000Z
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def gen_no(prefix: str) -> str:
    """生成业务编号：{prefix}_yyyymmddHHMMSS_xxxxxx（session_no/task_no）。"""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{prefix}_{stamp}_{rand}"
