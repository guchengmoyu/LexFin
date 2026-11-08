"""RRF 融合与去重单元测试（docs/09 §3.3 test_rrf ★）。

覆盖 rrf_fuse 纯函数：加权 RRF 公式（docs/05 §3.3）、双通道累加、
时效加权、知识点加权、结构化线索加成、空输入、同分稳定排序；
以及 dedup_items 三条去重规则（docs/05 §3.4）。
"""
from __future__ import annotations

import pytest

from app.rag.retriever.hybrid_retriever import (
    CLUE_BOOST,
    KP_BOOST,
    MAX_SAME_ARTICLE,
    SIMILARITY_THRESHOLD,
    dedup_items,
    rrf_fuse,
)

# 显式权重（docs/05 §3.3）：与 settings 默认值一致，测试中显式传入保证确定性
K = 60
W_VECTOR = 0.6
W_KEYWORD = 0.4
TW = {"effective": 1.0, "amended": 0.9, "unknown": 0.8, "repealed": 0.5}


# --------------------------------------------------------------------------- #
#  rrf_fuse
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_vector_only_fusion_score(make_item):
    """仅向量通道：score = w_vector/(K+rank) × 时效权重。"""
    items = [
        make_item(source_type="chunk", source_id=1, timeliness="effective"),
        make_item(source_type="chunk", source_id=2, timeliness="effective"),
    ]
    fused = rrf_fuse(
        items, [], rrf_k=K, w_vector=W_VECTOR, w_keyword=W_KEYWORD,
        timeliness_weights=TW,
    )

    assert len(fused) == 2
    by_id = {i.source_id: i.score for i in fused}
    assert by_id[1] == pytest.approx(W_VECTOR / (K + 1))
    assert by_id[2] == pytest.approx(W_VECTOR / (K + 2))


@pytest.mark.unit
def test_fusion_score_multiplies_timeliness_weight(make_item):
    items = [make_item(source_id=1, timeliness="unknown")]
    fused = rrf_fuse(
        items, [], rrf_k=K, w_vector=W_VECTOR, w_keyword=W_KEYWORD,
        timeliness_weights=TW,
    )
    assert fused[0].score == pytest.approx(W_VECTOR / (K + 1) * TW["unknown"])


@pytest.mark.unit
def test_two_channels_scores_accumulate_once(make_item):
    """同一实体两通道同时命中：分数累加，且只出现一次。"""
    vec = [make_item(source_type="chunk", source_id=7, timeliness="effective")]
    kw = [make_item(source_type="chunk", source_id=7, timeliness="effective")]
    fused = rrf_fuse(
        vec, kw, rrf_k=K, w_vector=W_VECTOR, w_keyword=W_KEYWORD,
        timeliness_weights=TW,
    )

    assert len(fused) == 1
    assert fused[0].score == pytest.approx(
        W_VECTOR / (K + 1) + W_KEYWORD / (K + 1)
    )


@pytest.mark.unit
def test_repealed_weight_is_half_of_effective(make_item):
    """repealed 时效权重为 effective 的一半（显式传入 timeliness_weights）。"""
    tw = {"effective": 1.0, "repealed": 0.5}
    eff = make_item(source_type="chunk", source_id=1, timeliness="effective")
    rep = make_item(source_type="chunk", source_id=2, timeliness="repealed")
    fused = rrf_fuse(
        [eff], [rep], rrf_k=K, w_vector=1.0, w_keyword=1.0, timeliness_weights=tw,
    )
    by_id = {i.source_id: i.score for i in fused}

    assert by_id[2] == pytest.approx(by_id[1] / 2)


@pytest.mark.unit
def test_knowledge_point_boost(make_item):
    """knowledge_point 类型分数 ×1.15。"""
    chunk = make_item(source_type="chunk", source_id=1, timeliness="effective")
    kp = make_item(source_type="knowledge_point", source_id=2, timeliness="effective")
    fused = rrf_fuse(
        [chunk], [kp], rrf_k=K, w_vector=1.0, w_keyword=1.0, timeliness_weights=TW,
    )
    by_key = {i.key: i.score for i in fused}

    assert by_key["knowledge_point_2"] == pytest.approx(
        by_key["chunk_1"] * KP_BOOST
    )
    assert KP_BOOST == 1.15


@pytest.mark.unit
def test_article_no_clue_boost(make_item):
    """条号精确命中 query_article_nos 时 ×1.5。"""
    item = make_item(source_type="chunk", source_id=1, article_no="第二十五条")
    plain = rrf_fuse(
        [item], [], rrf_k=K, w_vector=1.0, w_keyword=1.0, timeliness_weights=TW,
    )[0]
    boosted = rrf_fuse(
        [make_item(source_type="chunk", source_id=1, article_no="第二十五条")],
        [], rrf_k=K, w_vector=1.0, w_keyword=1.0, timeliness_weights=TW,
        query_article_nos=["第二十五条"],
    )[0]

    assert CLUE_BOOST == 1.5
    assert boosted.score == pytest.approx(plain.score * CLUE_BOOST)


