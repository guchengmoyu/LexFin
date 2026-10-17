"""可信度评分单元测试（docs/09 §3.3 test_scorer ★）。

覆盖四因子：s1 归一化截断、s2 引用覆盖率、s3 平均分、s4 时效因子，
以及无引用置 0 与分级边界（0.60 / 0.80 闭区间）。
"""
from __future__ import annotations

import pytest

from app.rag.scorer import level, level_label, score

ANSWER_ALL_CITED = "该指标不得低于100%[1]。资本充足率不得低于11.5%[2]。"


@pytest.mark.unit
def test_high_confidence(make_citation):
    citations = [make_citation(cite_index=1), make_citation(cite_index=2, timeliness="effective")]
    conf = score(ANSWER_ALL_CITED, citations, [0.05, 0.04], citations)

    assert conf >= 0.8
    assert level(conf) == "high"


@pytest.mark.unit
def test_no_citation_zero(make_citation):
    conf = score("没有任何来源标注的答案。", [], [0.05, 0.04])
    assert conf == 0.0
    assert level(conf) == "low"

    # used_citations 为空同样置 0
    conf2 = score("没有角标。", [make_citation()], [0.05], [])
    assert conf2 == 0.0


@pytest.mark.unit
def test_all_repealed_lowers_score(make_citation):
    eff = [make_citation(cite_index=1), make_citation(cite_index=2)]
    rep = [
        make_citation(cite_index=1, timeliness="repealed"),
        make_citation(cite_index=2, timeliness="repealed"),
    ]
    conf_eff = score(ANSWER_ALL_CITED, eff, [0.05, 0.04], eff)
    conf_rep = score(ANSWER_ALL_CITED, rep, [0.05, 0.04], rep)

    assert conf_rep < conf_eff, "全 repealed 时 s4=0，总分降低"
    assert conf_eff - conf_rep == pytest.approx(0.15, abs=1e-3), "降幅约 0.15"


@pytest.mark.unit
def test_level_boundaries():
    assert level(0.60) == "medium", "0.60 为 medium 闭区间下界"
    assert level(0.599) == "low"
    assert level(0.799) == "medium"
    assert level(0.80) == "high"
    assert level_label("high") == "可信度高"


@pytest.mark.unit
def test_s1_clamped_to_one(make_citation):
    """检索分过高时归一化截断 1.0，总分不超过 1。"""
    citations = [make_citation(cite_index=1), make_citation(cite_index=2)]
    conf = score(ANSWER_ALL_CITED, citations, [5.0, 3.0], citations)

    assert 0.0 < conf <= 1.0
    assert conf == 1.0, "高检索分 + 全引用 + 全 effective = 满分 1.0"


@pytest.mark.unit
def test_cited_ratio_affects_s2(make_citation):
    citations = [make_citation(cite_index=1)]
    full = score("结论一[1]。", citations, [0.03], citations)
    none = score("结论一。", citations, [0.03], citations)
    assert full > none, "无角标句子拉低 s2 与总分"
