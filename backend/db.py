"""
智愈错题 —— 数据库操作模块（v0.5 多轮对话版）

这个文件把"所有跟数据库打交道的事情"集中在一起。
main.py 只管接收 HTTP 请求，具体怎么存、怎么查，都由这里负责。

这种写法叫"分层"：接口层（main.py）和数据层（db.py）分开。
好处是以后换成 MySQL 之类，只要改这一个文件。

【重要变更】
旧版操作的是 dialogues 表（一问一答）。
新版操作的是 sessions（会话）+ messages（消息）。
如果数据库里还有旧表，请先运行：python database/migrate.py

【表之间的关系】
    students (学生)
       └── sessions (会话)          一个学生有多个会话
              └── messages (消息)   一个会话有多条消息

数据库文件位置：database/zhixue.db（自动创建，不用手动建）
"""

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------
# 1. 路径配置
#    __file__ 是 backend/db.py
#    .parent          -> backend 文件夹
#    .parent.parent   -> 项目根目录 你的目录
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_DIR = PROJECT_ROOT / "database"
SCHEMA_PATH = DATABASE_DIR / "schema.sql"
DB_PATH = DATABASE_DIR / "zhixue.db"


# ---------------------------------------------------------------
# 2. 基础函数：连接数据库 / 建表 / 检查旧表
# ---------------------------------------------------------------
def get_connection() -> sqlite3.Connection:
    """
    创建一个数据库连接。

    row_factory = sqlite3.Row 的作用：
    查询结果可以用 row["name"] 这样的方式取值，
    而不是只能 row[0]、row[1] 数下标，可读性好很多。
    """
    # 如果 database 文件夹不存在就先创建（exist_ok=True 表示已存在也不报错）
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    # 让查询结果支持用列名取值
    conn.row_factory = sqlite3.Row

    # 打开外键检查。
    # 注意：SQLite 默认不检查外键，必须每次连接都手动打开！
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_db() -> None:
    """
    执行 schema.sql，建好所有表。

    服务每次启动都会调用它。
    因为 SQL 里写了 IF NOT EXISTS，已经存在的表会被跳过，
    所以重启服务不会丢数据，也不会报错。
    """
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"找不到表结构文件：{SCHEMA_PATH}")

    sql = SCHEMA_PATH.read_text(encoding="utf-8")

    conn = get_connection()
    try:
        conn.executescript(sql)

        # ★ 补字段：给老数据库加上后来才新增的列
        added = _ensure_columns(conn)
        if added:
            print(f"[智愈错题] 数据库升级完成，sessions 表新增字段：{', '.join(added)}")

        conn.commit()
    finally:
        conn.close()


# 会话的四种教学状态（写在这里方便别处引用，避免打错字）
STATUS_DIAGNOSING = "diagnosing"   # 首次诊断：还没诊断过
STATUS_GUIDING = "guiding"         # 引导追问中：正在一步步引导学生
STATUS_SOLVED = "solved"           # 学生已经做对了
STATUS_PRACTICING = "practicing"   # 正在做变式练习题


def _ensure_columns(conn: sqlite3.Connection) -> list[str]:
    """
    确保 sessions 表有后来新增的字段。少了就补上，返回补了哪些。

    ── 为什么需要这个函数？ ──
    schema.sql 里写的是 CREATE TABLE IF NOT EXISTS，
    它的意思是"表不存在才建表"。对于**已经建好的表**，
    你在 schema.sql 里新加一个字段，重启服务是完全没有效果的。

    ── 为什么不用删表重建？ ──
    因为那样会把你已有的会话和聊天记录全部清空。

    ── 这里用的办法 ──
    先用 PRAGMA table_info 查出这张表实际有哪些列，
    发现少了就执行一次 ALTER TABLE ADD COLUMN。

    ALTER TABLE ... ADD COLUMN 是安全的：
      · 只增加一列，不动其他任何列
      · 带了 DEFAULT，已有的行会自动填默认值（不会变成 NULL）
      · 不会删除、修改任何现有数据
      · 执行很快（SQLite 只在表结构上记一笔）
    """
    # 想要有的字段：字段名 -> 建列语句
    # 想要有的字段：表名 -> {字段名: 建列语句}
    wanted = {
        "sessions": {
            "is_pinned": "INTEGER NOT NULL DEFAULT 0",
            # ★ 会话当前处于哪个教学阶段，见上面那四个常量
            "status": "TEXT NOT NULL DEFAULT 'diagnosing'",
        },
        "messages": {
            # ★ 错因的"固定分类"（7 选 1），专门用来画统计图表。
            #   原来的 error_type 改存详细的错因分析（长句子）。
            #   加个默认值 '其他'，老数据自动填上，不会变成 NULL。
            "error_category": "TEXT",
        },
    }

    added = []
    for table, columns in wanted.items():
        existing = [
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
        ]
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
                added.append(f"{table}.{column}")

    return added


