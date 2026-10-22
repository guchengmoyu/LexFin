"""启动钩子：创建/校正种子管理员、内置知识库、system_config 默认项。

设计约定（docs/03 §7）：管理员密码不在 SQL 中硬编码哈希，由本模块依据 .env 创建。
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import BUILTIN_KBS, Role
from app.core.security import hash_password
from app.models.knowledge_base import KnowledgeBase
from app.models.system_config import SystemConfig
from app.models.user import User

#: system_config 默认项（与 deploy/mysql/init/01-schema.sql 保持一致）
SYSTEM_CONFIG_DEFAULTS = [
    ("retrieval.default_mode", "hybrid", "默认检索模式：keyword/vector/hybrid"),
    ("retrieval.vector_top_k", "20", "向量召回条数"),
    ("retrieval.keyword_top_k", "20", "关键词召回条数"),
    ("retrieval.final_top_n", "5", "最终进入 Prompt 的证据条数"),
    ("retrieval.rrf_k", "60", "RRF 平滑常数"),
    ("retrieval.rrf_w_vector", "0.6", "向量通道权重"),
    ("retrieval.rrf_w_keyword", "0.4", "关键词通道权重"),
    ("retrieval.min_score", "0.30", "低于该融合分直接拒答"),
    ("rerank.enabled", "false", "是否启用重排模型（二期）"),
    ("prompt.version", "v1.2", "当前生效的 Prompt 版本号"),
    ("qa.multi_turn_enabled", "true", "是否启用多轮指代改写"),
    ("qa.max_context_chars", "4000", "拼入 Prompt 的上下文长度上限"),
    ("qa.confidence_high", "0.80", "可信度高的下限"),
    ("qa.confidence_medium", "0.60", "可信度中的下限"),
    ("llm.daily_token_budget", "2000000", "当日 token 预算"),
]


def seed_all(db: Session) -> None:
    """幂等执行：可重复调用。"""
    _seed_admin(db)
    _seed_kbs(db)
    _seed_system_config(db)
    db.commit()


def _seed_admin(db: Session) -> None:
    user = db.scalar(select(User).where(User.username == settings.seed_admin_username))
    if user is None:
        user = User(
            username=settings.seed_admin_username,
            password_hash=hash_password(settings.seed_admin_password),
            real_name=settings.seed_admin_real_name,
            role=Role.admin.value,
            status=1,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(user)
        logger.info("已创建种子管理员 {}", settings.seed_admin_username)
    else:
        # 校正：确保管理员角色与状态正确；密码不强制重置（避免覆盖用户改过的密码）
        changed = False
        if user.role != Role.admin.value:
            user.role = Role.admin.value
            changed = True
        if user.status != 1:
            user.status = 1
            changed = True
        if changed:
            logger.info("已校正管理员 {} 的角色/状态", settings.seed_admin_username)


def _seed_kbs(db: Session) -> None:
    for kb_def in BUILTIN_KBS:
        kb = db.scalar(select(KnowledgeBase).where(KnowledgeBase.code == kb_def["code"]))
        if kb is None:
            db.add(
                KnowledgeBase(
                    code=kb_def["code"],
                    name=kb_def["name"],
                    category=kb_def["category"],
                    description=kb_def["description"],
                    status=1,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
            )
            logger.info("已创建内置知识库 {}", kb_def["name"])


def _seed_system_config(db: Session) -> None:
    for key, value, desc in SYSTEM_CONFIG_DEFAULTS:
        exists = db.scalar(select(SystemConfig).where(SystemConfig.config_key == key))
        if exists is None:
            db.add(
                SystemConfig(
                    config_key=key,
                    config_value=value,
                    description=desc,
                    updated_at=datetime.now(),
                )
            )
