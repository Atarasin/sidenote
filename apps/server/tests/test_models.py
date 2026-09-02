"""BookDoc 模型与共享 JSON Schema / 示例的一致性。"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from app.books.models import BookDoc, make_chapter_id, make_para_id

SHARED = Path(__file__).resolve().parents[3] / "shared" / "types"
EXAMPLE = json.loads((SHARED / "examples" / "bookdoc.example.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((SHARED / "bookdoc.schema.json").read_text(encoding="utf-8"))


def test_example_matches_json_schema() -> None:
    jsonschema.validate(EXAMPLE, SCHEMA)


def test_example_matches_pydic_model() -> None:
    doc = BookDoc.model_validate(EXAMPLE)
    assert doc.chapters[0].paras[0].id == "c001-p0001"


def test_para_id_rules() -> None:
    # 章节序 + 段序，1 起、稳定
    assert make_chapter_id(1) == "c001"
    assert make_para_id(1, 1) == "c001-p0001"
    assert make_para_id(12, 345) == "c012-p0345"
    with pytest.raises(ValueError):
        BookDoc.model_validate(
            {
                "meta": {"bookId": "0" * 16, "title": "t", "format": "epub", "fileHash": "a" * 64},
                "toc": [],
                "chapters": [
                    {"id": "ch1", "title": "x", "paras": [{"id": "c001-p0001", "text": "y"}]}
                ],
                "figures": [],
            }
        )
