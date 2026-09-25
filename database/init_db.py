"""
智愈错题 —— 数据库建表脚本

【怎么用】
先打开终端，进入项目根目录（D:\\0\\1），然后运行：

    python database/init_db.py

看到 "数据库初始化完成" 就成功了。

【它做了什么】
读取同目录下的 schema.sql，然后在 database/zhixue.db 里建好三张表。

【可以反复运行吗？】
可以。schema.sql 里每条建表语句都带 IF NOT EXISTS，
表已经存在就跳过，不会删掉你已有的数据。
"""

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------
# 1. 路径配置
#    Path(__file__) 是"当前这个脚本文件"，
#    .resolve() 把它变成完整路径，
#    .parent 取它所在的文件夹（也就是 database 文件夹）。
#    这样写的好处：不管你在哪个目录运行，路径都不会错。
# ---------------------------------------------------------------
DATABASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DATABASE_DIR / "schema.sql"
DB_PATH = DATABASE_DIR / "zhixue.db"


def init_db() -> None:
    """读取 schema.sql 并执行，完成建表。"""

    # 检查 schema.sql 在不在，不在就给个友好提示
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"找不到表结构文件：{SCHEMA_PATH}")

    # 读取 SQL 文件内容（指定 utf-8，否则中文注释会乱码）
    sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # 连接数据库。如果 zhixue.db 不存在，SQLite 会自动创建它。
    conn = sqlite3.connect(DB_PATH)
    try:
        # executescript 可以一次性执行多条 SQL 语句
        conn.executescript(sql)
        conn.commit()
    finally:
        # finally 保证不管有没有出错，最后都会关闭连接
        conn.close()


def show_tables() -> None:
    """把数据库里现有的表打印出来，方便确认建表成功。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

    print(f"\n数据库文件：{DB_PATH}")
    print(f"已有的表（共 {len(tables)} 张）：")
    for name in tables:
        print(f"  - {name}")


# ---------------------------------------------------------------
# 2. 脚本入口
#    if __name__ == "__main__": 的意思是
#    "只有直接运行这个文件时才执行下面的代码"。
#    如果别的文件 import 它，下面这段就不会自动跑。
# ---------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    print("数据库初始化完成！")
    show_tables()
