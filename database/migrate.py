"""
智愈错题 —— 数据库迁移脚本
把旧版（dialogues）升级到新版（sessions + messages）

============================================================
【什么时候要运行它？】
只有一种情况：你之前用旧版跑过，数据库里已经有 dialogues 表。

运行命令（在项目根目录 D:\\0\\1 下）：
    python database/migrate.py

============================================================
【它会做什么？】
    1. 先把整个 zhixue.db 完整备份到 database/backup/ 文件夹
    2. 把旧的 dialogues 表改名为 dialogues_backup_年月日_时分秒
       （注意：是"改名"不是"删除"，数据还在！）
    3. 建好新的 sessions 和 messages 表
    4. 把旧数据搬过来：
          每一条旧记录  ->  变成 1 个会话 + 2 条消息
          （学生问的 -> user 消息，AI 答的 -> assistant 消息）

============================================================
【安全吗？】
安全。三步保险：
    - 迁移前自动备份整个数据库文件
    - 旧表只是改名，不删除
    - 整个过程在一个事务里，中途出错会自动回滚

如果迁移完发现哪里不对，把 database/backup/ 里的备份文件
复制回来改名成 zhixue.db 就恢复原样了。

============================================================
【可以重复运行吗？】
可以。搬过一次之后 dialogues 表就不存在了，
再运行它会直接跳过并提示"无需迁移"。
"""

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------
DATABASE_DIR = Path(__file__).resolve().parent
DB_PATH = DATABASE_DIR / "zhixue.db"
SCHEMA_PATH = DATABASE_DIR / "schema.sql"
BACKUP_DIR = DATABASE_DIR / "backup"


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """检查某张表在不在。"""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def make_backup() -> Path:
    """把整个数据库文件复制一份到 backup 文件夹。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"zhixue_backup_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def make_title(text: str, limit: int = 20) -> str:
    """从错题内容里截一段，当作会话标题。"""
    # split() 会把换行、连续空格都切开，join 再拼成一行
    one_line = " ".join(text.split())
    if not one_line:
        return "新会话"
    if len(one_line) <= limit:
        return one_line
    return one_line[:limit] + "…"


def ensure_pinned_column() -> bool:
    """
    给 sessions 表补上 is_pinned（置顶）字段。

    返回 True 表示这次真的补了，False 表示本来就有 / 还没建表。

    ── 为什么需要这个？ ──
    schema.sql 里写的是 CREATE TABLE IF NOT EXISTS，
    它只在"表不存在"时建表。对已经建好的表加字段，它是不会管的。

    ── 会不会丢数据？ ──
    不会。ALTER TABLE ... ADD COLUMN 只增加一列：
      · 其他列原封不动
      · 带了 DEFAULT 0，已有行自动填 0
      · 不删除、不修改任何现有记录

    ── 对应的 SQL 语句（你也可以在 DB Browser 里手动执行）──
        ALTER TABLE sessions ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0;
    """
    if not DB_PATH.exists():
        return False

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # 表还没建的话，直接跳过（init_db 会带着这一列一起建）
        if not table_exists(conn, "sessions"):
            return False

        columns = [row["name"] for row in conn.execute("PRAGMA table_info(sessions)")]
        if "is_pinned" in columns:
            return False

        conn.execute(
            "ALTER TABLE sessions ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
        return True
    finally:
        conn.close()


def migrate() -> int:
    """
    执行迁移。返回迁移的记录条数（0 表示没东西需要迁移）。
    """

    if not DB_PATH.exists():
        print(f"没有找到数据库文件：{DB_PATH}")
        print("说明你还没跑过旧版本，不需要迁移。")
        print("直接运行 python database/init_db.py 建新表即可。")
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        # ---- 情况 A：没有旧的 dialogues 表，什么都不用做 ----
        if not table_exists(conn, "dialogues"):
            print("数据库里没有旧的 dialogues 表，无需迁移。")
            print("（直接运行 python database/init_db.py 建新表即可）")
            return 0

        # ---- 读出旧数据 ----
        old_rows = conn.execute(
            "SELECT id, student_id, user_input, ai_response, "
            "       knowledge_point, error_type, created_at "
            "FROM dialogues ORDER BY id"
        ).fetchall()

        print(f"发现旧表 dialogues，共有 {len(old_rows)} 条记录。")

        if not old_rows:
            print("旧表是空的，直接把表改名留作纪念，不搬数据。")

        # ---- 备份整个文件（在改动之前做）----
        backup_path = make_backup()
        print(f"已备份数据库 -> {backup_path}")

        # ---- 建新表（schema.sql 里有 IF NOT EXISTS，不会破坏已有表）----
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)

        # ---- 开始搬数据 ----
        # 用一个大事务包起来：全部成功才提交，中途出错就自动回滚
        migrated = 0
        for row in old_rows:
            # 1) 建一个会话
            cursor = conn.execute(
                "INSERT INTO sessions (student_id, title, created_at) "
                "VALUES (?, ?, ?)",
                (row["student_id"], make_title(row["user_input"]), row["created_at"]),
            )
            session_id = cursor.lastrowid

            # 2) 学生那条消息（对应旧的 user_input）
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) "
                "VALUES (?, 'user', ?, ?)",
                (session_id, row["user_input"], row["created_at"]),
            )

            # 3) AI 那条消息（对应旧的 ai_response）
            #    如果旧记录的 ai_response 是空的（当时 AI 失败了），就不建这条
            if row["ai_response"]:
                conn.execute(
                    "INSERT INTO messages "
                    "(session_id, role, content, knowledge_point, error_type, created_at) "
                    "VALUES (?, 'assistant', ?, ?, ?, ?)",
                    (
                        session_id,
                        row["ai_response"],
                        row["knowledge_point"],
                        row["error_type"],
                        row["created_at"],
                    ),
                )

            migrated += 1

        # ---- 旧表改名，保留数据（不删除！）----
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_table = f"dialogues_backup_{stamp}"
        conn.execute(f"ALTER TABLE dialogues RENAME TO {backup_table}")

        conn.commit()

        print(f"迁移完成：{migrated} 条旧记录 -> {migrated} 个会话")
        print(f"旧表已改名为：{backup_table}（数据还在，确认没问题后可以自己删）")
        return migrated

    except Exception:
        # 出错了就回滚，保证数据库还是迁移前的样子
        conn.rollback()
        raise
    finally:
        conn.close()


def show_result() -> None:
    """打印迁移后的表情况，让人一眼看到结果。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        print("\n当前数据库里的表：")
        for name in names:
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"  - {name:<32} {count} 行")
    finally:
        conn.close()


if __name__ == "__main__":
    # 如果想跳过确认直接迁移，运行：python database/migrate.py --yes
    skip_confirm = "--yes" in sys.argv or "-y" in sys.argv

    if not skip_confirm:
        print("=" * 60)
        print("即将做两件事：")
        print("  1. 给 sessions 表补上 is_pinned（置顶）字段（安全，不动数据）")
        print("  2. 把旧的 dialogues 表迁移成 sessions + messages")
        print("过程会自动备份数据库，旧表只改名不删除，是安全的。")
        print("=" * 60)
        answer = input("确定要继续吗？输入 y 回车：").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消，什么都没改。")
            sys.exit(0)

    # 先补字段（这一步只加一列，原有数据一行都不会动）
    if ensure_pinned_column():
        print("已给 sessions 表新增 is_pinned 字段（原有会话数据全部保留）")
    else:
        print("sessions 表已有 is_pinned 字段，跳过")

    moved = migrate()
    show_result()

    if moved > 0:
        print("\n迁移成功！现在可以启动后端了。")
    else:
        print("\n数据库已经是最新的，不需要迁移。")
