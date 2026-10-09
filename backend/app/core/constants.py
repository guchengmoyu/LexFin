"""
枚举与常量（docs/00 术语表、docs/03 §2、docs/06 §3 错误码、docs/03 §4.2 子类字典）

业务子类字典一期硬编码于此（docs/03 §4.2），前端下拉框由 /system/config 接口返回。
"""
from __future__ import annotations

from enum import Enum


# --------------------------------------------------------------------------- #
#  枚举
# --------------------------------------------------------------------------- #
class Role(str, Enum):
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class DocStatus(str, Enum):
    pending = "pending"
    parsing = "parsing"
    embedding = "embedding"
    ready = "ready"
    error = "error"
    archived = "archived"


class DocType(str, Enum):
    law = "law"
    regulation = "regulation"
    rule = "rule"
    notice = "notice"
    guideline = "guideline"
    other = "other"


class Timeliness(str, Enum):
    effective = "effective"
    amended = "amended"
    repealed = "repealed"
    unknown = "unknown"


TIMELINESS_LABELS = {
    "effective": "现行有效",
    "amended": "已修订",
    "repealed": "已废止",
    "unknown": "时效未知",
}


class VerifyStatus(str, Enum):
    pending = "pending"
    passed = "passed"
    doubted = "doubted"
    rejected = "rejected"


