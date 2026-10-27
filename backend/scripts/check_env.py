"""环境变量自检：backend/.env（后端直跑）与 deploy/.env（docker compose）是否可用、是否一致。

检查项：
  1. backend/.env 是否存在拼错/未登记的键（pydantic extra=ignore 会**静默忽略**）
  2. 两个 .env 的关键项是否自相矛盾（最容易踩坑：Key 填在 deploy/.env，后端读 backend/.env）
  3. 数据目录是否存在且可写（不存在会自动创建）
  4. MySQL / Milvus 是否可连通
  5. LLM / Embedding 当前是 fake 还是真实provider

用法（backend 目录下）：
    python -m scripts.check_env
    python -m scripts.check_env --strict     # 出现 WARN 也返回非 0
退出码：0 = 无 ERR；1 = 有 ERR（--strict 下有 WARN 也算）
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.core.config import Settings, settings

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENV = ROOT / "backend" / ".env"
DEPLOY_ENV = ROOT / "deploy" / ".env"

#: 不属于 Settings 字段、但允许出现在 backend/.env 的键（由第三方库读取）
ALLOWED_EXTRA_KEYS = {"HF_ENDPOINT", "HF_HUB_OFFLINE", "HF_HOME", "TZ"}

#: 只出现在 deploy/.env 的 compose 变量
COMPOSE_ONLY_KEYS = {
    "TZ",
    "MYSQL_ROOT_PASSWORD",
    "MYSQL_DATABASE",
    "MINIO_IMAGE",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "MINIO_HOST_PORT",
    "MINIO_CONSOLE_HOST_PORT",
    "MILVUS_VERSION",
    "MILVUS_METRICS_HOST_PORT",
    "ATTU_VERSION",
    "ATTU_HOST_PORT",
    "FRONTEND_HOST_PORT",
    "BACKEND_HOST_PORT",
    "MYSQL_HOST_PORT",
    "MILVUS_HOST_PORT",
    "WITH_LIBREOFFICE",
    "VITE_API_BASE_URL",
    "VITE_APP_TITLE",
    "VITE_UPLOAD_MAX_MB",
}

PLACEHOLDER_PREFIX = "sk-CHANGE_ME"

errors: list[str] = []
warnings: list[str] = []
oks: list[str] = []


def parse_env(path: Path) -> dict[str, str]:
    """极简 dotenv 解析：KEY=VALUE，忽略注释与空行，去掉成对引号。"""
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #")[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key.strip()] = value
    return data


def mask(secret: str) -> str:
    if not secret:
        return "(空)"
    if len(secret) <= 10:
        return secret[:2] + "***"
    return f"{secret[:6]}...{secret[-4:]}"


def check_unknown_keys(backend_env: dict[str, str]) -> None:
    known = {name.upper() for name in Settings.model_fields}
    unknown = sorted(set(backend_env) - known - ALLOWED_EXTRA_KEYS)
    if unknown:
        warnings.append(
            "backend/.env 存在未登记的键（会被静默忽略，检查是否拼错）：" + ", ".join(unknown)
        )
    else:
        oks.append(f"backend/.env 的键全部能映射到 Settings（{len(backend_env)} 项）")


def check_cross_file(backend_env: dict[str, str], deploy_env: dict[str, str]) -> None:
    # 端口：backend 连宿主机映射端口，deploy 定义映射
    if backend_env.get("MYSQL_PORT") != deploy_env.get("MYSQL_HOST_PORT"):
        errors.append(
            f"MySQL 端口不通：deploy/.env MYSQL_HOST_PORT={deploy_env.get('MYSQL_HOST_PORT')} "
            f"≠ backend/.env MYSQL_PORT={backend_env.get('MYSQL_PORT')}"
        )
    else:
        oks.append(f"MySQL 端口一致（宿主机 {backend_env.get('MYSQL_PORT')}）")

    if backend_env.get("MILVUS_PORT") != deploy_env.get("MILVUS_HOST_PORT"):
        errors.append(
            f"Milvus 端口不一致：deploy={deploy_env.get('MILVUS_HOST_PORT')} "
            f"backend={backend_env.get('MILVUS_PORT')}"
        )
    else:
        oks.append(f"Milvus 端口一致（{backend_env.get('MILVUS_PORT')}）")

    # LLM：后端只读 backend/.env，deploy/.env 的 Key 对本地直跑无效
    be_provider = backend_env.get("LLM_PROVIDER", "")
    de_provider = deploy_env.get("LLM_PROVIDER", "")
    be_key = backend_env.get("LLM_API_KEY", "")
    de_key = deploy_env.get("LLM_API_KEY", "")
    if be_provider != de_provider:
        warnings.append(
            f"LLM_PROVIDER 不一致：deploy/.env={de_provider or '(空)'}，"
            f"backend/.env={be_provider or '(空)'}。本地直跑只读 backend/.env"
        )
    if de_key and not de_key.startswith(PLACEHOLDER_PREFIX) and be_key != de_key:
        errors.append(
            "deploy/.env 里像是真实 LLM_API_KEY，但 backend/.env 没有同步——"
            "本地直跑的后端读 backend/.env，会继续用占位实现"
        )
    elif be_key.startswith(PLACEHOLDER_PREFIX):
        warnings.append("backend/.env 的 LLM_API_KEY 仍是占位值（sk-CHANGE_ME）")

    if backend_env.get("SECRET_KEY") != deploy_env.get("SECRET_KEY"):
        warnings.append("两个 .env 的 SECRET_KEY 不一致（仅影响容器部署的 token 校验）")
    else:
        oks.append("SECRET_KEY 一致")


def check_dirs() -> None:
    for name in ("data_dir", "upload_dir", "ocr_cache_dir", "embedding_cache_dir"):
        path = Path(getattr(settings, name))
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            oks.append(f"{name} 可写：{path}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name} 不可用：{path}（{exc}）")


def check_services() -> None:
    try:
        from app.db.session import ping

        oks.append(f"MySQL 连接正常（{ping():.0f}ms）")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"MySQL 连接失败：{exc}")

    try:
        from app.rag.indexer import indexer

        oks.append(f"Milvus 连接正常（collection={settings.milvus_alias}，count={indexer.count()}）")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Milvus 连接失败：{exc}")


def check_llm_state() -> None:
    provider = (settings.llm_provider or "").lower()
    key = settings.llm_api_key or ""
    if provider == "fake":
        warnings.append("LLM_PROVIDER=fake：当前返回固定文本，不能做真实问答评测")
    elif key.startswith(PLACEHOLDER_PREFIX):
        errors.append("LLM_PROVIDER 不是 fake，但 LLM_API_KEY 仍是占位值，调用必然失败")
    else:
        oks.append(
            f"LLM 已配置真实渠道：provider={settings.llm_provider} "
            f"model={settings.llm_model} key={mask(key)}"
        )
    if settings.embedding_provider.lower() == "fake":
        warnings.append("EMBEDDING_PROVIDER=fake：语义检索无效（仅有关键词通道），达标评测前需切 local 并重建向量")
    else:
        oks.append(f"Embedding：{settings.embedding_provider} / {settings.embedding_model}")


def main(argv: list[str]) -> int:
    strict = "--strict" in argv

    print(f"backend/.env : {BACKEND_ENV}  {'存在' if BACKEND_ENV.exists() else '缺失'}")
    print(f"deploy/.env  : {DEPLOY_ENV}  {'存在' if DEPLOY_ENV.exists() else '缺失'}")

    if not BACKEND_ENV.exists():
        errors.append("backend/.env 缺失，后端会全部走默认值（连不上 3307 的 MySQL）")
    backend_env = parse_env(BACKEND_ENV)
    deploy_env = parse_env(DEPLOY_ENV)

    check_unknown_keys(backend_env)
    if deploy_env:
        check_cross_file(backend_env, deploy_env)
    else:
        warnings.append("deploy/.env 缺失，docker compose 起基础设施会失败")
    check_dirs()
    check_services()
    check_llm_state()

    print("\n== 结果 ==")
    for item in oks:
        print(f"[OK]   {item}")
    for item in warnings:
        print(f"[WARN] {item}")
    for item in errors:
        print(f"[ERR]  {item}")

    print(f"\n合计：OK={len(oks)} WARN={len(warnings)} ERR={len(errors)}")
    if errors or (strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
