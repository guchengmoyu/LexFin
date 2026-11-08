"""Cleaner 单元测试（docs/09 test_cleaner）。

覆盖：页码行删除、断行合并、空白归一（NFKC）、重复行去重、页眉页脚识别。
"""
from __future__ import annotations

import pytest

from app.rag.cleaner import Cleaner
from app.rag.types import PageContent, ParsedDocument, TextBlock


def _joined(lines):
    return "\n".join(Cleaner().clean_lines(lines))


@pytest.mark.unit
def test_page_number_lines_removed():
    out = _joined(["第一条为加强流动性风险管理制定本办法。", "12", "- 13 -", "— 14 —", "第二条本办法适用于银行业金融机构。"])
    assert "12" not in out and "13" not in out and "14" not in out
    assert "第一条" in out and "第二条" in out


@pytest.mark.unit
def test_broken_line_merged():
    out = _joined(["商业银行应当确保其流动性覆盖率", "始终高于监管标准。"])
    assert out == "商业银行应当确保其流动性覆盖率始终高于监管标准。"


@pytest.mark.unit
def test_broken_line_english_hyphen():
    out = _joined(["liquidity cover-", "age ratio"])
    assert out == "liquidity coverage ratio"


@pytest.mark.unit
def test_sentence_boundary_not_merged():
    out = _joined(["第一句内容结束。", "第二句内容开始。"])
    assert out == "第一句内容结束。\n第二句内容开始。"


@pytest.mark.unit
def test_whitespace_normalized():
    out = _joined(["流动性覆盖率　不低于\t100％"])
    assert out == "流动性覆盖率 不低于 100%", "全角数字/空格/Tab 归一"


@pytest.mark.unit
def test_duplicate_line_removed():
    out = _joined(["本资料仅供内部参考使用。", "本资料仅供内部参考使用。", "银行业金融机构应当审慎经营。"])
    assert out.count("本资料仅供内部参考使用。") == 1, "同页重复行应去重"
    assert "银行业金融机构应当审慎经营。" in out


@pytest.mark.unit
def test_header_footer_detected():
    pages = [
        PageContent(
            page_no=p,
            blocks=[
                TextBlock(type="text", text="商业银行流动性风险管理办法试行版", page_no=p),
                TextBlock(type="text", text=f"第{p}页正文内容各不相同。", page_no=p),
                TextBlock(type="text", text="本资料仅供内部参考使用。", page_no=p),
            ],
            char_count=100,
            used_ocr=False,
        )
        for p in range(1, 6)
    ]
    repeated = Cleaner().find_repeated_lines(pages)
    assert repeated == {"商业银行流动性风险管理办法试行版", "本资料仅供内部参考使用。"}


@pytest.mark.unit
def test_header_footer_removed_in_document():
    pages = [
        PageContent(
            page_no=p,
            blocks=[
                TextBlock(type="text", text="商业银行流动性风险管理办法试行版", page_no=p),
                TextBlock(type="text", text=f"第{p}页正文内容各不相同。", page_no=p),
                TextBlock(type="text", text="本资料仅供内部参考使用。", page_no=p),
            ],
            char_count=100,
            used_ocr=False,
        )
        for p in range(1, 6)
    ]
    parsed = ParsedDocument(
        file_name="t.docx", file_ext="docx", pages=pages,
        parse_method="text", meta={},
    )
    result = Cleaner().clean_document(parsed)

    lines = [line for line, _ in result]
    assert lines, "正文应保留"
    assert all("本资料仅供内部参考使用。" not in line for line in lines)
    assert all("管理办法试行版" not in line for line in lines)
    assert [page for _, page in result][:1] == [1], "页号保留"


@pytest.mark.unit
def test_find_repeated_lines_empty():
    assert Cleaner().find_repeated_lines([]) == set()