def set_session_status(session_id: int, status: str) -> dict | None:
    """更新会话当前的教学状态。"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sessions SET status = ? WHERE id = ?",
            (status, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    return get_session(session_id)


def has_legacy_table() -> bool:
    """
    检查有没有旧版的 dialogues 表。

    如果有，说明用户还没跑 migrate.py，
    main.py 启动时会用这个函数给出提醒。
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'dialogues'"
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ---------------------------------------------------------------
# 3. students 表的操作（和以前一样）
# ---------------------------------------------------------------
def create_student(name: str) -> dict:
    """新增一个学生，ID 由数据库自动分配。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO students (name) VALUES (?)",
            (name,),
        )
        conn.commit()
        new_id = cursor.lastrowid      # 拿到刚插入那行的 id
    finally:
        conn.close()

    return get_student(new_id)


def create_student_with_id(student_id: int, name: str) -> dict:
    """新增学生，并手动指定 id（用于前端指定了学号的情况）。"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO students (id, name) VALUES (?, ?)",
            (student_id, name),
        )
        conn.commit()
    finally:
        conn.close()

    return get_student(student_id)


def get_student(student_id: int) -> dict | None:
    """按 id 查学生。查不到返回 None。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
        # 必须在关闭连接之前把 row 转成普通字典，
        # 否则连接关掉后 row 就不能用了。
        return dict(row) if row is not None else None
    finally:
        conn.close()


def list_students() -> list[dict]:
    """查出所有学生，按 id 排序。"""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM students ORDER BY id").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_or_create_student(student_id: int) -> tuple[dict, bool]:
    """
    拿到学生；不存在就自动创建一个。

    返回 (学生字典, 是不是新建的)。
    这样测试时不用先手动建学生。
    """
    student = get_student(student_id)
    if student is not None:
        return student, False
    return create_student_with_id(student_id, f"学生{student_id}"), True


# ---------------------------------------------------------------
# 4. sessions 表的操作（新增）
# ---------------------------------------------------------------

def create_session(student_id: int, title: str = "新会话") -> dict:
    """新建一个会话，返回会话信息（含 session_id）。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO sessions (student_id, title) VALUES (?, ?)",
            (student_id, title),
        )
        conn.commit()
        new_id = cursor.lastrowid
    finally:
        conn.close()

    return get_session(new_id)


