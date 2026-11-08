"""Prompt 模板与组装（docs/05 §6，版本 v1.2）。

变更必须同步更新 docs/05 §6 版本号与 qa_message.prompt_version，
并在评测集上回归（准确率不得下降，docs/00 §6 变更管理约定）。
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from app.core.config import settings
from app.core.constants import TIMELINESS_LABELS, ErrorCode
from app.core.exceptions import BizError
from app.rag.types import RetrievedItem

PROMPT_VERSION = "v1.2"

# --------------------------------------------------------------------------- #
#  6.1 系统提示（System）
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """你是金融制度领域的专业问答助手，服务于银行、证券、保险行业的合规与业务人员。
你的回答必须严格基于下面给出的【参考条文】，不得使用参考条文之外的任何知识。

【回答规则】
1. 只依据【参考条文】作答，禁止凭常识、经验或训练记忆推测和编造。
2. 每一句结论后面必须标注来源编号，格式为 [1]、[2]；多个来源写作 [1][3]。
3. 若【参考条文】不足以回答问题，必须直接回答："根据现有知识库，暂未检索到相关规定"，
   并说明缺少哪方面的信息；严禁给出没有来源标注的答案。
4. 引用数值、比例、金额、期限、日期时必须与原文完全一致，不得改写、换算或四舍五入。
5. 若引用的制度标注为「已废止」或「已修订」，必须明确指出，并优先采用标注为「现行有效」的条文。
6. 回答结构：先给结论，再给依据与适用条件。用语规范、简洁，不寒暄、不复述本规则。
7. 若多条【参考条文】之间存在冲突，需指出冲突并说明各自的适用范围与时效。"""

USER_HEADER = "【参考条文】"
USER_QUESTION = "【用户问题】"
USER_REQUIREMENT = (
    "【回答要求】\n请基于上述参考条文回答问题，并在结论后标注来源编号。若参考条文不足，请直接说明。"
)

# 上下文预算（docs/05 §6.4）
MAX_CONTEXT_CHARS_DEFAULT = 4000
TOP1_TRUNCATE_CHARS = 1500


def format_entry(index: int, item: RetrievedItem) -> str:
    """单条参考条文：每条附完整出处头（标题/文号/条号/页码/时效）。"""
    timeliness_label = TIMELINESS_LABELS.get(item.timeliness or "unknown", "时效未知")
    doc_title = item.doc_title or item.title or "未知文档"
    head_parts = [f"《{doc_title}》"]
    detail = [item.doc_no or "", timeliness_label]
    head_parts.append("（" + "，".join(d for d in detail if d) + "）")
    struct = " ".join(x for x in (item.chapter_no, item.article_no) if x)
    page = f"  第{item.page_no}页" if item.page_no else ""
    head = f"[{index}] " + "".join(head_parts) + f" {struct}{page}".rstrip()
    body = (item.raw_content or item.content or "").strip()
    return f"{head}\n{body}"


def trim_context(
    items: Sequence[RetrievedItem],
    max_chars: Optional[int] = None,
) -> List[RetrievedItem]:
    """上下文裁剪（docs/05 §6.4）：
    1. 按融合分降序累加长度；
    2. 超预算停止加入（调用方重新编号保持连续）；
    3. Top-1 单独超预算 → 1500 字截断并保留条号前缀；
    4. 保证至少 2 条证据进入上下文（除非只有 1 条通过阈值）。
    """
    budget = max_chars or settings.max_context_chars
    ordered = sorted(items, key=lambda x: -x.score) if items else []
    if not ordered:
        return []

    selected: List[RetrievedItem] = []
    used = 0
    for idx, item in enumerate(ordered):
        text = item.raw_content or item.content or ""
        if idx == 0 and len(text) > budget:
            truncated = text[:TOP1_TRUNCATE_CHARS]
            if item.article_no and not truncated.startswith(item.article_no):
                truncated = f"{item.article_no} {truncated}"
            item.raw_content = truncated
            selected.append(item)
            used += len(truncated)
            continue
        if used + len(text) > budget and selected:
            break
        selected.append(item)
        used += len(text)

    # 保证至少 2 条（若存在）
    if len(selected) < 2 and len(ordered) > len(selected):
        for item in ordered[len(selected):]:
            selected.append(item)
            if len(selected) >= 2:
                break
    return selected


def build_user_prompt(
    question: str,
    items: Sequence[RetrievedItem],
    max_chars: Optional[int] = None,
) -> str:
    """组装用户提示：编号上下文 + 用户问题 + 回答要求。

    空证据抛业务异常，由上层触发拒答（docs/05 §5）。
    """
    if not items:
        raise BizError(ErrorCode.INTERNAL_ERROR, "参考条文为空，无法组装 Prompt")

    selected = trim_context(items, max_chars)
    entries = [format_entry(i, item) for i, item in enumerate(selected, start=1)]
    context_block = USER_HEADER + "\n" + "\n\n".join(entries)
    return f"{context_block}\n\n{USER_QUESTION}\n{question.strip()}\n\n{USER_REQUIREMENT}"


def build_messages(
    question: str,
    items: Sequence[RetrievedItem],
    max_chars: Optional[int] = None,
) -> list[dict]:
    """构造 ChatOpenAI 消息列表（system + user）。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question, items, max_chars)},
    ]


# --------------------------------------------------------------------------- #
#  标准拒答话术（docs/05 §5）
# --------------------------------------------------------------------------- #
REFUSAL_TEMPLATE = """根据现有知识库，暂未检索到与「{question}」直接相关的制度规定。

建议您可以：
1. 换用制度原文中的表述重新提问，例如「{suggested_query}」；
2. 在「关键词检索」中直接搜索：{top_keywords}；
3. 确认该问题是否属于当前知识库范围（银行监管 / 证券行业 / 保险制度）。"""


def build_refusal_answer(
    question: str,
    suggested_query: str = "",
    top_keywords: Sequence[str] = (),
) -> str:
    return REFUSAL_TEMPLATE.format(
        question=question.strip(),
        suggested_query=suggested_query or question.strip(),
        top_keywords="、".join(top_keywords) or "相关制度名称、条号或专业术语",
    )
