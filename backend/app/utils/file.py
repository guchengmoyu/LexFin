"""文件安全工具：类型/大小/魔数校验、MD5、安全文件名（docs/06 §6 上传安全）。"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.constants import ErrorCode
from app.core.exceptions import BizError

#: 常见文件头魔数（用于 Content-Type 嗅探兜底）
MAGIC_NUMBERS: dict[str, list[bytes]] = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".gif": [b"GIF8"],
    ".tiff": [b"II*\x00", b"MM\x00*"],
}


def check_extension(file_name: str) -> str:
    ext = Path(file_name).suffix.lower()
    if ext not in settings.allowed_extension_list:
        raise BizError(
            ErrorCode.FILE_TYPE_NOT_ALLOWED,
            f"不支持的文件类型 {ext or '(无扩展名)'}，仅支持 {'、'.join(settings.allowed_extension_list)}",
        )
    return ext


def check_size(size: int) -> None:
    if size <= 0:
        raise BizError(ErrorCode.FILE_EMPTY, "文件为空或已损坏")
    if size > settings.max_file_size_bytes:
        raise BizError(
            ErrorCode.FILE_TOO_LARGE,
            f"文件超过大小限制（{settings.max_file_size_mb}MB）",
        )


def check_magic(ext: str, head: bytes) -> None:
    """文件头魔数校验；对无魔数约定的格式（txt/md/docx）跳过。"""
    patterns = MAGIC_NUMBERS.get(ext)
    if not patterns:
        return
    if not any(head.startswith(p) for p in patterns):
        raise BizError(ErrorCode.FILE_TYPE_NOT_ALLOWED, "文件内容与扩展名不符，可能已损坏")


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_store(file_name: str, data: bytes, subdir: str = "") -> tuple[str, str, str]:
    """落盘并返回 (绝对路径, uuid 文件名, md5)。

    文件名服务端重命名（{uuid}.{ext}），不使用用户原始文件名做路径（docs/06 §6）。
    """
    ext = check_extension(file_name)
    check_size(len(data))
    check_magic(ext, data[:16])

    base_dir = Path(settings.upload_dir) / subdir if subdir else Path(settings.upload_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    abs_path = base_dir / stored_name
    abs_path.write_bytes(data)
    return str(abs_path.resolve()), stored_name, md5_bytes(data)
