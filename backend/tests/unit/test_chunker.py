"""Chunker 单元测试（docs/09 §3.3 test_chunker ★）。

覆盖：标准条文切分、章节归属、超长条滑窗、极短条合并、不跨章合并、
无条结构、页码映射（含滑窗页码）、跨页条、表格块、前缀格式、
中文数字条号、空输入、幂等、切分自检。
"""
from __future__ import annotations

import pytest

from app.rag.chunker import Chunker, ChunkerParams
from app.rag.types import RawChunk

DOC_TITLE = "商业银行流动性风险管理办法"
DOC_NO = "银保监会令2018年第3号"

ARTICLE_NOS = ["第一条", "第二条", "第三条", "第四条", "第五条"]
BODY_SENTENCE = "流动性风险管理应当遵循审慎原则确保资产安全稳健运行。"  # 22 字


def _body(repeat: int = 6) -> str:
    """≥120 字的条文正文（默认 132 字，避免触发极短条合并）。"""
    return BODY_SENTENCE * repeat


def _short_body() -> str:
    """恰好 30 字的极短条文正文。"""
    s = "本条内容简短仅供测试使用补足三十字符"  # 17 字
    return (s + "补充说明文字若干。")[:30]  # 30 字


def _distinct_text(n: int, start: int = 0x4E00) -> str:
    """n 个互不相同的汉字（避开切分分隔符），保证滑窗位置唯一可寻。"""
    return "".join(chr(start + i) for i in range(n))


def _article(no: str, body: str) -> str:
    return f"{no} {body}"


def _doc(lines, page_no: int = 1, block_type: str = "text", make_parsed=None):
    return make_parsed([(page_no, [(block_type, "\n".join(lines))])])


# --------------------------------------------------------------------------- #
#  标准条文切分
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_standard_five_articles(make_parsed):
    lines = [_article(no, _body()) for no in ARTICLE_NOS]
    chunks = Chunker().split(_doc(lines, make_parsed=make_parsed), DOC_TITLE, DOC_NO)

    assert len(chunks) == 5
    assert [c.article_no for c in chunks] == ARTICLE_NOS
    assert all(c.source_type == "text" for c in chunks)


@pytest.mark.unit
def test_chapter_attribution(make_parsed):
    lines = ["第三章 流动性风险管理", _article("第二条", _body())]
    chunks = Chunker().split(_doc(lines, make_parsed=make_parsed), DOC_TITLE, DOC_NO)

    assert len(chunks) == 1
    assert chunks[0].chapter_no == "第三章"
    assert "第三章 流动性风险管理" in chunks[0].content


# --------------------------------------------------------------------------- #
#  超长条滑窗切分
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_long_article_multi_chunks_same_article_no(make_parsed):
    text = _article("第一百条", _distinct_text(2000))
    chunks = Chunker().split(_doc([text], make_parsed=make_parsed), DOC_TITLE, DOC_NO)

    assert len(chunks) >= 3
    assert all(c.article_no == "第一百条" for c in chunks)
    # 入库顺序保证：首个切片从条首开始，末个切片以条尾结束
    assert chunks[0].raw_content.startswith("第一百条")
    assert chunks[-1].raw_content.endswith(_distinct_text(2000)[-20:])


@pytest.mark.unit
def test_long_article_adjacent_overlap_80_chars(make_parsed):
    """相邻滑窗块保持 CHUNK_OVERLAP=80 字重叠，且重叠不多不少。"""
    text = _article("第一百条", _distinct_text(2000))
    chunks = Chunker(ChunkerParams(chunk_size=500, chunk_overlap=80)).split(
        _doc([text], make_parsed=make_parsed), DOC_TITLE, DOC_NO
    )

    assert len(chunks) >= 2
    for prev, cur in zip(chunks, chunks[1:]):
        assert prev.raw_content[-80:] == cur.raw_content[:80], "相邻块应有 80 字重叠"
        assert prev.raw_content[-81:] != cur.raw_content[:81], "重叠应恰好 80 字"


