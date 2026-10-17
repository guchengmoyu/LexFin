"""Citation 单元测试（docs/09 §3.3 test_citation ★）。

覆盖：角标解析、去重、越界过滤与告警日志、无角标、句中角标、
全角括号不匹配、前导零。
"""
from __future__ import annotations

from unittest import mock

import pytest

from app.rag import citation as citation_mod
from app.rag.citation import (
    CITE_PATTERN,
    build_citations,
    cited_ratio,
    extract_cite_indexes,
    out_of_range_ratio,
    resolve,
)


@pytest.mark.unit
def test_extract_two_indexes():
    assert extract_cite_indexes("结论一[1]。结论二[2]。") == {1, 2}


@pytest.mark.unit
def test_cite_pattern_halfwidth_only():
    assert CITE_PATTERN.findall("参考[1]") == ["1"]
    assert CITE_PATTERN.findall("参考【1】") == []


@pytest.mark.unit
def test_extract_in_sentence():
    assert extract_cite_indexes("该指标不得低于100%[1]。") == {1}


@pytest.mark.unit
def test_extract_leading_zero():
    assert extract_cite_indexes("依据[01]的规定") == {1}


@pytest.mark.unit
def test_extract_no_citation():
    assert extract_cite_indexes("本答案没有任何来源标注。") == set()
    assert extract_cite_indexes("") == set()


@pytest.mark.unit
def test_resolve_duplicate_index_once(make_citation):
    citations = [make_citation(cite_index=i) for i in (1, 2, 3)]
    answer = "结论一[1]。再次引用[1]。仍然引用[1]。"

    used = resolve(answer, citations)
    assert [c.cite_index for c in used] == [1], "[1] 重复出现只返回 1 条"


@pytest.mark.unit
def test_resolve_two_indexes_sorted(make_citation):
    citations = [make_citation(cite_index=i) for i in (1, 2, 3)]
    used = resolve("结论二[2]。结论一[1]。", citations)
    assert [c.cite_index for c in used] == [1, 2], "保持 cite_index 升序"


@pytest.mark.unit
def test_resolve_out_of_range_filtered_and_logged(make_citation):
    citations = [make_citation(cite_index=i) for i in (1, 2, 3)]
    with mock.patch.object(citation_mod, "logger") as mock_logger:
        used = resolve("有效引用[1]。越界引用[9]。", citations)

    assert [c.cite_index for c in used] == [1], "[9] 越界应被过滤"
    assert mock_logger.warning.called, "越界角标必须记录 warning 日志"


@pytest.mark.unit
def test_resolve_no_citation_returns_empty(make_citation):
    citations = [make_citation(cite_index=i) for i in (1, 2, 3)]
    assert resolve("根据现有知识库，暂未检索到相关规定。", citations) == []


@pytest.mark.unit
def test_resolve_fullwidth_bracket_not_matched(make_citation):
    citations = [make_citation(cite_index=i) for i in (1, 2, 3)]
    answer = "该指标不得低于100%【1】。"
    assert extract_cite_indexes(answer) == set(), "全角【1】不匹配"
    assert resolve(answer, citations) == [], "全角括号记录为无引用"


@pytest.mark.unit
def test_resolve_leading_zero_maps_to_one(make_citation):
    citations = [make_citation(cite_index=i) for i in (1, 2, 3)]
    used = resolve("依据[01]的规定。", citations)
    assert [c.cite_index for c in used] == [1]


@pytest.mark.unit
def test_out_of_range_ratio_recorded(make_citation):
    citations = [make_citation(cite_index=1)]
    resolve("越界[9]。", citations)  # 越界引用应计入质量指标
    assert out_of_range_ratio() > 0


@pytest.mark.unit
def test_build_citations_numbering(make_item):
    items = [make_item(source_id=i) for i in (11, 12, 13)]
    citations = build_citations(items)
    assert [c.cite_index for c in citations] == [1, 2, 3]
    assert [c.chunk_id for c in citations] == [11, 12, 13]
    assert citations[0].source_url == "/api/v1/documents/1/download#page=1"


@pytest.mark.unit
def test_cited_ratio():
    assert cited_ratio("结论一[1]。结论二[2]。") == 1.0
    assert cited_ratio("结论一。结论二[2]。") == 0.5
    assert cited_ratio("") == 0.0
