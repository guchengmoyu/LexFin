"""ORM 模型 ↔ 实际 MySQL 结构一致性巡检（联调/发版前使用）。

背景：`deploy/mysql/init/01-schema.sql` 只在容器**首次**初始化时执行，
因此模型新增的列（例如 `knowledge_point_source.source_url`）不会自动出现在
已有的数据库里，表现为运行时 `Unknown column ... in 'field list'`（HTTP 500）。

用法（在 backend 目录下）：
    python -m scripts.check_schema_drift
    python -m scripts.check_schema_drift --sql   # 额外输出可直接执行的 ALTER 建议

退出码：0 = 一致；1 = 存在漂移。
"""
from __future__ import annotations

import sys

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import Table

from app.db.base import Base
import app.models  # noqa: F401  导入以注册全部 ORM 模型
from app.db.session import get_engine


def _render_type(column) -> str:
    """尽量生成与 DDL 风格一致的列类型。"""
    try:
        return column.type.compile(dialect=get_engine().dialect)
    except Exception:  # pragma: no cover - 兜底
        return "VARCHAR(255)"


def collect_differences(engine: Engine) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """返回 (列差异列表, 缺失表列表)。列差异元素为 (表名, 列名, 方向, 建议类型)。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    differences: list[tuple[str, str, str, str]] = []
    missing_tables: list[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            missing_tables.append(table.name)
            continue
        db_columns = {column["name"] for column in inspector.get_columns(table.name)}
        model_columns = {column.name: column for column in table.columns}
        for name in sorted(model_columns.keys() - db_columns):
            differences.append((table.name, name, "仅模型有", _render_type(model_columns[name])))
        for name in sorted(db_columns - model_columns.keys()):
            differences.append((table.name, name, "仅库里有", ""))

    return differences, missing_tables


def main(argv: list[str]) -> int:
    engine = get_engine()
    differences, missing_tables = collect_differences(engine)

    total_tables = len(Base.metadata.sorted_tables)
    print(f"ORM 表数={total_tables}  实际表数={len(inspect(engine).get_table_names())}")

    for name in missing_tables:
        print(f"[缺表] {name}（请执行 deploy/mysql/init/01-schema.sql 或手工建表）")

    for table, column, direction, sql_type in differences:
        if direction == "仅模型有":
            print(f"[缺列] {table}.{column} {sql_type}")
            if "--sql" in argv:
                _print_alter(table, column, sql_type)
        else:
            print(f"[多余列] {table}.{column}（ORM 已无此字段）")

    if not differences and not missing_tables:
        print("结构一致：ORM 模型与实际数据库无差异")
        return 0
    print(f"共发现 {len(differences) + len(missing_tables)} 处差异")
    return 1


def _print_alter(table_name: str, column_name: str, sql_type: str) -> None:
    print(f"    ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {sql_type} NULL;")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