class KpStatus(str, Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class KpSourceType(str, Enum):
    manual = "manual"
    auto_extract = "auto_extract"
    import_ = "import"


class AnswerType(str, Enum):
    answered = "answered"
    refused = "refused"
    error = "error"
    clarify = "clarify"


class RetrievalMode(str, Enum):
    keyword = "keyword"
    vector = "vector"
    hybrid = "hybrid"


class TaskStatus(str, Enum):
    queued = "queued"
    parsing = "parsing"
    cleaning = "cleaning"
    chunking = "chunking"
    embedding = "embedding"
    indexing = "indexing"
    success = "success"
    failed = "failed"


class TaskType(str, Enum):
    ingest = "ingest"
    reparse = "reparse"
    reembed = "reembed"


class ChunkSourceType(str, Enum):
    text = "text"
    table = "table"
    ocr = "ocr"


class RelationType(str, Enum):
    same_topic = "same_topic"
    context = "context"
    supersede = "supersede"
    supplement = "supplement"
    conflict = "conflict"


class FeedbackReason(str, Enum):
    inaccurate = "inaccurate"
    incomplete = "incomplete"
    outdated = "outdated"
    wrong_citation = "wrong_citation"
    other = "other"


class ReviewErrorType(str, Enum):
    retrieval_miss = "retrieval_miss"
    hallucination = "hallucination"
    citation_wrong = "citation_wrong"
    outdated = "outdated"
    incomplete = "incomplete"


class ReviewTargetType(str, Enum):
    answer = "answer"
    knowledge_point = "knowledge_point"


class VectorSourceType(str, Enum):
    chunk = "chunk"
    knowledge_point = "knowledge_point"


# --------------------------------------------------------------------------- #
#  错误码（docs/06 §3，代码与文档一致，禁止新增不登记的错误码）
# --------------------------------------------------------------------------- #
class ErrorCode:
    OK = 0
    PARAM_INVALID = 40001
    PARAM_MISSING = 40002
    PARAM_FORMAT = 40003
    FILE_TYPE_NOT_ALLOWED = 40010
    FILE_TOO_LARGE = 40011
    FILE_EMPTY = 40012
    QUESTION_EMPTY = 40020
    QUESTION_TOO_LONG = 40021
    PAGE_OUT_OF_RANGE = 40030
    UNAUTHORIZED = 40100
    TOKEN_EXPIRED = 40101
    TOKEN_INVALID = 40102
    LOGIN_FAILED = 40103
    FORBIDDEN = 40300
    USER_DISABLED = 40301
    NOT_FOUND = 40400
    DOCUMENT_NOT_FOUND = 40401
    KNOWLEDGE_POINT_NOT_FOUND = 40402
    SESSION_NOT_FOUND = 40403
    CONFLICT = 40900
    DOCUMENT_DUPLICATE = 40901
    TASK_RUNNING = 40902
    KP_CODE_EXISTS = 40903
    TOO_MANY_REQUESTS = 42900
    INTERNAL_ERROR = 50000
    DB_ERROR = 50010
    VECTOR_ERROR = 50020
    LLM_ERROR = 50030
    OCR_UNAVAILABLE = 50040
    PARSE_FAILED = 50050


#: 错误码 → HTTP 状态码（docs/06 §3）
ERROR_HTTP_STATUS = {
    ErrorCode.OK: 200,
    ErrorCode.PARAM_INVALID: 400,
    ErrorCode.PARAM_MISSING: 400,
    ErrorCode.PARAM_FORMAT: 400,
    ErrorCode.FILE_TYPE_NOT_ALLOWED: 400,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.FILE_EMPTY: 400,
    ErrorCode.QUESTION_EMPTY: 400,
    ErrorCode.QUESTION_TOO_LONG: 400,
    ErrorCode.PAGE_OUT_OF_RANGE: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.TOKEN_INVALID: 401,
    ErrorCode.LOGIN_FAILED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.USER_DISABLED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.DOCUMENT_NOT_FOUND: 404,
    ErrorCode.KNOWLEDGE_POINT_NOT_FOUND: 404,
    ErrorCode.SESSION_NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.DOCUMENT_DUPLICATE: 409,
    ErrorCode.TASK_RUNNING: 409,
    ErrorCode.KP_CODE_EXISTS: 409,
    ErrorCode.TOO_MANY_REQUESTS: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.DB_ERROR: 500,
    ErrorCode.VECTOR_ERROR: 500,
    ErrorCode.LLM_ERROR: 502,
    ErrorCode.OCR_UNAVAILABLE: 503,
    ErrorCode.PARSE_FAILED: 500,
}


# --------------------------------------------------------------------------- #
#  字典（docs/03 §4.2 / docs/06 §5.2 /system/config）
# --------------------------------------------------------------------------- #
CATEGORY_SUB: dict[str, list[str]] = {
    "banking": [
        "资本管理", "流动性风险", "信用风险", "市场风险", "操作风险", "公司治理",
        "信息披露", "支付结算", "反洗钱", "消费者权益保护", "账户管理", "信贷业务",
    ],
    "securities": [
        "发行上市", "信息披露", "交易规则", "投资者适当性", "证券公司治理",
        "资产管理", "债券业务", "融资融券", "投资顾问", "基金销售",
    ],
    "insurance": [
        "产品条款", "销售规范", "偿付能力", "资金运用", "理赔服务",
        "保险公司治理", "再保险", "保险中介",
    ],
}

CATEGORY_LABELS = {
    "banking": "银行监管",
    "securities": "证券行业",
    "insurance": "保险制度",
}

#: 三个内置知识库（docs/03 §4.1）
BUILTIN_KBS = [
    {"code": "banking", "name": "银行监管制度库", "category": "banking",
     "description": "中国人民银行、原银保监会、国家金融监督管理总局等发布的银行监管政策与规范性文件"},
    {"code": "securities", "name": "证券行业规范库", "category": "securities",
     "description": "中国证监会、证券交易所、证券业协会发布的证券业务规范、自律规则与信息披露要求"},
    {"code": "insurance", "name": "保险制度库", "category": "insurance",
     "description": "国家金融监督管理总局、保险行业协会发布的保险产品、销售、偿付能力与资金运用制度"},
]

DOC_TYPE_LABELS = {
    "law": "法律",
    "regulation": "行政法规/办法",
    "rule": "部门规章/细则",
    "notice": "通知/公告",
    "guideline": "自律规范/指引",
    "other": "其他",
}

RETRIEVAL_MODE_LABELS = {
    "hybrid": "智能检索",
    "keyword": "关键词",
    "vector": "语义",
}

#: 知识点编号前缀（docs/03 §2.5：KP-{CAT}-{4位序号}）
KP_CODE_PREFIX = {
    "banking": "KP-BANK",
    "securities": "KP-SEC",
    "insurance": "KP-INS",
}

#: 答案可信度分级阈值（docs/05 §9）
CONFIDENCE_HIGH = 0.80
CONFIDENCE_MEDIUM = 0.60

#: 问答限流等
QUESTION_MAX_LEN = 500
PROMPT_VERSION_DEFAULT = "v1.2"
