"""关键词通道的「口语 → 术语」归一（docs/05 §2.4）。

问题：MySQL ngram FULLTEXT 是 OR 语义，口语里的通用词（本钱、倒闭、骗保）在
制度原文里几乎不出现，IDF 很高，会直接压过真正的领域词，召回结果跑偏。
做法：把口语词替换成制度里的标准说法，并补上该概念的同义术语（追加是 OR，
只提高召回，不改变原词权重），最终由 rerank / RRF 决定顺序。

只作用于关键词通道（`search_keyword` 的 q），不动向量通道的原文，避免影响
BGE 的语义表达。开关：settings.synonym_enabled。
"""
from __future__ import annotations

from typing import Dict, Tuple

#: 口语说法 → 制度原文里的标准说法（替换，去掉高 IDF 干扰词）
REPLACEMENTS: Dict[str, str] = {
    "本钱": "资本",
    "本金比例": "资本充足率",
    "留多少钱": "最低要求",
    "最少要留": "最低要求",
    "开公司": "设立公司",
    "办公司": "设立公司",
    "卖保险": "销售保险产品",
    "卖产品": "销售产品",
    "赔钱": "赔偿",
    "倒闭": "破产接管清算",
    "骗保": "保险欺诈骗取保险金",
    "罚钱": "罚款处罚",
    "扣钱": "扣划资金",
    "借钱": "贷款借款",
    "押金": "保证金",
    "老板": "董事高级管理人员",
    "员工": "从业人员",
    "跑路": "失联逃逸",
    "黑名单": "名单",
    "关停": "停业关闭",
    "审批": "批准核准",
    "报备": "备案",
    "坏账": "不良贷款",
}

#: 概念扩展：出现左侧词时，把右侧制度术语追加进检索式（OR 召回）
CONCEPTS: Dict[str, Tuple[str, ...]] = {
    "营业执照": ("无照经营", "未经批准", "擅自设立"),
    "无证": ("未取得许可证", "未经许可"),
    "资本": ("资本充足率", "核心一级资本", "风险加权资产"),
    "留多少钱": ("资本充足率", "最低要求"),
    "流动性": ("流动性覆盖率", "流动性风险", "期限错配"),
    "偿付能力": ("偿付能力充足率", "实际资本", "最低资本"),
    "准备金": ("存款准备金", "贷款损失准备"),
    "杠杆": ("杠杆率", "表内外资产"),
    "关联交易": ("关联方", "关联交易"),
    "信息披露": ("披露", "报告", "报送"),
    "洗钱": ("反洗钱", "客户身份识别", "可疑交易"),
    "理财产品": ("理财业务", "销售管理", "投资者适当性"),
    "代销": ("代理销售", "代销业务"),
    "托管": ("托管业务", "资产托管"),
    "违约": ("违约", "信用风险", "逾期"),
    "罚款": ("行政处罚", "罚款", "责令改正"),
    "吊销": ("吊销许可证", "撤销", "责令停业"),
    "保险金": ("保险金给付", "赔偿", "给付"),
    "骗保": ("保险欺诈", "骗取保险金"),
    "存款": ("存款业务", "储蓄存款"),
    "贷款": ("贷款业务", "授信", "信贷"),
    "股东": ("股东", "主要股东", "股权管理"),
    "董监高": ("董事", "监事", "高级管理人员"),
    "消费者": ("金融消费者", "投资者", "客户"),
    "个人信息": ("个人信息保护", "客户信息"),
    "系统": ("信息系统", "信息科技风险"),
    "外包": ("外包", "第三方合作"),
    "评级": ("信用评级", "风险分类"),
}

MAX_ADDED_TERMS = 8


def apply_synonyms(text: str, append: bool = True) -> str:
    """把口语问题/关键词串归一为制度术语，返回新的检索式。

    append=False 时只做替换（不追加同义术语），用于 A/B 验证追加是否带来噪声。
    """
    if not text:
        return text
    normalized = text
    for colloquial, standard in REPLACEMENTS.items():
        if colloquial in normalized:
            normalized = normalized.replace(colloquial, standard)
    if not append:
        return normalized

    added: list[str] = []
    source = f"{text} {normalized}"
    for phrase, terms in CONCEPTS.items():
        if phrase not in source:
            continue
        for term in terms:
            if term not in normalized and term not in added:
                added.append(term)
    if not added:
        return normalized
    return f"{normalized} {' '.join(added[:MAX_ADDED_TERMS])}"
