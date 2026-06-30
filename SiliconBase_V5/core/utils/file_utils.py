#!/usr/bin/env python3
"""
文件工具 - 强制 UTF-8 编码，防止跨平台乱码
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

治理目标：消灭所有不带 encoding='utf-8' 的文本文件 open() 调用。
所有文本文件 I/O 必须通过此模块。

Windows 上 Python 默认编码是 GBK，Linux/Mac 是 UTF-8。
不指定编码会导致跨平台乱码和数据损坏。
"""

import json
from pathlib import Path
from typing import Any


def read_text(path: Path, encoding: str = "utf-8") -> str:
    """读取文本文件（默认 UTF-8）"""
    return path.read_text(encoding=encoding)


def write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """写入文本文件（默认 UTF-8）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding)


def read_json(path: Path, encoding: str = "utf-8") -> Any:
    """读取 JSON 文件"""
    with open(path, encoding=encoding) as f:
        return json.load(f)


def write_json(
    path: Path,
    data: Any,
    encoding: str = "utf-8",
    indent: int = 2,
    ensure_ascii: bool = False
) -> None:
    """写入 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=encoding) as f:
        json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)


def read_jsonl(path: Path, encoding: str = "utf-8") -> list:
    """读取 JSON Lines 文件"""
    records = []
    with open(path, encoding=encoding) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(
    path: Path,
    records: list,
    encoding: str = "utf-8",
    append: bool = False
) -> None:
    """写入 JSON Lines 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with open(path, mode, encoding=encoding) as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