def get_session(session_id: int) -> dict | None:
    """按 id 查会话。查不到返回 None。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def list_sessions(student_id: int) -> list[dict]:
    """
    查某个学生的所有会话。

    排序规则（很重要）：
        1. 先按 is_pinned 倒序 —— 置顶的（1）永远排在普通会话（0）前面
        2. 再按"最后一条消息的时间"倒序 —— 最近聊过的排前面
        3. 最后按 id 倒序 —— 时间相同时，新建的排前面

    这里用了 LEFT JOIN：把 sessions 和 messages 连起来，
    顺便算出每个会话有多少条消息、最后一条消息是什么时候发的。
    LEFT 的意思是"就算这个会话一条消息都没有，也要列出来"。
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                s.id,
                s.student_id,
                s.title,
                s.is_pinned,
                s.created_at,
                COUNT(m.id)        AS message_count,
                MAX(m.created_at)  AS last_message_at
              FROM sessions s
              LEFT JOIN messages m ON m.session_id = s.id
             WHERE s.student_id = ?
             GROUP BY s.id
             ORDER BY s.is_pinned DESC,
                      COALESCE(MAX(m.created_at), s.created_at) DESC,
                      s.id DESC
            """,
            (student_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def set_session_pinned(session_id: int, pinned: bool) -> dict | None:
    """
    设置会话的置顶状态。

    SQLite 没有布尔类型，所以把 True/False 转成 1/0 存进去。
    """
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sessions SET is_pinned = ? WHERE id = ?",
            (1 if pinned else 0, session_id),
        )
        conn.commit()
    finally:
        conn.close()

    return get_session(session_id)


def update_session_title(session_id: int, title: str) -> None:
    """修改会话标题（第一条消息发出去后用它自动命名）。"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (title, session_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_session(session_id: int) -> dict:
    """
    彻底删除一个会话：连同它所有的聊天记录。

    ── 分两步，放在同一个事务里 ──
        第 1 步：DELETE FROM messages WHERE session_id = ?   删掉所有聊天记录
        第 2 步：DELETE FROM sessions WHERE id = ?           删掉会话本身

    ── 既然建表时已经写了 ON DELETE CASCADE，为什么还要手动删一遍？──
    因为 CASCADE（级联删除）依赖每条数据库连接都执行过
        PRAGMA foreign_keys = ON
    这个开关默认是【关】的。万一以后有人在别的地方忘了打开，
    CASCADE 会静默失效，sessions 被删了但 messages 还留着，
    变成永远查不到、也删不掉的"孤儿数据"。

    手动删一遍是双保险：多删一次不存在的行不会报错，也没有副作用。

    返回删掉了几条消息、几个会话，方便接口层确认。
    """
    conn = get_connection()
    try:
        # 同一个连接 = 同一个事务，两条语句要么都成功、要么都回滚
        msg_cursor = conn.execute(
            "DELETE FROM messages WHERE session_id = ?", (session_id,)
        )
        deleted_messages = msg_cursor.rowcount

        sess_cursor = conn.execute(
            "DELETE FROM sessions WHERE id = ?", (session_id,)
        )
        deleted_sessions = sess_cursor.rowcount

        conn.commit()
        return {"sessions": deleted_sessions, "messages": deleted_messages}

    except Exception:
        conn.rollback()      # 中途出错就整体回滚，绝不留下删一半的状态
        raise
    finally:
        conn.close()