@pytest.mark.unit
def test_long_article_page_mapping_per_chunk(make_parsed):
    """滑窗子块的页码跨度 = 该块覆盖字符所在页的最小/最大页号（docs/04 §6.4）。"""
    lines = [
        _article("第一百零五条", _distinct_text(700, 0x4E00)),   # 第 12 页
        _distinct_text(700, 0x6000),                              # 第 13 页
        _distinct_text(700, 0x7200),                              # 第 14 页
    ]
    pages = [(12, [("text", lines[0])]), (13, [("text", lines[1])]), (14, [("text", lines[2])])]
    parsed = make_parsed(pages)

    chunks = Chunker().split(parsed, DOC_TITLE, DOC_NO)
    assert len(chunks) >= 3

    # 期望页码 oracle：每个字符的页号
    full_text = "\n".join(lines)
    char_pages = []
    for line_text, page in zip(lines, [12, 13, 14]):
        char_pages.extend([page] * (len(line_text) + 1))  # 换行符归上一行

    search_from = 0
    for chunk in chunks:
        pos = full_text.find(chunk.raw_content, search_from)
        assert pos >= 0, "切片应能按顺序在原文中定位"
        search_from = pos + 1
        span_pages = char_pages[pos : pos + len(chunk.raw_content)]
        assert chunk.page_start == min(span_pages), f"切片起始页错误: {chunk.raw_content[:10]}"
        assert chunk.page_end == max(span_pages), f"切片结束页错误: {chunk.raw_content[:10]}"


# --------------------------------------------------------------------------- #
#  极短条合并
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_short_articles_merged_range_default_params(make_parsed):
    """5 条各 30 字：合并后 article_no 为区间『第X条~第Y条』。"""
    lines = [_article(no, _short_body()) for no in ARTICLE_NOS]
    chunks = Chunker().split(_doc(lines, make_parsed=make_parsed), DOC_TITLE, DOC_NO)

    assert 1 <= len(chunks) <= 2
    assert "~" in chunks[0].article_no, "首块应为合并区间"
    assert chunks[0].article_no.startswith("第一条~")
    assert chunks[0].article_no.endswith("条")
    # 区间格式：只保留首尾条号
    assert chunks[0].article_no.count("~") == 1


@pytest.mark.unit
def test_short_articles_merge_exact_range(make_parsed):
    """提高合并阈值使 5 条全部合并为 1 块，article_no = 第一条~第五条。"""
    lines = [_article(no, _short_body()) for no in ARTICLE_NOS]
    params = ChunkerParams(chunk_min_merge=300)
    chunks = Chunker(params).split(_doc(lines, make_parsed=make_parsed), DOC_TITLE, DOC_NO)

    assert len(chunks) == 1
    assert chunks[0].article_no == "第一条~第五条"


@pytest.mark.unit
def test_no_cross_chapter_merge(make_parsed):
    """第一章末尾短条 + 第二章开头短条：绝不合并。"""
    lines = [
        "第一章 总则",
        _article("第一条", _short_body()),
        "第二章 监管职责",
        _article("第二条", _short_body()),
    ]
    chunks = Chunker().split(_doc(lines, make_parsed=make_parsed), DOC_TITLE, DOC_NO)

    assert len(chunks) == 2
    assert chunks[0].chapter_no == "第一章"
    assert chunks[1].chapter_no == "第二章"
    assert [c.article_no for c in chunks] == ["第一条", "第二条"]
    assert all("~" not in (c.article_no or "") for c in chunks)


# --------------------------------------------------------------------------- #
#  无条结构 / 页码 / 表格
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_no_article_structure_article_no_none(make_parsed):
    notice = "为规范银行业金融机构操作风险管理，根据《中华人民共和国银行业监督管理法》制定本通知。" * 3
    chunks = Chunker().split(_doc([notice], make_parsed=make_parsed), DOC_TITLE, DOC_NO)

    assert len(chunks) >= 1
    assert all(c.article_no is None for c in chunks)


@pytest.mark.unit
def test_page_mapping_single_page(make_parsed):
    """第 12 页中部的条 → page_start == page_end == 12。"""
    lines = ["第九条 本条位于第十二页中部。" + _body(5)]
    parsed = make_parsed([(12, [("text", lines[0])])])
    chunks = Chunker().split(parsed, DOC_TITLE, DOC_NO)

    assert len(chunks) == 1
    assert chunks[0].page_start == 12
    assert chunks[0].page_end == 12


@pytest.mark.unit
def test_cross_page_article(make_parsed):
    """第 12 页末到第 13 页初的条 → page_start=12, page_end=13。"""
    page12 = "第二条 银行业金融机构应当建立健全流动性风险管理制度。" + "董事会承担最终责任。" * 5
    page13 = "高级管理层负责组织实施并定期评估。" * 3
    parsed = make_parsed(
        [(12, [("text", page12)]), (13, [("text", page13)])]
    )
    chunks = Chunker().split(parsed, DOC_TITLE, DOC_NO)

    assert len(chunks) == 1
    assert chunks[0].page_start == 12
    assert chunks[0].page_end == 13


