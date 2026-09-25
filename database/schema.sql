-- ============================================================
-- 智愈错题 —— SQLite 数据库表结构（v0.5 多轮对话版）
--
-- 【重要变更】
--   旧版：students → dialogues（一条记录 = 一问一答）
--   新版：students → sessions（会话） → messages（消息）
--
--   为什么要改？
--   旧版一次提交就是一问一答，存不进"第二轮追问"。
--   新版像微信一样：一个会话(session)里有很多条消息(message)，
--   这样才能把历史记录发给 AI，让它记得之前聊过什么。
--
-- 【旧数据怎么办？】
--   不要删！运行迁移脚本，会自动把旧数据搬过来：
--       python database/migrate.py
--   详见 README 的「数据库升级」一节。
--
-- 【建表命令】
--   python database/init_db.py
--
-- 所有语句都带 IF NOT EXISTS，可以反复运行。
-- ============================================================

-- 打开外键约束（让 SQLite 真的检查 session_id 是否存在）
PRAGMA foreign_keys = ON;


-- ------------------------------------------------------------
-- 1. students —— 学生信息表（没变）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS students (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
                       DEFAULT (datetime('now', 'localtime'))
);


-- ------------------------------------------------------------
-- 2. sessions —— 会话表
--
--    一个会话 = 聊天界面里的一个"对话窗口"，
--    就像一个微信聊天窗口，里面可以有很多条消息。
--
--    is_pinned：是否置顶。0 = 普通，1 = 置顶。
--    SQLite 没有真正的布尔类型，所以用整数 0/1 表示，
--    再用 CHECK 约束保证这一列只能是 0 或 1。
--
--    ⚠️ 如果这个字段是你后来才加的，光改这里没用！
--       CREATE TABLE IF NOT EXISTS 只会在"表不存在"时建表，
--       对已经建好的表加字段它不管。
--       但本项目在 backend/db.py 的 init_db() 里做了自动检测，
--       启动服务时会自动补上这一列（用 ALTER TABLE，不动原有数据）。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,                   -- 外键：属于哪个学生
    title      TEXT    NOT NULL DEFAULT '新会话',  -- 会话标题
    is_pinned  INTEGER NOT NULL DEFAULT 0          -- 是否置顶：0=普通 1=置顶
                       CHECK (is_pinned IN (0, 1)),
    status     TEXT    NOT NULL DEFAULT 'diagnosing'
                       -- 会话当前的教学阶段（状态机）：
                       --   diagnosing  首次诊断，还没诊断过
                       --   guiding     正在一步步引导追问
                       --   solved      学生已经做对了
                       --   practicing  正在做变式练习题
                       CHECK (status IN ('diagnosing', 'guiding',
                                         'solved', 'practicing')),
    created_at TEXT    NOT NULL
                       DEFAULT (datetime('now', 'localtime')),

    -- 删掉学生时，他的会话也一起删掉
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);


-- ------------------------------------------------------------
-- 3. messages —— 消息表（由旧的 dialogues 表演变而来）
--
--    role 只有两种取值：
--      'user'      —— 学生说的话（错题、追问）
--      'assistant' —— AI 导师的回复
--
--    ⚠ knowledge_point 和 error_type 是"额外加的"两列。
--      你要求的字段是 (id, session_id, role, content, created_at)，
--      但如果没有这两列，AI 诊断出的知识点和错因就没地方放了，
--      后面的学习报告（reports 表）也就没法统计。
--      所以它们只在这条消息是 AI 回复、且分析出结果时才有值，
--      其他情况是 NULL。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL,              -- 外键：属于哪个会话
    role            TEXT    NOT NULL
                            CHECK (role IN ('user', 'assistant')),
    content         TEXT    NOT NULL,              -- 消息正文
    knowledge_point TEXT,                          -- 知识点（只有 AI 回复可能有）
    error_type      TEXT,                          -- 错因（只有 AI 回复可能有）
    error_category  TEXT,                          -- 可以为空（和 error_type 一致）
                            -- ★ 错因的"固定分类"（7 选 1）：
                            --   计算失误 / 概念混淆 / 审题不清 / 步骤遗漏 /
                            --   公式记错 / 逻辑推理错误 / 其他
                            --   学习报告只统计这一列，饼图才干净。
                            --   上面的 error_type 则存详细的长句子分析。
    created_at      TEXT    NOT NULL
                            DEFAULT (datetime('now', 'localtime')),

    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);


-- ------------------------------------------------------------
-- 4. reports —— 学习报告表（没变，还是挂在学生身上）
--
--    mastery_data 和 error_stats 存的是 JSON 字符串。
--    SQLite 没有"数组/字典"类型，所以把复杂结构转成 JSON 文本存。
--
--    mastery_data 例子：{"函数": 0.8, "三角函数": 0.45}
--    error_stats  例子：{"计算失误": 5, "概念不清": 3}
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id   INTEGER NOT NULL,
    mastery_data TEXT,                              -- 知识点掌握度（JSON 文本）
    error_stats  TEXT,                              -- 错误类型统计（JSON 文本）
    created_at   TEXT    NOT NULL
                         DEFAULT (datetime('now', 'localtime')),

    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
);


-- ------------------------------------------------------------
-- 5. 索引 —— 相当于给书本加目录，查的时候不用一页页翻
--
--    现在最常做的查询是：
--      "按学生查他的所有会话"   -> idx_sessions_student
--      "按会话查它的所有消息"   -> idx_messages_session
-- ------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_sessions_student ON sessions(student_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_reports_student  ON reports(student_id);