def delete_sessions(session_ids: list[int]) -> dict:
    """
    批量彻底删除多个会话（逻辑和单条删除完全一样，只是用 IN 一次处理一批）。

    全部放在一个事务里：
        要么全部都删干净，要么一条都不删。
        不会出现"删了一半"的中间状态。

    ⚠️ 关于 SQL 注入：
       IN (?, ?, ?) 里的问号是根据 id 的【个数】生成的，
       具体的 id 值仍然是用参数传进去的，绝对没有把用户输入拼进 SQL。
    """
    # 去重 + 过滤掉非法值，顺便保持顺序稳定
    ids: list[int] = []
    for raw in session_ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in ids:
            ids.append(value)

    if not ids:
        return {"sessions": 0, "messages": 0, "session_ids": []}

    # 生成 "?,?,?" 这样的占位符，几个 id 就几个问号
    placeholders = ",".join("?" * len(ids))

    conn = get_connection()
    try:
        msg_cursor = conn.execute(
            f"DELETE FROM messages WHERE session_id IN ({placeholders})",
            ids,
        )
        deleted_messages = msg_cursor.rowcount

        sess_cursor = conn.execute(
            f"DELETE FROM sessions WHERE id IN ({placeholders})",
            ids,
        )
        deleted_sessions = sess_cursor.rowcount

        conn.commit()
        return {
            "sessions": deleted_sessions,
            "messages": deleted_messages,
            "session_ids": ids,
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def count_orphan_messages() -> int:
    """
    数一数有多少条"孤儿消息"—— 即 session_id 指向一个已经不存在的会话。

    正常情况下这个数字应该永远是 0。
    LEFT JOIN 之后 s.id 为 NULL 的行，就是找不到对应会话的消息。

    这是检查"删除是不是真的删干净了"最直接的指标。
    """
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT COUNT(*)
              FROM messages m
              LEFT JOIN sessions s ON s.id = m.session_id
             WHERE s.id IS NULL
            """
        ).fetchone()[0]
    finally:
        conn.close()


def count_rows() -> dict:
    """统计各张表里有多少行，用于排查和验证。"""
    conn = get_connection()
    try:
        result = {}
        for table in ("students", "sessions", "messages", "reports"):
            result[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------
# 7. 学习报告：按知识点 / 错因做聚合统计
# ---------------------------------------------------------------

# 变式练习题的那条 AI 消息，它的 error_type 固定是这个值。
# 统计报告时要把它排除掉，否则"生成变式题"会把知识点计数刷高。
VARIANT_TAG = "变式练习"


def get_study_report(student_id: int) -> dict:
    """
    统计某个学生的学习情况。

    统计口径：
        只看 role = 'assistant'（AI 的诊断回复）里成功提取出
        knowledge_point / error_type 的那些消息。
        并且排除掉"变式练习"，因为那是练习题不是错因。

    SQL 里的 GROUP BY 就是"按某一列分组计数"，
    相当于把全班同学的分数按"及格/不及格"分成两堆数人数。
    """
    conn = get_connection()
    try:
        # ---- 总体数字 ----
        total_sessions = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE student_id = ?",
            (student_id,),
        ).fetchone()[0]

        total_questions = conn.execute(
            """
            SELECT COUNT(*) FROM messages m
              JOIN sessions s ON s.id = m.session_id
             WHERE s.student_id = ? AND m.role = 'user'
            """,
            (student_id,),
        ).fetchone()[0]

        diagnosed = conn.execute(
            f"""
            SELECT COUNT(*) FROM messages m
              JOIN sessions s ON s.id = m.session_id
             WHERE s.student_id = ?
               AND m.role = 'assistant'
               AND m.knowledge_point IS NOT NULL
               AND m.knowledge_point <> ''
               AND (m.error_type IS NULL OR m.error_type <> '{VARIANT_TAG}')
            """,
            (student_id,),
        ).fetchone()[0]

        # ---- 知识点排行（柱状图用）----
        knowledge_rows = conn.execute(
            f"""
            SELECT m.knowledge_point AS name, COUNT(*) AS count
              FROM messages m
              JOIN sessions s ON s.id = m.session_id
             WHERE s.student_id = ?
               AND m.role = 'assistant'
               AND m.knowledge_point IS NOT NULL
               AND m.knowledge_point <> ''
               AND (m.error_type IS NULL OR m.error_type <> '{VARIANT_TAG}')
             GROUP BY m.knowledge_point
             ORDER BY count DESC, m.knowledge_point ASC
            """,
            (student_id,),
        ).fetchall()

        # ---- 错因分布（饼图用）----
        error_rows = conn.execute(
            f"""
            SELECT m.error_category AS name, COUNT(*) AS count
              FROM messages m
              JOIN sessions s ON s.id = m.session_id
             WHERE s.student_id = ?
               AND m.role = 'assistant'
               AND m.error_category IS NOT NULL
               AND m.error_category <> ''
               AND m.error_type <> '{VARIANT_TAG}'
             GROUP BY m.error_category
             ORDER BY count DESC, m.error_category ASC
            """,
            (student_id,),
        ).fetchall()

        # ---- 最近几条"错题 -> 知识点"记录，报告里列出来 ----
        recent_rows = conn.execute(
            f"""
            SELECT m.knowledge_point, m.error_type, m.created_at
              FROM messages m
              JOIN sessions s ON s.id = m.session_id
             WHERE s.student_id = ?
               AND m.role = 'assistant'
               AND m.knowledge_point IS NOT NULL
               AND m.knowledge_point <> ''
               AND (m.error_type IS NULL OR m.error_type <> '{VARIANT_TAG}')
             ORDER BY m.id DESC
             LIMIT 8
            """,
            (student_id,),
        ).fetchall()

    finally:
        conn.close()

    return {
        "student_id": student_id,
        "summary": {
            "total_sessions": total_sessions,
            "total_questions": total_questions,
            "diagnosed": diagnosed,
            # 掌握度：已经诊断过的题里，没有被反复记成同一个错因的比例。
            # 只是个粗略的展示指标，不用太当真。
            "knowledge_count": len(knowledge_rows),
            "error_type_count": len(error_rows),
        },
        "knowledge_points": [dict(r) for r in knowledge_rows],
        "error_types": [dict(r) for r in error_rows],
        "recent": [dict(r) for r in recent_rows],
    }


# ---------------------------------------------------------------
# 5. messages 表的操作（新增）
#
#    参数里的 "?" 叫"占位符"，是防 SQL 注入的标准做法。
#    千万不要用 f-string 把用户输入直接拼进 SQL 里！
# ---------------------------------------------------------------

def save_message(
    session_id: int,
    role: str,
    content: str,
    knowledge_point: str | None = None,
    error_type: str | None = None,
    error_category: str | None = None,
) -> dict:
    """
    往会话里追加一条消息。

    role 只能是 "user" 或 "assistant"（数据库有 CHECK 约束把关）。
    knowledge_point / error_type 一般只有 AI 回复才需要传。
    """

    # ★ 防御性处理：error_category 这一列在某些老数据库里是 NOT NULL 的。
    #   SQLite 的规则是：DEFAULT 只在"省略该列"时生效，
    #   如果显式插入 None，会直接报 "NOT NULL constraint failed"。
    #   用户消息本来就没有错因，这里统一转成空字符串，避免报错。
    if error_category is None:
        error_category = ""
    if role not in ("user", "assistant"):
        raise ValueError("role 只能是 'user' 或 'assistant'")

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO messages
                (session_id, role, content, knowledge_point, error_type, error_category)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, role, content, knowledge_point, error_type, error_category),
        )
        conn.commit()
        new_id = cursor.lastrowid
    finally:
        conn.close()

    return get_message(new_id)


def get_message(message_id: int) -> dict | None:
    """按 id 查一条消息。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def list_messages(session_id: int) -> list[dict]:
    """
    查一个会话里的全部消息，按时间从早到晚。

    聊天界面要"先说的在上面"，所以是 ASC（升序）。
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM messages
             WHERE session_id = ?
             ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_history_for_ai(session_id: int, max_messages: int = 20) -> list[dict]:
    """
    取出最近的 N 条消息，整理成 DeepSeek 要的格式。

    返回：[{"role": "user", "content": "..."},
           {"role": "assistant", "content": "..."}, ...]

    为什么要限制条数？
    因为发给 AI 的内容越长，花钱越多、速度越慢，
    而且超过模型的上下文长度还会直接报错。
    只带最近 20 条（约 10 轮对话）通常就够 AI 记住上下文了。
    """
    conn = get_connection()
    try:
        # 先按 id 倒序取最近的 N 条……
        rows = conn.execute(
            """
            SELECT role, content FROM messages
             WHERE session_id = ?
             ORDER BY id DESC
             LIMIT ?
            """,
            (session_id, max_messages),
        ).fetchall()
    finally:
        conn.close()

    # ……再翻转回"从早到晚"的顺序，AI 才能看懂对话的先后
    history = [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows)
    ]

    # 小细节：如果截断后第一条正好是 AI 说的话，对话就变成"AI 先开口"，
    # 有点奇怪。去掉它，保证历史一定从用户的话开始。
    while history and history[0]["role"] != "user":
        history.pop(0)

    return history


def count_messages(session_id: int) -> int:
    """数一个会话里有多少条消息。"""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------
# 6. reports 表的操作（暂时没变，留给下一步做学习报告）
# ---------------------------------------------------------------
def save_report(
    student_id: int,
    mastery_data: str | None = None,
    error_stats: str | None = None,
) -> dict:
    """保存一份学习报告（mastery_data / error_stats 传 JSON 字符串）。"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO reports (student_id, mastery_data, error_stats) "
            "VALUES (?, ?, ?)",
            (student_id, mastery_data, error_stats),
        )
        conn.commit()
        new_id = cursor.lastrowid
    finally:
        conn.close()

    return get_report(new_id)


def get_report(report_id: int) -> dict | None:
    """按 id 查一份学习报告。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()
