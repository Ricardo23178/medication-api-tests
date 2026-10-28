"""重建一次性测试库。

为什么需要这一步：
    接口测试会真实写入数据（注册账号、建药品、建计划、确认服药）。
    如果直接跑在开发库 medication_system 上，测试数据会混进演示数据里，
    答辩演示前还得手工清理。所以测试前先造一个独立库，
    用例在里面随便写，跑完删掉即可。

用法：
    python scripts/prepare_db.py              # 重建默认测试库
    python scripts/prepare_db.py --quiet      # 只报结果
    python scripts/prepare_db.py --keep-data  # 库已存在时不重建

连接参数按这个顺序取：环境变量 > .env 文件 > 下面写的默认值。
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

import pymysql

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_FILE = ROOT / "schema" / "schema.sql"

DEFAULTS = {
    "MED_DB_HOST": "127.0.0.1",
    "MED_DB_PORT": "3306",
    "MED_DB_USER": "root",
    "MED_DB_PASSWORD": "",
    "MED_TEST_DB": "medication_api_test",
}


def load_dotenv() -> None:
    """读取项目根目录的 .env，只补齐缺失的变量，不覆盖已有的环境变量。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def setting(name: str) -> str:
    return os.environ.get(name) or DEFAULTS[name]


def split_statements(sql: str) -> list[str]:
    """按行切分 SQL 语句。

    不用 split(';')：注释和字符串里都可能出现分号。
    这份 schema 由 mysqldump 生成，每条语句都以行尾分号结束，
    所以「行尾是分号」就是最可靠的语句边界。
    """
    statements, buffer = [], []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if line.rstrip().endswith(";"):
            statements.append("\n".join(buffer))
            buffer = []
    if buffer:
        statements.append("\n".join(buffer))
    return statements


def main() -> int:
    parser = argparse.ArgumentParser(description="重建接口测试用的一次性数据库")
    parser.add_argument("--keep-data", action="store_true", help="库已存在时直接复用，不重建")
    parser.add_argument("--quiet", action="store_true", help="只输出结果")
    args = parser.parse_args()

    load_dotenv()
    db_name = setting("MED_TEST_DB")
    if not db_name.endswith("_test") and "_test" not in db_name:
        print(f"拒绝执行：库名 {db_name!r} 看起来不像测试库，"
              f"库名必须包含 _test，避免误删开发库。", file=sys.stderr)
        return 2

    conn_args = dict(
        host=setting("MED_DB_HOST"),
        port=int(setting("MED_DB_PORT")),
        user=setting("MED_DB_USER"),
        password=setting("MED_DB_PASSWORD"),
        charset="utf8mb4",
        autocommit=True,
    )

    try:
        conn = pymysql.connect(**conn_args)
    except pymysql.MySQLError as exc:
        print(f"连不上 MySQL（{conn_args['host']}:{conn_args['port']}）：{exc}", file=sys.stderr)
        print("检查 MySQL 是否已启动，以及 .env 里的 MED_DB_USER / MED_DB_PASSWORD 是否正确。",
              file=sys.stderr)
        return 1

    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s", (db_name,)
        )
        exists = cur.fetchone()[0] > 0

        if exists and args.keep_data:
            if not args.quiet:
                print(f"复用已有测试库 {db_name}（--keep-data）")
            return 0

        cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        cur.execute(
            f"CREATE DATABASE `{db_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        cur.execute(f"USE `{db_name}`")

        # 表之间有外键，但建表语句按表名字母序排列，父表不一定先建。
        # 关掉外键检查让建表一次通过，建完立刻恢复，不影响后续用例的数据一致性。
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        statements = split_statements(SCHEMA_FILE.read_text(encoding="utf-8"))
        for stmt in statements:
            cur.execute(stmt)
        cur.execute("SET FOREIGN_KEY_CHECKS=1")

        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema=%s AND table_type='BASE TABLE'",
            (db_name,),
        )
        table_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM admin_setting")
        seed_count = cur.fetchone()[0]

    if not args.quiet:
        print(f"测试库已重建：{db_name}")
        print(f"  表数量   {table_count}")
        print(f"  配置种子 {seed_count} 行 (admin_setting)")
        print()
        print("启动被测服务（另开一个终端）：")
        print(f"  export DB_URL='jdbc:mysql://{conn_args['host']}:{conn_args['port']}/"
              f"{db_name}?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai'")
        print(f"  export DB_PASSWORD='<你的 MySQL 密码>'")
        print("  ./mvnw spring-boot:run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
