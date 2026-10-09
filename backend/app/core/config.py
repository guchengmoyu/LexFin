"""
全局配置（pydantic-settings 单例）

所有可变项均来自 .env（见 deploy/.env.example 与 docs/08），
代码中禁止出现裸常量（端口、维度、chunk 参数、模型名、Top-K 等）。
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。字段名与 deploy/.env.example 一一对应（大写环境变量映射小写字段）。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- 0. 通用
    app_env: str = "development"
    app_version: str = "1.0.0"
    app_name: str = "finrag"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:8080,http://localhost:5173"

    secret_key: str = "CHANGE_ME_please_generate_a_random_32_byte_hex_string"
    access_token_expire_minutes: int = 480
    jwt_algorithm: str = "HS256"

    seed_admin_username: str = "admin"
    seed_admin_password: str = "Admin@123"
    seed_admin_real_name: str = "系统管理员"
    editor_invite_code: str = "FINRAG2025"

    # ---------------------------------------------------------------- 1. MySQL
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "finrag"
    mysql_user: str = "finrag"
    mysql_password: str = "finrag_pass_2025"
    mysql_charset: str = "utf8mb4"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # ---------------------------------------------------------------- 2. Milvus
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_collection: str = "finrag_embedding_v1"
    milvus_alias: str = "finrag_embedding"
    milvus_index_type: str = "HNSW"
    milvus_metric_type: str = "COSINE"
    milvus_hnsw_m: int = 16
    milvus_hnsw_ef_construction: int = 200
    milvus_search_ef: int = 64
    milvus_timeout: int = 10

    # ---------------------------------------------------------------- 3. LLM
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = "sk-CHANGE_ME"
    llm_model: str = "deepseek-chat"

    llm_fallback_enabled: bool = True
    llm_fallback_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_fallback_api_key: str = "sk-CHANGE_ME"
    llm_fallback_model: str = "qwen-plus"

    llm_temperature: float = 0.1
    llm_max_tokens: int = 800
    llm_timeout: int = 20
    llm_ttft_timeout: int = 5
    llm_daily_token_budget: int = 2_000_000
    llm_max_concurrency: int = 5

    # ---------------------------------------------------------------- 4. Embedding
    embedding_provider: str = "local"          # local / cloud / fake
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    embedding_dim: int = 1024
    embedding_device: str = "cpu"
    embedding_batch_size: int = 32
    embedding_max_length: int = 512
    embedding_normalize: bool = True
    embedding_cache_dir: str = "/data/models"

    # ---------------------------------------------------------------- 5. Rerank
    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_min_score: float = 0.35
    rerank_top_n: int = 5

    # ---------------------------------------------------------------- 6. 检索
    vector_top_k: int = 20
    keyword_top_k: int = 20
    final_top_n: int = 5
    rrf_k: int = 60
    rrf_w_vector: float = 0.6
    rrf_w_keyword: float = 0.4
    rrf_ref: float = 0.03
    retrieval_min_score: float = 0.30

    timeliness_weight_effective: float = 1.00
    timeliness_weight_amended: float = 0.90
    timeliness_weight_unknown: float = 0.80
    timeliness_weight_repealed: float = 0.50

    # ---------------------------------------------------------------- 7. Prompt/多轮
    prompt_version: str = "v1.2"
    max_context_chars: int = 4000
    multi_turn_enabled: bool = True
    multi_turn_history_size: int = 3
    query_rewrite_timeout_ms: int = 800
    query_vector_cache_size: int = 500

    # ---------------------------------------------------------------- 8. 解析/OCR
    data_dir: str = "/data"
    upload_dir: str = "/data/uploads"
    ocr_cache_dir: str = "/data/ocr_cache"
    max_file_size_mb: int = 50
    allowed_extensions: str = ".pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg,.tiff"

    pdf_text_min_chars: int = 20
    pdf_text_min_chars_per_page: int = 50

    ocr_lang: str = "chi_sim+eng"
    ocr_dpi: int = 300
    ocr_psm: int = 6
    ocr_oem: int = 1
    ocr_max_workers: int = 4
    ocr_min_confidence: int = 60
    ocr_page_timeout: int = 30

    chunk_size: int = 500
    chunk_overlap: int = 80
    chunk_max: int = 800
    chunk_min_merge: int = 120

    # ---------------------------------------------------------------- 9. 限流/安全
    rate_limit_qa_per_minute: int = 20
    rate_limit_upload_per_minute: int = 10
    rate_limit_default_per_minute: int = 120
    password_bcrypt_rounds: int = 12

    # ------------------------------------------------------- 派生属性（只读）
    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_extension_list(self) -> List[str]:
        return [e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()]

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset={self.mysql_charset}"
        )

    @property
    def timeliness_weights(self) -> dict:
        """时效加权表（docs/05 §3.3 / docs/03 §4.4）。"""
        return {
            "effective": self.timeliness_weight_effective,
            "amended": self.timeliness_weight_amended,
            "unknown": self.timeliness_weight_unknown,
            "repealed": self.timeliness_weight_repealed,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。"""
    return Settings()


settings: Settings = get_settings()
