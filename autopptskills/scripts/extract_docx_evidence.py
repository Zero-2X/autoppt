#!/usr/bin/env python3
"""Extract ordered paragraphs, tables, and embedded media from a DOCX source."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterator
from zipfile import ZipFile

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+){0,3}[\s.、]|第[一二三四五六七八九十百0-9]+[章节部分篇]|"
    r"摘要|目录|引言|绪论|结论|总结|参考文献|附录)$"
)


def _normalize(text: str) -> str:
    return " ".join(str(text or "").replace("\u00a0", " ").split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_blocks(document: DocumentType) -> Iterator[Paragraph | Table]:
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _outline_level(paragraph: Paragraph) -> int | None:
    values = paragraph._p.xpath("./w:pPr/w:outlineLvl/@w:val")
    if not values:
        return None
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


def _heading_level(paragraph: Paragraph, text: str) -> int | None:
    outline = _outline_level(paragraph)
    if outline is not None:
        return min(6, outline + 1)
    style = paragraph.style.name if paragraph.style else ""
    match = re.search(r"(?:Heading|Title)\s*([1-6])", style, flags=re.I)
    if match:
        return int(match.group(1))
    if HEADING_RE.match(text) and len(text) <= 36:
        dot_depth = text.split(maxsplit=1)[0].count(".")
        return min(4, dot_depth + 1)
    return None


def _extract_media(source: Path, media_dir: Path) -> list[dict[str, Any]]:
    media_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with ZipFile(source) as archive:
        names = sorted(name for name in archive.namelist() if name.startswith("word/media/") and not name.endswith("/"))
        for index, name in enumerate(names, 1):
            original_name = Path(name).name
            suffix = Path(original_name).suffix.lower() or ".bin"
            target = media_dir / f"media-{index:03d}{suffix}"
            with archive.open(name) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            record: dict[str, Any] = {
                "id": f"media-{index:03d}",
                "original_name": original_name,
                "path": str(target.resolve()),
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            }
            try:
                from PIL import Image

                with Image.open(target) as image:
                    record["width"] = image.width
                    record["height"] = image.height
                    record["format"] = image.format
            except Exception:
                record["width"] = None
                record["height"] = None
                record["format"] = suffix.lstrip(".").upper()
            records.append(record)
    return records


def extract(source: Path, media_dir: Path) -> dict[str, Any]:
    document = Document(source)
    blocks: list[dict[str, Any]] = []
    paragraphs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []

    for block_index, block in enumerate(_iter_blocks(document), 1):
        if isinstance(block, Paragraph):
            text = _normalize(block.text)
            if not text:
                continue
            style = block.style.name if block.style else ""
            record = {
                "id": f"paragraph-{len(paragraphs) + 1:04d}",
                "block_index": block_index,
                "text": text,
                "style": style,
                "heading_level": _heading_level(block, text),
            }
            paragraphs.append(record)
            blocks.append({"type": "paragraph", "ref": record["id"]})
            continue

        rows = [
            [_normalize(cell.text) for cell in row.cells]
            for row in block.rows
        ]
        record = {
            "id": f"table-{len(tables) + 1:03d}",
            "block_index": block_index,
            "rows": rows,
            "row_count": len(rows),
            "column_count": max((len(row) for row in rows), default=0),
        }
        tables.append(record)
        blocks.append({"type": "table", "ref": record["id"]})

    media = _extract_media(source, media_dir)
    return {
        "source": str(source.resolve()),
        "source_sha256": _sha256(source),
        "statistics": {
            "paragraphs": len(paragraphs),
            "tables": len(tables),
            "media": len(media),
            "inline_shapes": len(document.inline_shapes),
            "sections": len(document.sections),
        },
        "blocks": blocks,
        "paragraphs": paragraphs,
        "tables": tables,
        "media": media,
    }


def _write_markdown(data: dict[str, Any], output: Path) -> None:
    paragraph_map = {item["id"]: item for item in data["paragraphs"]}
    table_map = {item["id"]: item for item in data["tables"]}
    lines = ["# DOCX Evidence Export", "", f"Source: `{data['source']}`", ""]
    for block in data["blocks"]:
        if block["type"] == "paragraph":
            item = paragraph_map[block["ref"]]
            level = item.get("heading_level")
            lines.append(("#" * level + " " if level else "") + item["text"])
            lines.append("")
            continue
        table = table_map[block["ref"]]
        rows = table["rows"]
        if not rows:
            continue
        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        lines.append("| " + " | ".join(normalized[0]) + " |")
        lines.append("| " + " | ".join(["---"] * width) + " |")
        for row in normalized[1:]:
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    lines.extend(["## Embedded Media", ""])
    for item in data["media"]:
        dims = f"{item.get('width')}x{item.get('height')}" if item.get("width") else "unknown"
        lines.append(f"- `{item['id']}` `{item['original_name']}` {dims} {item['bytes']} bytes")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--markdown-out")
    parser.add_argument("--media-dir", required=True)
    args = parser.parse_args()

    source = Path(args.source).resolve()
    if not source.exists():
        parser.error(f"source not found: {source}")
    data = extract(source, Path(args.media_dir).resolve())
    output = Path(args.json_out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_out:
        _write_markdown(data, Path(args.markdown_out).resolve())
    print(json.dumps(data["statistics"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