@pytest.mark.unit
def test_doc_no_clue_boost(make_item):
    item_kw = dict(source_type="chunk", source_id=1, doc_no="银保监会令2018年第3号")
    plain = rrf_fuse(
        [make_item(**item_kw)], [], rrf_k=K, w_vector=1.0, w_keyword=1.0,
        timeliness_weights=TW,
    )[0]
    boosted = rrf_fuse(
        [make_item(**item_kw)], [], rrf_k=K, w_vector=1.0, w_keyword=1.0,
        timeliness_weights=TW, query_doc_nos=["银保监会令2018年第3号"],
    )[0]

    assert boosted.score == pytest.approx(plain.score * CLUE_BOOST)


@pytest.mark.unit
def test_empty_inputs_return_empty():
    assert rrf_fuse([], []) == []


@pytest.mark.unit
def test_stable_sort_by_source_type_and_id(make_item):
    """同分时按 (source_type, source_id) 稳定排序。"""
    # 同分不同 source_id → 按 source_id 升序
    fused = rrf_fuse(
        [make_item(source_type="chunk", source_id=5)],
        [make_item(source_type="chunk", source_id=3)],
        rrf_k=K, w_vector=1.0, w_keyword=1.0, timeliness_weights=TW,
    )
    assert [i.source_id for i in fused] == [3, 5]

    # 同分不同 source_type → chunk 先于 knowledge_point
    fused = rrf_fuse(
        [make_item(source_type="chunk", source_id=5)],
        [make_item(source_type="knowledge_point", source_id=1)],
        rrf_k=K, w_vector=1.15, w_keyword=1.0, timeliness_weights=TW,
    )
    assert [i.source_type for i in fused] == ["chunk", "knowledge_point"]


# --------------------------------------------------------------------------- #
#  dedup_items
# --------------------------------------------------------------------------- #
def _distinct_content(i: int, n: int = 60) -> str:
    """互不重叠的字符序列，保证 3-gram 相似度为 0（不触碰相似度规则）。"""
    return "".join(chr(0x4E00 + i * 200 + k) for k in range(n))


@pytest.mark.unit
def test_dedup_knowledge_point_wins_over_primary_chunk(make_item):
    kp = make_item(source_type="knowledge_point", source_id=7, score=0.9,
                   raw_content=_distinct_content(1))
    primary = make_item(source_type="chunk", source_id=42, score=0.8,
                        raw_content=_distinct_content(2))
    other = make_item(source_type="chunk", source_id=99, score=0.7,
                      raw_content=_distinct_content(3))

    out = dedup_items([kp, primary, other], kp_primary_chunk_ids={7: 42})
    assert [(i.source_type, i.source_id) for i in out] == [
        ("knowledge_point", 7),
        ("chunk", 99),
    ]


@pytest.mark.unit
def test_dedup_same_document_article_max_two(make_item):
    """同 document + article 的滑窗块最多保留 MAX_SAME_ARTICLE=2 个。"""
    items = [
        make_item(source_type="chunk", source_id=i, document_id=3,
                  article_no="第二十条", chunk_index=i - 1, score=1.0 - i * 0.01,
                  raw_content=_distinct_content(i))
        for i in (1, 2, 3)
    ]
    out = dedup_items(items)

    assert MAX_SAME_ARTICLE == 2
    assert len(out) == 2
    assert [i.chunk_index for i in out] == [0, 1]


@pytest.mark.unit
def test_dedup_different_articles_not_limited(make_item):
    items = [
        make_item(source_type="chunk", source_id=i, document_id=3,
                  article_no=f"第{i}条", chunk_index=i, score=1.0 - i * 0.01,
                  raw_content=_distinct_content(i))
        for i in (1, 2, 3)
    ]
    assert len(dedup_items(items)) == 3


@pytest.mark.unit
def test_dedup_similarity_above_threshold(make_item):
    """内容相似度 > 0.95 → 保留先出现（高分）者。"""
    assert SIMILARITY_THRESHOLD == 0.95
    base = _distinct_content(1, 200)                      # 200 个互不相同字符
    near_dup = base[:100] + chr(0x6000) + base[101:]      # 仅 1 字不同 → 相似度 ≈ 0.97
    a = make_item(source_type="chunk", source_id=1, article_no=None,
                  raw_content=base, score=0.9)
    b = make_item(source_type="chunk", source_id=2, article_no=None,
                  raw_content=near_dup, score=0.8)

    out = dedup_items([a, b])
    assert [i.source_id for i in out] == [1]


@pytest.mark.unit
def test_dedup_dissimilar_content_kept(make_item):
    a = make_item(source_type="chunk", source_id=1, article_no=None,
                  raw_content=_distinct_content(1, 120))
    b = make_item(source_type="chunk", source_id=2, article_no=None,
                  raw_content=_distinct_content(2, 120))
    assert len(dedup_items([a, b])) == 2


@pytest.mark.unit
def test_dedup_empty_input():
    assert dedup_items([]) == []
