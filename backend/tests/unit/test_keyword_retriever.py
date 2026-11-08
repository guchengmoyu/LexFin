from types import SimpleNamespace

from app.rag.retriever.keyword_retriever import _core_query_terms, _has_core_term


def test_core_query_terms_drop_overlapping_search_tokens():
    assert _core_query_terms(["证券公司", "公司", "证券", "风险", "控制", "指标"]) == [
        "证券公司"
    ]


def test_keyword_candidate_requires_a_substantive_query_term():
    terms = _core_query_terms(["证券公司", "公司", "证券", "风险", "控制", "指标"])
    bank_result = SimpleNamespace(
        title="资产风险分类",
        raw_content="商业银行流动性监管指标及风险控制要求",
        content="",
        doc_title="商业银行流动性风险管理办法",
    )
    securities_result = SimpleNamespace(
        title="证券公司风控指标",
        raw_content="证券公司应持续符合风险控制指标要求",
        content="",
        doc_title="证券公司风险控制指标管理办法",
    )

    assert not _has_core_term(bank_result, terms)
    assert _has_core_term(securities_result, terms)


def test_liquidity_query_keeps_relevant_content():
    terms = _core_query_terms(["流动性", "流动", "风险"])
    result = SimpleNamespace(
        title="什么是流动性风险？",
        raw_content="银行无法及时以合理成本获得资金的风险。",
        content="",
        doc_title="商业银行流动性风险管理办法",
    )

    assert terms == ["流动性"]
    assert _has_core_term(result, terms)
