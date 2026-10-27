-- =============================================================================
--  基于 RAG 的金融制度类知识问答系统 · MySQL 初始化脚本
--  对应设计文档：docs/03-数据模型与知识库设计.md
--  字符集：utf8mb4 / utf8mb4_unicode_ci
--  说明：本脚本由 MySQL 容器首次启动时自动执行（docker-entrypoint-initdb.d）
--        脚本内所有语句必须幂等，可安全重复执行。
-- =============================================================================

SET NAMES utf8mb4;
SET time_zone = '+08:00';

CREATE DATABASE IF NOT EXISTS `finrag`
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `finrag`;

-- -----------------------------------------------------------------------------
-- 1. user · 用户
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user` (
    `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `username`       VARCHAR(50)     NOT NULL                COMMENT '登录名',
    `password_hash`  VARCHAR(100)    NOT NULL                COMMENT 'bcrypt cost=12',
    `real_name`      VARCHAR(50)     DEFAULT NULL            COMMENT '姓名',
    `email`          VARCHAR(100)    DEFAULT NULL,
    `role`           VARCHAR(20)     NOT NULL DEFAULT 'viewer' COMMENT 'admin/editor/viewer',
    `status`         TINYINT         NOT NULL DEFAULT 1      COMMENT '1启用 0禁用',
    `last_login_at`  DATETIME        DEFAULT NULL,
    `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_username` (`username`),
    KEY `idx_role` (`role`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '用户表';

-- -----------------------------------------------------------------------------
-- 2. knowledge_base · 知识库
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `knowledge_base` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `code`        VARCHAR(32)     NOT NULL              COMMENT 'banking/securities/insurance',
    `name`        VARCHAR(100)    NOT NULL,
    `category`    VARCHAR(32)     NOT NULL              COMMENT '与 code 一致，便于检索过滤',
    `description` VARCHAR(500)    DEFAULT NULL,
    `doc_count`   INT             NOT NULL DEFAULT 0,
    `chunk_count` INT             NOT NULL DEFAULT 0,
    `kp_count`    INT             NOT NULL DEFAULT 0    COMMENT '知识点数量，验收指标载体',
    `status`      TINYINT         NOT NULL DEFAULT 1    COMMENT '1启用 0停用',
    `created_by`  BIGINT UNSIGNED DEFAULT NULL,
    `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_code` (`code`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '知识库表';

-- -----------------------------------------------------------------------------
-- 3. document · 制度文档
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `document` (
    `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `kb_id`              BIGINT UNSIGNED NOT NULL,
    `title`              VARCHAR(300)    NOT NULL,
    `doc_no`             VARCHAR(100)    DEFAULT NULL           COMMENT '文号',
    `doc_type`           VARCHAR(20)     NOT NULL DEFAULT 'regulation'
                         COMMENT 'law/regulation/rule/notice/guideline/other',
    `category`           VARCHAR(32)     NOT NULL               COMMENT '冗余自 knowledge_base',
    `issuing_authority`  VARCHAR(100)    DEFAULT NULL           COMMENT '发布机构',
    `publish_date`       DATE            DEFAULT NULL,
    `effective_date`     DATE            DEFAULT NULL,
    `expiry_date`        DATE            DEFAULT NULL,
    `timeliness`         VARCHAR(16)     NOT NULL DEFAULT 'unknown'
                         COMMENT 'effective/amended/repealed/unknown',
    `superseded_by`      BIGINT UNSIGNED DEFAULT NULL           COMMENT '被哪份文档替代',
    `is_latest`          TINYINT         NOT NULL DEFAULT 1     COMMENT '1最新版 0历史版本',
    `file_name`          VARCHAR(255)    NOT NULL,
    `file_path`          VARCHAR(500)    NOT NULL               COMMENT '容器内绝对路径',
    `file_ext`           VARCHAR(16)     NOT NULL,
    `file_size`          BIGINT          NOT NULL DEFAULT 0     COMMENT '字节',
    `file_md5`           CHAR(32)        NOT NULL,
    `page_count`         INT             NOT NULL DEFAULT 0,
    `parse_method`       VARCHAR(16)     DEFAULT NULL           COMMENT 'text/ocr/mixed',
    `status`             VARCHAR(16)     NOT NULL DEFAULT 'pending'
                         COMMENT 'pending/parsing/embedding/ready/error/archived',
    `error_message`      VARCHAR(500)    DEFAULT NULL,
    `chunk_count`        INT             NOT NULL DEFAULT 0,
    `version`            INT             NOT NULL DEFAULT 1,
    `keywords`           VARCHAR(500)    DEFAULT NULL           COMMENT '逗号分隔',
    `uploaded_by`        BIGINT UNSIGNED DEFAULT NULL,
    `created_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_kb_md5` (`kb_id`, `file_md5`),
    KEY `idx_kb_status` (`kb_id`, `status`),
    KEY `idx_category` (`category`),
    KEY `idx_timeliness` (`timeliness`),
    KEY `idx_created_at` (`created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '制度文档表';

-- -----------------------------------------------------------------------------
-- 4. document_chunk · 文档切片（向量库的 MySQL 侧事实来源）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `document_chunk` (
    `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `document_id`      BIGINT UNSIGNED NOT NULL,
    `kb_id`            BIGINT UNSIGNED NOT NULL,
    `chunk_index`      INT             NOT NULL               COMMENT '文档内序号，从0开始',
    `chapter_no`       VARCHAR(50)     DEFAULT NULL           COMMENT '章，如 第三章',
    `article_no`       VARCHAR(50)     DEFAULT NULL           COMMENT '条，如 第二十五条',
    `page_start`       INT             DEFAULT NULL,
    `page_end`         INT             DEFAULT NULL,
    `content`          TEXT            NOT NULL               COMMENT '带元数据前缀，用于向量化与全文检索',
    `raw_content`      TEXT            NOT NULL               COMMENT '无前缀原文，用于展示',
    `char_count`       INT             NOT NULL DEFAULT 0,
    `source_type`      VARCHAR(16)     NOT NULL DEFAULT 'text' COMMENT 'text/table/ocr',
    `embedding_status` TINYINT         NOT NULL DEFAULT 0      COMMENT '0未向量化 1已向量化',
    `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_doc_chunk` (`document_id`, `chunk_index`),
    KEY `idx_kb` (`kb_id`),
    KEY `idx_document` (`document_id`),
    KEY `idx_article` (`document_id`, `article_no`),
    FULLTEXT KEY `ft_content` (`content`) WITH PARSER ngram
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '文档切片表';

-- -----------------------------------------------------------------------------
-- 5. knowledge_point · 核心知识点（★ 验收指标：published >= 1000）
--    code 采用「先插入取 id，再回填 KP-{CAT}-{id:04d}」的生成方式，
--    因此允许为 NULL 并保留唯一索引（MySQL 唯一索引允许多个 NULL）。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `knowledge_point` (
    `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `kb_id`              BIGINT UNSIGNED NOT NULL,
    `code`               VARCHAR(50)     DEFAULT NULL          COMMENT 'KP-{CAT}-{4位序号}',
    `title`              VARCHAR(300)    NOT NULL              COMMENT '问题式/结论式标题',
    `content`            TEXT            NOT NULL              COMMENT '知识点正文',
    `category`           VARCHAR(32)     NOT NULL              COMMENT 'banking/securities/insurance',
    `sub_category`       VARCHAR(50)     DEFAULT NULL          COMMENT '业务子类',
    `doc_no`             VARCHAR(100)    DEFAULT NULL,
    `issuing_authority`  VARCHAR(100)    DEFAULT NULL,
    `article_no`         VARCHAR(50)     DEFAULT NULL,
    `effective_date`     DATE            DEFAULT NULL,
    `expiry_date`        DATE            DEFAULT NULL,
    `timeliness`         VARCHAR(16)     NOT NULL DEFAULT 'unknown',
    `keywords`           VARCHAR(500)    DEFAULT NULL          COMMENT '逗号分隔，5~10个',
    `difficulty`         TINYINT         NOT NULL DEFAULT 1    COMMENT '1基础 2进阶 3专家',
    `source_type`        VARCHAR(16)     NOT NULL DEFAULT 'manual'
                         COMMENT 'manual/auto_extract/import',
    `primary_document_id` BIGINT UNSIGNED DEFAULT NULL,
    `primary_chunk_id`   BIGINT UNSIGNED DEFAULT NULL,
    `embedding_status`   TINYINT         NOT NULL DEFAULT 0,
    `confidence`         DECIMAL(4,3)    DEFAULT NULL          COMMENT '0.000~1.000',
    `verify_status`      VARCHAR(16)     NOT NULL DEFAULT 'pending'
                         COMMENT 'pending/passed/doubted/rejected',
    `verified_by`        BIGINT UNSIGNED DEFAULT NULL,
    `verified_at`        DATETIME        DEFAULT NULL,
    `verify_comment`     VARCHAR(500)    DEFAULT NULL,
    `status`             VARCHAR(16)     NOT NULL DEFAULT 'draft'
                         COMMENT 'draft/published/archived',
    `created_by`         BIGINT UNSIGNED DEFAULT NULL,
    `created_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_code` (`code`),
    KEY `idx_kb_cat` (`kb_id`, `category`),
    KEY `idx_verify` (`verify_status`),
    KEY `idx_status` (`status`),
    KEY `idx_timeliness` (`timeliness`),
    KEY `idx_sub_category` (`sub_category`),
    FULLTEXT KEY `ft_kp` (`title`, `content`, `keywords`) WITH PARSER ngram
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '知识点表';

-- -----------------------------------------------------------------------------
-- 6. knowledge_point_source · 知识点 ↔ 切片（多对多）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `knowledge_point_source` (
    `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `knowledge_point_id` BIGINT UNSIGNED NOT NULL,
    `chunk_id`           BIGINT UNSIGNED NOT NULL,
    `document_id`        BIGINT UNSIGNED NOT NULL,
    `page_no`            INT             DEFAULT NULL,
    `article_no`         VARCHAR(50)     DEFAULT NULL,
    `quote_text`         TEXT            DEFAULT NULL          COMMENT '支撑该知识点的原文片段',
    `source_url`         VARCHAR(2000)   DEFAULT NULL          COMMENT '溯源地址（/api/v1/documents/{id}/download#page=n）',
    `is_primary`         TINYINT         NOT NULL DEFAULT 0    COMMENT '1主来源',
    `created_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_kp_chunk` (`knowledge_point_id`, `chunk_id`),
    KEY `idx_chunk` (`chunk_id`),
    KEY `idx_kp` (`knowledge_point_id`, `is_primary`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '知识点来源关联表';

-- -----------------------------------------------------------------------------
-- 7. knowledge_point_relation · 知识点关联（条文关联查询）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `knowledge_point_relation` (
    `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `source_kp_id`  BIGINT UNSIGNED NOT NULL,
    `target_kp_id`  BIGINT UNSIGNED NOT NULL,
    `relation_type` VARCHAR(20)     NOT NULL
                    COMMENT 'same_topic/context/supersede/supplement/conflict',
    `score`         DECIMAL(5,4)    DEFAULT NULL,
    `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_rel` (`source_kp_id`, `target_kp_id`, `relation_type`),
    KEY `idx_source` (`source_kp_id`, `relation_type`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '知识点关联表';

-- -----------------------------------------------------------------------------
-- 8. qa_session · 问答会话
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `qa_session` (
    `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `session_no`     VARCHAR(40)     NOT NULL              COMMENT 's_yyyymmddHHMMSS_xxxxxx',
    `user_id`        BIGINT UNSIGNED NOT NULL,
    `title`          VARCHAR(200)    DEFAULT NULL,
    `kb_id`          BIGINT UNSIGNED DEFAULT NULL          COMMENT 'NULL=全部知识库',
    `message_count`  INT             NOT NULL DEFAULT 0,
    `last_active_at` DATETIME        DEFAULT NULL,
    `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_session_no` (`session_no`),
    KEY `idx_user_time` (`user_id`, `last_active_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '问答会话表';

-- -----------------------------------------------------------------------------
-- 9. qa_message · 问答消息
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `qa_message` (
    `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `session_id`      BIGINT UNSIGNED NOT NULL,
    `user_id`         BIGINT UNSIGNED NOT NULL,
    `parent_id`       BIGINT UNSIGNED DEFAULT NULL          COMMENT 'assistant 指向本轮 user 消息',
    `role`            VARCHAR(16)     NOT NULL              COMMENT 'user/assistant',
    `content`         MEDIUMTEXT      NOT NULL,
    `answer_type`     VARCHAR(16)     DEFAULT NULL          COMMENT 'answered/refused/error/clarify',
    `retrieval_mode`  VARCHAR(16)     DEFAULT NULL          COMMENT 'keyword/vector/hybrid',
    `confidence`      DECIMAL(4,3)    DEFAULT NULL,
    `latency_ms`      INT             DEFAULT NULL,
    `latency_detail`  JSON            DEFAULT NULL          COMMENT '{rewrite,retrieve,rerank,llm_ttft,total}',
    `prompt_version`  VARCHAR(16)     DEFAULT NULL,
    `model_name`      VARCHAR(50)     DEFAULT NULL,
    `token_usage`     JSON            DEFAULT NULL,
    `kb_id`           BIGINT UNSIGNED DEFAULT NULL,
    `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_session` (`session_id`, `id`),
    KEY `idx_user_time` (`user_id`, `created_at`),
    KEY `idx_answer_type` (`answer_type`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '问答消息表';

-- -----------------------------------------------------------------------------
-- 10. qa_citation · 答案引用溯源（★ 核心差异化能力）
--     对 document/chunk/kp 为弱引用，文档字段做冗余快照，保证历史可读。
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `qa_citation` (
    `id`                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `message_id`          BIGINT UNSIGNED NOT NULL          COMMENT 'assistant 消息 id',
    `cite_index`          INT             NOT NULL          COMMENT '答案角标序号 [n]',
    `chunk_id`            BIGINT UNSIGNED DEFAULT NULL,
    `knowledge_point_id`  BIGINT UNSIGNED DEFAULT NULL,
    `document_id`         BIGINT UNSIGNED DEFAULT NULL,
    `doc_title`           VARCHAR(300)    DEFAULT NULL,
    `doc_no`              VARCHAR(100)    DEFAULT NULL,
    `issuing_authority`   VARCHAR(100)    DEFAULT NULL,
    `article_no`          VARCHAR(50)     DEFAULT NULL,
    `page_no`             INT             DEFAULT NULL,
    `timeliness`          VARCHAR(16)     DEFAULT NULL,
    `snippet`             VARCHAR(1000)   DEFAULT NULL,
    `score`               DECIMAL(6,5)    DEFAULT NULL,
    `created_at`          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_message` (`message_id`, `cite_index`),
    KEY `idx_chunk` (`chunk_id`),
    KEY `idx_kp` (`knowledge_point_id`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '答案引用溯源表';

-- -----------------------------------------------------------------------------
-- 11. favorite · 收藏
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `favorite` (
    `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_id`       BIGINT UNSIGNED NOT NULL,
    `message_id`    BIGINT UNSIGNED NOT NULL,
    `session_id`    BIGINT UNSIGNED DEFAULT NULL,
    `question`      VARCHAR(500)    DEFAULT NULL,
    `answer_digest` VARCHAR(500)    DEFAULT NULL,
    `note`          VARCHAR(500)    DEFAULT NULL,
    `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_user_msg` (`user_id`, `message_id`),
    KEY `idx_user_time` (`user_id`, `created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '收藏表';

-- -----------------------------------------------------------------------------
-- 12. qa_feedback · 答案反馈
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `qa_feedback` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `message_id`  BIGINT UNSIGNED NOT NULL,
    `user_id`     BIGINT UNSIGNED NOT NULL,
    `rating`      TINYINT         NOT NULL              COMMENT '1点赞 -1点踩',
    `reason`      VARCHAR(50)     DEFAULT NULL
                  COMMENT 'inaccurate/incomplete/outdated/wrong_citation/other',
    `comment`     VARCHAR(1000)   DEFAULT NULL,
    `status`      VARCHAR(16)     NOT NULL DEFAULT 'open' COMMENT 'open/handled/ignored',
    `handled_by`  BIGINT UNSIGNED DEFAULT NULL,
    `handled_at`  DATETIME        DEFAULT NULL,
    `handle_note` VARCHAR(500)    DEFAULT NULL,
    `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_user_msg` (`user_id`, `message_id`),
    KEY `idx_status` (`status`),
    KEY `idx_rating` (`rating`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '答案反馈表';

-- -----------------------------------------------------------------------------
-- 13. qa_review · 人工校验记录（★ 85% 准确率的数据来源）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `qa_review` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `target_type` VARCHAR(20)     NOT NULL              COMMENT 'answer/knowledge_point',
    `target_id`   BIGINT UNSIGNED NOT NULL,
    `reviewer_id` BIGINT UNSIGNED NOT NULL,
    `is_correct`  TINYINT         NOT NULL              COMMENT '1正确 0错误',
    `error_type`  VARCHAR(32)     DEFAULT NULL
                  COMMENT 'retrieval_miss/hallucination/citation_wrong/outdated/incomplete',
    `comment`     VARCHAR(1000)   DEFAULT NULL,
    `batch_no`    VARCHAR(40)     DEFAULT NULL          COMMENT '评测批次号 EVAL-yyyymmdd',
    `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_reviewer_target` (`reviewer_id`, `target_type`, `target_id`),
    KEY `idx_target` (`target_type`, `target_id`),
    KEY `idx_batch` (`batch_no`),
    KEY `idx_error_type` (`error_type`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '人工校验记录表';

-- -----------------------------------------------------------------------------
-- 14. ingest_task · 入库任务
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `ingest_task` (
    `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `task_no`       VARCHAR(40)     NOT NULL              COMMENT 't_yyyymmddHHMMSS_xxxxxx',
    `document_id`   BIGINT UNSIGNED NOT NULL,
    `kb_id`         BIGINT UNSIGNED NOT NULL,
    `task_type`     VARCHAR(20)     NOT NULL DEFAULT 'ingest'
                    COMMENT 'ingest/reparse/reembed',
    `status`        VARCHAR(16)     NOT NULL DEFAULT 'queued'
                    COMMENT 'queued/parsing/cleaning/chunking/embedding/indexing/success/failed',
    `progress`      TINYINT         NOT NULL DEFAULT 0    COMMENT '0~100',
    `stage_message` VARCHAR(200)    DEFAULT NULL,
    `total_chunks`  INT             NOT NULL DEFAULT 0,
    `done_chunks`   INT             NOT NULL DEFAULT 0,
    `error_message` VARCHAR(1000)   DEFAULT NULL,
    `duration_ms`   INT             DEFAULT NULL,
    `started_at`    DATETIME        DEFAULT NULL,
    `finished_at`   DATETIME        DEFAULT NULL,
    `created_by`    BIGINT UNSIGNED DEFAULT NULL,
    `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_task_no` (`task_no`),
    KEY `idx_document` (`document_id`),
    KEY `idx_status` (`status`),
    KEY `idx_created_at` (`created_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '入库任务表';

-- -----------------------------------------------------------------------------
-- 15. operation_log · 操作日志（P2）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `operation_log` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `user_id`     BIGINT UNSIGNED DEFAULT NULL,
    `action`      VARCHAR(50)     NOT NULL,
    `target_type` VARCHAR(30)     DEFAULT NULL,
    `target_id`   BIGINT UNSIGNED DEFAULT NULL,
    `detail`      JSON            DEFAULT NULL,
    `ip`          VARCHAR(45)     DEFAULT NULL,
    `request_id`  VARCHAR(40)     DEFAULT NULL,
    `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_user_time` (`user_id`, `created_at`),
    KEY `idx_action` (`action`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '操作日志表';

-- -----------------------------------------------------------------------------
-- 16. system_config · 运行期配置（P2）
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `system_config` (
    `config_key`   VARCHAR(64)  NOT NULL,
    `config_value` VARCHAR(500) NOT NULL,
    `description`  VARCHAR(200) DEFAULT NULL,
    `updated_by`   BIGINT UNSIGNED DEFAULT NULL,
    `updated_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`config_key`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '系统配置表';

-- =============================================================================
--  初始化数据
-- =============================================================================

-- 三个内置知识库
INSERT INTO `knowledge_base` (`code`, `name`, `category`, `description`, `status`)
VALUES
    ('banking',    '银行监管制度库', 'banking',
     '中国人民银行、原银保监会、国家金融监督管理总局等发布的银行监管政策与规范性文件', 1),
    ('securities', '证券行业规范库', 'securities',
     '中国证监会、证券交易所、证券业协会发布的证券业务规范、自律规则与信息披露要求', 1),
    ('insurance',  '保险制度库', 'insurance',
     '国家金融监督管理总局、保险行业协会发布的保险产品、销售、偿付能力与资金运用制度', 1)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `description` = VALUES(`description`);

-- 运行期配置默认项
INSERT INTO `system_config` (`config_key`, `config_value`, `description`)
VALUES
    ('retrieval.default_mode',     'hybrid',  '默认检索模式：keyword/vector/hybrid'),
    ('retrieval.vector_top_k',     '20',      '向量召回条数'),
    ('retrieval.keyword_top_k',    '20',      '关键词召回条数'),
    ('retrieval.final_top_n',      '5',       '最终进入 Prompt 的证据条数'),
    ('retrieval.rrf_k',            '60',      'RRF 平滑常数'),
    ('retrieval.rrf_w_vector',     '0.6',     '向量通道权重'),
    ('retrieval.rrf_w_keyword',    '0.4',     '关键词通道权重'),
    ('retrieval.min_score',        '0.30',    '低于该融合分直接拒答'),
    ('rerank.enabled',             'false',   '是否启用重排模型（二期）'),
    ('prompt.version',             'v1.2',    '当前生效的 Prompt 版本号'),
    ('qa.multi_turn_enabled',      'true',    '是否启用多轮指代改写'),
    ('qa.max_context_chars',       '4000',    '拼入 Prompt 的上下文长度上限'),
    ('qa.confidence_high',         '0.80',    '可信度"高"的下限'),
    ('qa.confidence_medium',       '0.60',    '可信度"中"的下限'),
    ('llm.daily_token_budget',     '2000000', '当日 token 预算，超限降级为仅检索模式')
ON DUPLICATE KEY UPDATE `description` = VALUES(`description`);

-- =============================================================================
--  验收核对视图与语句（便于答辩现场取证）
-- =============================================================================

-- AC-01：核心知识点覆盖（要求 >= 1000）
-- SELECT COUNT(*) AS published_kp FROM knowledge_point WHERE status = 'published';

-- AC-03：人工校验准确率（要求 >= 0.85）
-- SELECT batch_no,
--        COUNT(*)                             AS total,
--        SUM(is_correct)                      AS correct,
--        ROUND(SUM(is_correct) / COUNT(*), 4) AS accuracy
-- FROM qa_review
-- WHERE target_type = 'answer'
-- GROUP BY batch_no;

-- 知识库资源概览
CREATE OR REPLACE VIEW `v_kb_overview` AS
SELECT kb.id,
       kb.code,
       kb.name,
       (SELECT COUNT(*) FROM document d
         WHERE d.kb_id = kb.id AND d.status = 'ready')      AS ready_documents,
       (SELECT COUNT(*) FROM document_chunk c
         WHERE c.kb_id = kb.id)                             AS chunks,
       (SELECT COUNT(*) FROM knowledge_point k
         WHERE k.kb_id = kb.id AND k.status = 'published')  AS published_kps,
       (SELECT COUNT(*) FROM knowledge_point k
         WHERE k.kb_id = kb.id AND k.verify_status = 'passed') AS verified_kps
FROM knowledge_base kb
WHERE kb.status = 1;

SET FOREIGN_KEY_CHECKS = 1;

-- =============================================================================
--  注意
--  管理员账号不在此脚本中创建（避免明文/固定哈希入库）。
--  由后端启动钩子 app/db/seed.py 依据 .env 的
--      SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD
--  创建或校正，默认 admin / Admin@123。
-- =============================================================================