@pytest.mark.unit
def test_table_block_source_type_and_header(make_parsed):
    table = (
        "指标\t达标标准\t监测频率\n"
        "流动性覆盖率\t不低于100%\t每日\n"
        "净稳定资金比例\t不低于100%\t每月"
    )
    parsed = make_parsed(
        [(1, [("text", _article("第十条", _body())), ("table", table)])]
    )
    chunks = Chunker().split(parsed, DOC_TITLE, DOC_NO)

    table_chunks = [c for c in chunks if c.source_type == "table"]
    assert len(table_chunks) == 1
    tc = table_chunks[0]
    assert "指标" in tc.raw_content and "达标标准" in tc.raw_content, "应保留表头"
    assert "不低于100%" in tc.raw_content


# --------------------------------------------------------------------------- #
#  前缀 / 中文数字条号 / 空输入 / 幂等
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_content_prefix_format(make_parsed):
    lines = [_article("第三条", _body())]
    chunks = Chunker().split(_doc(lines, make_parsed=make_parsed), DOC_TITLE, DOC_NO)

    content = chunks[0].content
    assert content.startswith("【")
    assert DOC_TITLE in content
    assert DOC_NO in content
    assert "第三条" in content
    assert content.splitlines()[0].endswith("】")
    # raw_content 不含前缀
    assert not chunks[0].raw_content.startswith("【")


@pytest.mark.unit
def test_chinese_numeral_article_no(make_parsed):
    lines = [_article("第一百零二条", _body())]
    chunks = Chunker().split(_doc(lines, make_parsed=make_parsed), DOC_TITLE, DOC_NO)

    assert len(chunks) == 1
    assert chunks[0].article_no == "第一百零二条"


@pytest.mark.unit
def test_empty_input_returns_empty(make_parsed):
    assert Chunker().split(make_parsed([]), DOC_TITLE, DOC_NO) == []
    empty_page = make_parsed([(1, [("text", "")])])
    assert Chunker().split(empty_page, DOC_TITLE, DOC_NO) == []


@pytest.mark.unit
def test_split_idempotent(make_parsed):
    lines = [
        "第三章 流动性风险管理",
        _article("第一条", _body()),
        _article("第二条", _short_body()),
        _article("第三条", _short_body()),
        _article("第四条", _body()),
    ]
    parsed = make_parsed(
        [(1, [("text", "\n".join(lines)), ("table", "指标\t标准值\n流动性覆盖率\t100%")])]
    )

    chunks1 = Chunker().split(parsed, DOC_TITLE, DOC_NO)
    chunks2 = Chunker().split(parsed, DOC_TITLE, DOC_NO)
    assert chunks1 == chunks2, "同一输入两次切分输出应完全一致"


# --------------------------------------------------------------------------- #
#  build_prefix / self_check
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_build_prefix_format():
    prefix = Chunker.build_prefix(
        doc_title=DOC_TITLE,
        doc_no=DOC_NO,
        chapter_label="第三章 流动性风险管理",
        article_no="第二条",
    )
    assert prefix == f"【{DOC_TITLE}｜{DOC_NO}｜第三章 流动性风险管理 第二条】"

    assert Chunker.build_prefix() == "【】"
    assert Chunker.build_prefix(doc_title="T") == "【T】"


@pytest.mark.unit
def test_self_check():
    assert Chunker.self_check([]) == ["未切分出任何内容"]

    healthy = [
        RawChunk(
            raw_content="x" * 150,
            content="【t】" + "x" * 150,
            chapter_no="第一章",
            article_no=f"第{i}条",
            page_start=1,
            page_end=1,
        )
        for i in range(1, 4)
    ]
    assert Chunker.self_check(healthy) == []

    oversized = [
        RawChunk(
            raw_content="x" * 1700,
            content="【t】" + "x" * 1700,
            chapter_no=None,
            article_no="第一条",
            page_start=1,
            page_end=1,
        )
    ]
    warnings = Chunker.self_check(oversized)
    assert any("超长切片" in w for w in warnings)

    too_small = [
        RawChunk(
            raw_content="x" * 40,
            content="【t】" + "x" * 40,
            chapter_no=None,
            article_no=None,
            page_start=1,
            page_end=1,
        )
    ]
    assert any("偏小" in w for w in Chunker.self_check(too_small))
