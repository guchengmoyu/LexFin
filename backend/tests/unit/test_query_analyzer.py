"""查询理解单元测试（docs/09 test_query_analyzer）。

覆盖：条号/文号线索抽取、关键词抽取（金融术语 + 数字单位）、
NFKC 全半角归一、need_rewrite 触发条件。
"""
from __future__ import annotations

import pytest

from app.rag.query_rewriter import (
    analyze,
    clean_question,
    extract_clues,
    extract_keywords,
    need_rewrite,
)


@pytest.mark.unit
def test_extract_article_clue():
    article_nos, doc_nos = extract_clues("根据第二十五条和第一百零二条的规定执行")
    assert article_nos == ["第二十五条", "第一百零二条"]
    assert doc_nos == []


@pytest.mark.unit
def test_extract_doc_no_clues():
    _, doc_nos = extract_clues("依据银保监会令2018年第3号及证监发〔2018〕12号执行")
    # DOC_NO_RE 允许文号前带 2~8 个汉字机构名前缀，抽取结果以文号结尾
    assert any(c.endswith("银保监会令2018年第3号") for c in doc_nos)
    assert any(c.endswith("证监发〔2018〕12号") for c in doc_nos)


@pytest.mark.unit
def test_extract_clues_none():
    assert extract_clues("普通问题没有任何线索") == ([], [])


@pytest.mark.unit
def test_keywords_finance_terms_and_number_unit():
    kws = extract_keywords("LCR不得低于100%，反洗钱和债券管理要求")
    assert "LCR" in kws, "金融术语应入选"
    assert "反洗钱" in kws
    assert any(any(ch.isdigit() for ch in k) for k in kws), "数字/单位词应入选"


@pytest.mark.unit
def test_keywords_finance_term_ranked_first():
    kws = extract_keywords("LCR的监管要求")
    assert kws == ["LCR", "监管"], "金融术语（×2.0）应排在普通词之前"


@pytest.mark.unit
def test_keywords_stopwords_filtered():
    kws = extract_keywords("请问如何进行债券的规定要求")
    assert "请问" not in kws and "如何" not in kws and "规定" not in kws
    assert all(len(k) > 1 for k in kws)


@pytest.mark.unit
def test_clean_question_nfkc():
    assert clean_question("　ＬＣＲ１００％　") == "LCR100%"
    assert clean_question("流动性覆盖率１００％") == "流动性覆盖率100%"
    assert clean_question("") == ""


@pytest.mark.unit
def test_need_rewrite_short_with_history():
    assert need_rewrite("这个指标是多少？", has_history=True)


@pytest.mark.unit
def test_need_rewrite_pronoun_with_history():
    long_q = "上述商业银行流动性覆盖率的计算口径与监管标准的具体规定"
    assert len(long_q) >= 25
    assert need_rewrite(long_q, has_history=True), "含指代词即触发"


@pytest.mark.unit
def test_need_rewrite_full_question_no_trigger():
    long_q = "请问商业银行流动性覆盖率计算口径与监管标准具体规定是什么"
    assert len(long_q) >= 25
    assert not need_rewrite(long_q, has_history=True)


@pytest.mark.unit
def test_need_rewrite_without_history():
    assert not need_rewrite("这个指标是多少？", has_history=False)


@pytest.mark.unit
def test_analyze_integration():
    info = analyze("  第二十五条：LCR不得低于100%  ")
    assert info.cleaned == "第二十五条:LCR不得低于100%", "NFKC 将全角冒号归一为半角"
    assert info.article_nos == ["第二十五条"]
    assert info.has_structured_clue
    assert info.keywords
    assert info.effective_query == info.cleaned
    assert info.keyword_query == " ".join(info.keywords)
