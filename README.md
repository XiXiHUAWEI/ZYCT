# 智愈错题 🎓

基于 AI 的错题诊断与个性化学习网站

> **当前版本：v0.5（多轮对话 + 多会话管理）**

---

## ⚠️ 从旧版本升级上来的？先看这里

如果你之前跑过 v0.4 或更早的版本，数据库里会有旧的 `dialogues` 表。
新版用的是 `sessions` + `messages`，**必须先跑一次迁移脚本**：

```powershell
cd 你的目录
python database/migrate.py
```

这个脚本很安全，会做三件事：

1. 先把整个数据库文件**备份**到 `database/backup/`
2. 旧表 `dialogues` **改名**为 `dialogues_backup_时间戳`（是改名，不是删除，数据还在）
3. 把旧数据搬进新表：**每一条旧记录 → 1 个会话 + 2 条消息**

跑完之后你会看到：

```
发现旧表 dialogues，共有 3 条记录。
已备份数据库 -> \database\backup\zhixue_backup_.db
迁移完成：3 条旧记录 -> 3 个会话
旧表已改名为：dialogues_backup_20260918_190916（数据还在，确认没问题后可以自己删）
```

如果**没有跑迁移就直接启动后端**，启动日志里会有醒目提醒：

```
[智愈错题] ! 检测到旧版的 dialogues 表！
[智愈错题]   请先停止服务，运行迁移脚本（会自动备份，数据不会丢）
```

> 如果你是全新开始（数据库里没有 `dialogues` 表），**完全不用管这一节**，
> 直接往下看「如何启动」即可。

---

## 一、项目目录结构

```
智愈错题/
├── backend/                 # 后端（Python + FastAPI）
│   ├── main.py              # 接口层：接收 HTTP 请求
│   ├── db.py                # 数据层：所有读写数据库的代码
│   ├── ai_service.py        # ★ AI 层：调用 DeepSeek，含核心提示词
│   └── requirements.txt     # 需要安装的 Python 库
├── frontend/                # 前端（HTML + Bootstrap + 原生 JS）
│   ├── index.html           # 聊天界面：左侧会话栏 + 右侧聊天窗
│   ├── css/style.css        # 自定义样式（气泡、打字动画等）
│   └── js/app.js            # 会话管理、发消息、渲染聊天记录
├── database/                # 数据库
│   ├── schema.sql           # ★ 表结构设计（只写 SQL）
│   ├── init_db.py           # ★ 建表脚本（全新开始用这个）
│   ├── migrate.py           # ★ 升级脚本（从旧版升上来用这个）
│   ├── backup/              # 迁移前的自动备份（自动生成）
│   └── zhixue.db            # SQLite 数据库文件（自动生成）
├── .env                     # ★ 你的 API Key（自己创建，已被 git 忽略）
├── .env.example             # ★ 环境变量填写模板
├── test_api.py              # 接口测试脚本（不需要 AI）
├── .gitignore
└── README.md
```

---

## 二、如何启动（两步）

### 第 1 步：安装依赖（只做一次）

```powershell
cd 你的目录\backend
pip install -r requirements.txt
```

> 下载慢就加国内镜像：
> ```powershell
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

### 第 2 步：启动后端

```powershell
cd 你的目录\backend
python -m uvicorn main:app --reload
```

看到下面这行就成功了：

```
[智愈错题] 数据库已就绪：你的目录database\zhixue.db
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

**不要关闭这个终端窗口。** 想停止服务，按 `Ctrl + C`。

> ⚠️ 一定要先 `cd backend`。因为 `main.py` 要 `import db`，
> 而 `db.py` 就在 backend 文件夹里。

---

## 三、改了代码，`--reload` 会自动生效吗？

**后端 Python 代码：会。** 你保存 `main.py` 或 `db.py` 后，终端会自动打印：

```
WATCHFILES.FILE_CHANGED - main.py
INFO:     Reloading...
```

**但是有 3 个坑要注意：**

| 情况 | 需要重启后端吗？ | 你要做什么 |
| --- | --- | --- |
| 改 `main.py` / `db.py` 等 `.py` 文件 | ❌ 不用，自动重启 | 等终端打印 `Reloading...` |
| **改 `frontend/` 里的 HTML / CSS / JS** | **❌ 完全不用** | **只要在浏览器按 `F5` 刷新** |
| 改 `database/schema.sql` | ✅ 要 | `--reload` 只盯着 `.py`，得按 `Ctrl+C` 再重新启动 |

> 💡 **划重点**：改前端文件（`index.html`、`app.js`、`style.css`）**永远不需要重启后端**。
> 因为后端只是把这些文件"原样发"给浏览器，文件内容变了它照发就行。
> 你只要在浏览器按 `F5` 刷新，新代码就生效了。
>
> 如果刷新了还是旧的，那是浏览器缓存。按 `Ctrl + F5` 强制刷新即可。
>
> ⚠️ **反过来说**：如果你改了 `app.js` 却没按 `F5`，页面上跑的还是旧代码——
> 很多同学会在这里怀疑自己代码写错了，其实是没刷新。

**还有一个最容易踩的坑：**

`schema.sql` 里写的是 `CREATE TABLE IF NOT EXISTS`，意思是"表已存在就跳过"。
所以你**给已有的表加字段**时（比如给 `students` 加个 `grade` 列），
重新运行只会跳过，字段根本加不上去！

解决办法（二选一）：
- **推荐（数据不要了）**：删掉 `database\zhixue.db`，重启服务，让它重新建表。
- **保留数据**：在 `schema.sql` 后面加一条 `ALTER TABLE students ADD COLUMN grade TEXT;`，重启服务执行一次，然后把这行删掉。

**另外注意**：`--reload` 是重启整个服务，正在处理的请求会被中断。
自己开发时无所谓，比赛演示前记得把 `--reload` 去掉：

```powershell
python -m uvicorn main:app
```

---

## 四、聊天界面怎么用

后端启动后，浏览器打开 **http://127.0.0.1:8000/**（公网IP暂未考虑）

界面左边是会话列表，右边是聊天窗口：

```
┌──────────────────────┬─────────────────────────────────────┐
│ 学生 ID  [ 1 ]       │  解方程 2x + 5 = 13…      [🧪 日志] │
│                      ├─────────────────────────────────────┤
│ [ ＋ 新建会话 ]       │                              ┌────┐ │
│                      │                              │错题│ │
│ ▎解方程 2x + 5 = 13… │                              └────┘ │
│   03-01 10:00 · 2 条 │  ┌────┐                             │
│                      │  │ AI │ 我们先不急着对答案…          │
│   sin30 到底等于…   │  └────┘ 📘一元一次方程 🔍计算失误    │
│   03-01 10:05 · 1 条 │                                      │
│                      │                              ┌────┐ │
│   因式分解 x²-5x+6… │                              │追问│ │
│   03-02 09:00 · 2 条 │                              └────┘ │
│                      ├─────────────────────────────────────┤
│                      │ ┌───────────────────────┐ ┌──────┐  │
│                      │ │ 把错题粘贴在这里…      │ │ 发送 │  │
│                      │ └───────────────────────┘ └──────┘  │
└──────────────────────┴─────────────────────────────────────┘
```

**完整操作流程：**

1. 点左上角的 **＋ 新建会话** —— 这就是开了一个新的聊天窗口。
2. 在下面的输入框里粘贴错题，比如：
   > 解方程 2x + 5 = 13，我算出来 x = 3，但正确答案是 4
3. 按 **发送**（或 `Ctrl + Enter`）。
4. 你的话立刻出现在右边（蓝色气泡），左边出现三个跳动的点表示 AI 在想。
5. 等 10-20 秒，AI 的引导回复出现在左边。
6. **继续追问！** 比如输入「我还是不太明白，为什么移项要变号？」
   —— AI 记得你们刚才聊的是哪道题，会接着往下引导。
7. 想聊新题目？点 **＋ 新建会话**，开一个新的窗口，互不干扰。
8. 鼠标移到侧边栏某个会话上，右边会出现 `×`，点它可以删除。

**界面上各种提示的含义：**

| 提示 | 颜色 | 原因 |
| --- | --- | --- |
| 请新建或选择一个会话 | 灰 | 还没选会话，输入框是禁用的 |
| 这是一个新会话，把错题发进来吧 | 灰 | 会话建好了但还没说话 |
| AI 导师正在思考…（三个跳动的点） | 灰 | 正在等 DeepSeek 回复，正常 |
| 消息已保存，但 AI 没有回复：xxx | 🔴 红 | AI 那边出错了，但你的消息没丢 |
| 发送失败：xxx | 🔴 红 | 后端返回了错误 |
| 网络错误：连不上后端 | 🔴 红 | 后端那个终端窗口关了 |

### 多轮对话是怎么实现的？

**这是整个项目最核心的原理，答辩时一定会被问到。**

DeepSeek 的 API **本身是无状态的** —— 它不记得你上一句说了什么。
所谓「AI 记得我们聊过什么」，其实是**每次请求都把之前的聊天记录重新发一遍**。

我们在 `backend/main.py` 里是这样做的：

```python
# 1. 先把学生说的话存进 messages 表
user_message = db.save_message(session_id, "user", user_input)

# 2. 把这个会话的历史消息全部取出来
history = db.get_history_for_ai(session_id)

# 3. 带着历史一起发给 DeepSeek   ← 关键的一步
result = await ai_service.generate_reply(history)
```

在 `ai_service.py` 里，最终发给 DeepSeek 的结构是这样的：

```
[
  {"role": "system",    "content": "你是一位苏格拉底式初中数学导师……"},
  {"role": "user",      "content": "解方程 2x + 5 = 13，我算出来 x = 3……"},   ← 第 1 轮
  {"role": "assistant", "content": "我们先不急着对答案。你觉得……"},          ← 第 1 轮 AI 回复
  {"role": "user",      "content": "我还是不太明白，为什么移项要变号？"}        ← 第 2 轮
]
```

所以在聊天记录里，**每发一条消息，带的历史就多两条**：

| 第几轮 | 带给 AI 的消息条数 |
| --- | --- |
| 第 1 轮 | 2 条（system + 你的错题）|
| 第 2 轮 | 4 条（多了上一轮的问答）|
| 第 3 轮 | 6 条（再多了第 2 轮的问答）|

> ⚠️ **为什么不能无限带下去？**
> 因为发给 AI 的内容越长，花钱越多、速度越慢，
> 而且超过模型的上下文长度会直接报错。
> 所以 `db.get_history_for_ai()` 默认只带**最近 20 条**（约 10 轮对话）。
> 这个数字可以在 `.env` 里用 `AI_MAX_HISTORY` 调整。

还有一个容易被忽略的小细节：截断历史时，如果第一条正好是 AI 说的话，
对话就变成「AI 先开口」了，很奇怪。所以 `get_history_for_ai()` 会自动
把开头的 assistant 消息去掉，保证历史一定从用户的话开始。


---

## 五、配置 DeepSeek API Key

### 第 1 步：申请一个 Key

打开 https://platform.deepseek.com/api_keys ，注册登录后点
「创建 API Key」，会得到一串 `sk-` 开头的字符。

> ⚠️ **这串字符只会完整显示一次**，关掉页面就再也看不到了，请立刻复制下来。
> 它就像你的银行卡密码，**绝对不要**发到群里、写进代码、或者提交到 GitHub。

### 第 2 步：新建 `.env` 文件

在**项目根目录**（`你的目录`，和 `README.md` 同一层）新建一个文件，文件名就叫 `.env`
（注意开头有个点，**没有** `.txt` 之类的后缀）。

最简单的做法：把现成的 `.env.example` 复制一份，改名为 `.env`，然后编辑它：

```powershell
cd 你的目录
Copy-Item .env.example .env
notepad .env
```

`.env` 的内容长这样：

```ini
DEEPSEEK_API_KEY=sk-把这里换成你自己的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_TIMEOUT=60
```

| 变量名 | 必填？ | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | ✅ **必填** | 你的密钥，`sk-` 开头 |
| `DEEPSEEK_BASE_URL` | 否 | API 地址，一般不用改 |
| `DEEPSEEK_MODEL` | 否 | 模型名。报错说"模型不存在"时改这里 |
| `DEEPSEEK_TIMEOUT` | 否 | 超时秒数，默认 60 |

### 第 3 步：安装新依赖

这一步**必须做**，否则后端启动会报 `No module named 'httpx'`：

```powershell
cd 你的目录\backend
pip install -r requirements.txt
```

这次新增了两个库：

| 库 | 作用 |
| --- | --- |
| `httpx` | 用来发 HTTP 请求调用 DeepSeek API（异步的，不会卡住其他请求） |
| **`python-dotenv`** | **用来读取 `.env` 文件**，这就是"不把 Key 写死在代码里"的关键 |

### 第 4 步：重启后端

改了 `.env` **必须重启后端**才会生效（`--reload` 只监视 `.py` 文件，不监视 `.env`）。

按 `Ctrl+C` 停掉，再重新运行：

```powershell
cd 你的目录\backend
python -m uvicorn main:app --reload
```

启动日志里出现下面这行就说明配好了：

```
[智愈错题] AI 已配置，模型：deepseek-flash
```

如果看到的是警告，说明 Key 没读到，请检查 `.env` 是不是放在 `你的目录\` 根目录：

```
[智愈错题] ⚠ 未检测到 DEEPSEEK_API_KEY，AI 诊断功能将不可用
```

### 🔒 为什么 Key 必须放在后端？

这是**比赛答辩时很可能被问到**的问题，一定要理解：

```
❌ 错误做法：前端直接调 DeepSeek
   浏览器 --(带着 Key)--> DeepSeek
   问题：前端 JS 代码在浏览器里按 F12 就能看到，
        任何人打开你的网页都能偷走 Key，然后拿去刷你的钱。

✅ 正确做法：后端中转
   浏览器 --> 你的后端 --(带着 Key)--> DeepSeek
   Key 只存在服务器上，永远不会发给浏览器。
```

所以：
- `frontend/` 里**绝对不允许**出现 `sk-` 开头的字符串
- 前端只调用我们自己的后端 `/api/submit_error`
- Key 由后端从 `.env` 读取，用完就留在后端

另外，`.env` 已经被写进 `.gitignore`，所以 `git commit` 时不会被上传。
而 `.env.example`（只有占位符、没有真 Key）是用来提交的，方便队友知道该填哪些变量。

> 🔎 **自查小技巧**：在项目根目录搜索一下 `sk-`，如果除了 `.env` 之外还有别的地方出现，就说明泄漏了。

### 核心提示词是怎么设计的？

提示词（System Prompt）写在 `backend/ai_service.py` 里，是整个项目的灵魂。
它规定了 AI 必须遵守的四件事：

**① 教学方式 —— 苏格拉底式，绝对不给答案**

```
1. 绝对不能直接给出正确答案，也不能把完整解题过程写出来。
2. 用提问代替讲解。第一轮只问 1 到 2 个最关键的问题。
3. 提问要有梯度：先问"你当时是怎么想的"，再问"这一步的依据是什么"，
   最后才指向错误点。
```

为什么要写得这么死？因为 AI 的**默认习惯就是直接给答案**——
你只要问一道题，它立刻把完整解法倒给你。那样学生就只是抄答案，
完全没有"自己发现错误"的过程，也失去了这个项目的意义。

**② 输出格式 —— 强制 JSON**

```
你必须只输出一个 json 对象，不要输出任何额外解释，
也不要用 markdown 代码块包裹。
```

同时在代码里开启 JSON 模式：

```python
"response_format": {"type": "json_object"},
```

> ⚠️ 注意：DeepSeek 官方文档要求，**开启 JSON 模式时，提示词里必须包含 `json` 字样**
> 并给出格式样例，否则接口会报错。这一点很容易踩坑。

**③ 限定取值范围 —— 让错因可以统计**

```
error_type 必须从下面这几个里挑最贴切的一个：
概念不清 / 计算失误 / 审题不清 / 公式记错 / 思路错误 / 步骤遗漏 / 单位换算错误
```

如果放任 AI 自由发挥，它可能这次说"粗心"，下次说"计算错误"，
下次说"马虎"——**这几个其实是同一个意思，但数据库里会被算成三类**，
后面的统计图表就全乱了。所以必须限定成固定的几个选项。

**④ 让 AI 兼容意外情况**

代码里做了几层"防呆"，因为 AI 并不总是听话：

| 可能出的问题 | 代码怎么处理 |
| --- | --- |
| 用 ` ```json ` 代码块把结果包起来 | `_strip_code_fence()` 自动剥掉 |
| 前后多说了几句废话 | 截取第一个 `{` 到最后一个 `}` 再解析 |
| 用中文字段名（知识点 / 错因） | `_normalize()` 同时认中文和英文的 key |
| 返回空内容（官方说这情况有概率发生） | 抛出明确错误，提示"请再试一次" |
| JSON 被 `max_tokens` 截断 | 把 `max_tokens` 设成 1200，给足空间 |

> 💡 这段代码是答辩时的加分项：说明你不只是"会调 API"，
> 还考虑了 AI 输出**不稳定**这个现实问题，并做了工程上的兜底。

---

## 六、数据库设计

### 四张表的关系

```
students (学生)
   │  id
   ├──────────────< sessions (会话)         一个学生有多个会话
   │                   id                       就像微信里的多个聊天窗口
   │                   └──< messages (消息)   一个会话有多条消息
   │                            id               学生和 AI 说的话
   └──────────────< reports  (学习报告)
```

**1. `students` —— 学生信息表（没变）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键，自动递增 |
| `name` | TEXT | 姓名，不能为空 |
| `created_at` | TEXT | 创建时间 |

**2. `sessions` —— 会话表（新增）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `student_id` | INTEGER | 外键 → `students.id` |
| `title` | TEXT | 会话标题，默认「新会话」 |
| `created_at` | TEXT | 创建时间 |

> 💡 **标题是怎么来的？** 发出这个会话的第一条消息时，
> 后端会截取消息的前 20 个字自动命名，就像 ChatGPT 左侧列表那样。
> 这段逻辑在 `main.py` 的 `make_title()` 函数里。

**3. `messages` —— 消息表（由旧的 `dialogues` 演变而来）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `session_id` | INTEGER | 外键 → `sessions.id` |
| `role` | TEXT | `'user'`（学生）或 `'assistant'`（AI） |
| `content` | TEXT | 消息正文 |
| `knowledge_point` | TEXT | 知识点（**只有 AI 回复才有**） |
| `error_type` | TEXT | 错因（**只有 AI 回复才有**） |
| `created_at` | TEXT | 创建时间 |

> ⚠️ 你要求的字段是 `(id, session_id, role, content, created_at)`，
> 我在这个基础上**多加了两列** `knowledge_point` 和 `error_type`。
>
> **为什么？** 如果没有这两列，AI 诊断出的知识点和错因就没地方存了，
> 下一步做学习报告（`reports` 表）时也没法统计「哪个知识点错得最多」。
> 它们只在这条消息是 AI 回复、且分析出结果时才有值，其他情况是 `NULL`。

`role` 列上有一个 `CHECK` 约束，是数据库层面的把关：

```sql
role TEXT NOT NULL CHECK (role IN ('user', 'assistant'))
```

意思是：想往这一列塞别的值，数据库会直接报错。
就算以后代码写错了，也污染不了数据。

**4. `reports` —— 学习报告表（没变）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键 |
| `student_id` | INTEGER | 外键 → `students.id` |
| `mastery_data` | TEXT | 知识点掌握度，存 **JSON 字符串** |
| `error_stats` | TEXT | 错误类型统计，存 **JSON 字符串** |
| `created_at` | TEXT | 创建时间 |

**为什么复杂数据要存 JSON 字符串？**
因为 SQLite 没有"数组 / 字典"这种类型。所以我们把 Python 字典转成文本存进去：

```python
import json
mastery = {"函数": 0.8, "三角函数": 0.45}
conn.execute("INSERT INTO reports (student_id, mastery_data) VALUES (?, ?)",
             (1, json.dumps(mastery, ensure_ascii=False)))
```

读出来的时候再 `json.loads()` 转回字典。

### 从旧版升级：migrate.py 做了什么

如果你有 v0.4 的旧数据，`migrate.py` 是这么搬的：

```
旧：dialogues 表的一行
    ┌──────────────────────────────────────────────┐
    │ student_id=1                                 │
    │ user_input="解方程 2x + 5 = 13..."           │
    │ ai_response="我们先不急着对答案..."           │
    │ knowledge_point="一元一次方程"                │
    │ error_type="计算失误"                         │
    └──────────────────────────────────────────────┘
                     ↓  变成
新：sessions 表 1 行
    ┌──────────────────────────────────────────────┐
    │ id=1, student_id=1, title="解方程 2x + 5 = 13…"│
    └──────────────────────────────────────────────┘
    messages 表 2 行
    ┌──────────────────────────────────────────────┐
    │ role='user',      content="解方程 2x + 5..."  │
    │ role='assistant', content="我们先不急着...",  │
    │                   knowledge_point="一元一次方程"│
    │                   error_type="计算失误"        │
    └──────────────────────────────────────────────┘
```

**如果旧记录的 `ai_response` 是空的**（当时 AI 调用失败了），
那就只建 1 条 user 消息，不建 assistant 消息 —— 不会伪造数据。

### 为什么把表结构单独放在 `schema.sql`？

因为这样"设计表"和"写代码"就分开了：

- 想加字段 / 改类型 → 只改 `schema.sql`
- `db.py` 和 `main.py` 完全不用动

### 关于建表

**你不用手动建表。** 服务启动时会自动跑一遍 `schema.sql`（在 `main.py` 的 `lifespan` 里）。

当然也可以单独运行：

```powershell
cd 你的目录
python database\init_db.py
```

两种方式效果一样，而且可以**反复运行**，不会删掉已有数据。

> ⚠️ **注意**：`init_db.py` 只管建新表，**不会搬旧数据**。
> 如果你是升级上来的，请用 `migrate.py`。

---

## 七、接口清单

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/hello` | 测试后端是否启动 |
| GET | `/api/ai_status` | 查询 AI 是否已配置（不返回 Key） |
| **POST** | **`/api/new_session`** | **新建会话，返回 session_id** |
| **GET** | **`/api/sessions/{student_id}`** | **获取该学生的所有会话** |
| **DELETE** | **`/api/sessions/{session_id}`** | **删除一个会话（消息一起删）** |
| **GET** | **`/api/messages/{session_id}`** | **获取某会话的全部聊天记录** |
| **POST** | **`/api/chat`** | **发一条消息并拿到 AI 回复（核心）** |
| POST | `/api/students` | 创建学生 |
| GET | `/api/students` | 查看所有学生 |
| POST | `/api/submit_error` | 【旧版兼容】单轮录入错题 |

> ⏱️ `/api/chat` 会**等待 AI 回答**，一般需要 **10-20 秒**才返回。
> 这是正常的，前端在这期间会显示跳动的点和一个计时器。

### `POST /api/new_session`

**请求：**

```json
{ "student_id": 1 }
```

**返回：**

```json
{
  "success": true,
  "message": "会话创建成功",
  "session_id": 2,
  "session": {
    "id": 2,
    "student_id": 1,
    "title": "新会话",
    "created_at": "2025-01-01 12:00:00"
  },
  "student": { "id": 1, "name": "学生1", "created_at": "2025-01-01 11:00:00" },
  "student_created": false
}
```

> 💡 前端最需要的是 `session_id`，后面发消息要用它。

### `GET /api/sessions/{student_id}`

返回会话列表，**最近有消息的排在前面**。
每个会话还附带 `message_count`（消息数）和 `last_message_at`（最后一条消息时间），
侧边栏就用这两个值显示「03-01 10:00 · 2 条」。

```json
{
  "student": { "id": 1, "name": "学生1", "created_at": "..." },
  "count": 2,
  "sessions": [
    {
      "id": 3,
      "student_id": 1,
      "title": "sin30 到底等于 1/2 还是…",
      "created_at": "2025-03-01 10:05:00",
      "message_count": 1,
      "last_message_at": "2025-03-01 10:05:00"
    }
  ]
}
```

### `GET /api/messages/{session_id}`

返回一个会话的全部消息，**按时间从早到晚**（聊天界面要从上往下铺）。

```json
{
  "session": { "id": 3, "student_id": 1, "title": "...", "created_at": "..." },
  "count": 4,
  "messages": [
    {
      "id": 5,
      "session_id": 3,
      "role": "user",
      "content": "解方程 2x + 5 = 13...",
      "knowledge_point": null,
      "error_type": null,
      "created_at": "2025-03-01 10:05:00"
    },
    {
      "id": 6,
      "session_id": 3,
      "role": "assistant",
      "content": "我们先不急着对答案。你觉得……",
      "knowledge_point": "一元一次方程",
      "error_type": "计算失误",
      "created_at": "2025-03-01 10:05:12"
    }
  ]
}
```

### `POST /api/chat`（核心接口）

**请求：**

```json
{
  "student_id": 1,
  "session_id": 3,
  "user_input": "我还是不太明白，为什么移项要变号？"
}
```

**成功返回（200，AI 也回复了）：**

```json
{
  "success": true,
  "ai_success": true,
  "ai_error": null,
  "message": "AI 已回复",
  "session": { "id": 3, "title": "解方程 2x + 5 = 13…", "message_count": 6 },
  "user_message": {
    "id": 7, "role": "user", "content": "我还是不太明白…", "created_at": "..."
  },
  "ai_message": {
    "id": 8,
    "role": "assistant",
    "content": "你问到点子上了。我们用一个简单的例子……",
    "knowledge_point": "一元一次方程",
    "error_type": "计算失误",
    "created_at": "..."
  }
}
```

**AI 失败时的返回（依然是 200）：**

```json
{
  "success": true,
  "ai_success": false,
  "ai_error": "连接 DeepSeek 失败：All connection attempts failed",
  "message": "消息已保存，但 AI 没有回复",
  "user_message": { "id": 9, "role": "user", "content": "...", "created_at": "..." },
  "ai_message": null
}
```

> 💡 **关键设计 1：先保存，再调 AI。**
> 调用 AI 可能失败（没网、Key 过期、超时）。
> 如果先调 AI 再保存，一旦失败，学生辛苦打的字就全丢了。
> 现在这样，**即使 AI 挂了，学生的话也安全地存在数据库里**，
> 前端会插一条红色的系统提示，而不是把消息吞掉。

> 💡 **关键设计 2：会检查会话归属。**
> 如果传的 `session_id` 属于别的学生，直接返回 `403`，防止串会话。

**几种错误返回：**

| 状态码 | 什么时候出现 |
| --- | --- |
| `400` | `user_input` 是空的 / 全是空格；`student_id` 或 `session_id` 小于等于 0 |
| `403` | 这个 `session_id` 不属于传进来的 `student_id` |
| `404` | `session_id` 不存在（比如还没新建会话就发消息）|
| `422` | 传的 JSON 格式不对，比如 `student_id` 传了字符串 `"abc"` |

### 【旧版兼容】`POST /api/submit_error`

v0.4 时代的接口，为了不让旧代码报错而保留。
内部其实做的是「新建一个会话 + 发第一条消息」，返回里同时给了新格式和旧格式的字段。

**新写的代码请直接用 `/api/new_session` + `/api/chat`。**

> 💡 **自动建学生**：`/api/new_session` 和 `/api/submit_error` 里，
> 如果传的 `student_id` 还没有对应的学生，会自动创建一个（名字叫"学生1"）。
> 这样测试时不用先建档。以后接了登录功能可以把这段去掉。

---

## 八、怎么测试接口

### 方法 A：直接用网页（最直观，推荐 ✅）

后端启动后打开 http://127.0.0.1:8000/ ，点「新建会话」，粘贴错题，点发送。
**再追问一句**，就能亲眼看到 AI 记得上文。

这也是比赛演示时最该用的方式。

### 方法 B：跑测试脚本

**先启动后端**，然后**另开一个终端**：

```powershell
cd 你的目录
python test_api.py
```

它会模拟一个学生完整的学习过程，测 11 个场景：

```
新建会话 -> 发错题 -> 追问 -> 再追问 -> 看聊天记录 -> 看会话列表
-> 空消息(400) -> 会话不存在(404) -> 会话不属于该学生(403)
```

并把每一步返回的 JSON 打印出来。不需要装 `requests`。

### 方法 C：浏览器点按钮（Swagger 文档）

后端启动后打开：

```
http://127.0.0.1:8000/docs
```

找到 `/api/chat`，点右边的 **Try it out**，
填入 `student_id`、`session_id` 和 `user_input`，再点 **Execute**。

### 方法 D：PowerShell 命令

```powershell
# 新建会话
$s = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/new_session" `
    -Method Post -Body '{"student_id":1}' -ContentType "application/json"
$sid = $s.session_id
Write-Host "新会话 ID = $sid"

# 发一条消息
$json = "{`"student_id`":1,`"session_id`":$sid,`"user_input`":`"解方程 2x + 5 = 13`"}"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/chat" `
    -Method Post -Body $json -ContentType "application/json; charset=utf-8"
```

### 方法 E：curl.exe

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/new_session" `
    -H "Content-Type: application/json" -d '{\"student_id\":1}'
```

> ⚠️ Windows PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名，必须写 `curl.exe`。
> 而且 JSON 里的双引号转义比较麻烦，所以**更推荐用方法 B 的测试脚本**。

### 怎么确认数据真的存进去了？

```powershell
cd 你的目录
python -c "import sqlite3; c=sqlite3.connect('database/zhixue.db'); c.row_factory=sqlite3.Row; [print(dict(r)) for r in c.execute('SELECT id, session_id, role, content FROM messages ORDER BY id')]"
```

---

## 九、常见问题

### ❓ 启动时看到「检测到旧版的 dialogues 表」

说明你是从 v0.4 升级上来的，还没跑迁移。停掉服务，运行：

```powershell
cd 你的目录
python database/migrate.py
```

详见 README 最上面那一节。

### ❓ 提示「会话 5 不存在，请先新建一个会话」

有两种可能：

1. 前端还没选会话就发消息了 —— 先点「＋ 新建会话」。
2. 你删掉的那个会话正好还开着 —— 刷新一下页面（`F5`）。

### ❓ 迁移后想反悔，怎么恢复原样？

迁移前自动备份在 `database/backup/` 里，直接复制回来改名即可：

```powershell
cd 你的目录\database
Copy-Item backup\zhixue_backup_20260918_190916.db zhixue.db -Force
```

### ❓ 页面显示「连不上后端服务」

后端没启动，或中途关掉了。检查运行 `uvicorn` 的终端窗口还在不在。

### ❓ 页面顶部出现黄色警告「还没有配置 DeepSeek API Key」

`你的目录\.env` 文件不存在，或者里面没填 `DEEPSEEK_API_KEY`。
照着「五、配置 DeepSeek API Key」做一遍，然后**重启后端**。

### ❓ AI 好像不记得我们之前聊过什么

先检查这几点：

1. 是不是在**同一个会话**里追问的？换了会话，AI 当然不知道另一个窗口聊过什么。
2. 聊天记录超过 20 条了吗？超过之后只带最近 20 条，更早的会被忘掉。
   可以在 `.env` 里把 `AI_MAX_HISTORY` 调大（比如 `40`），然后重启后端。
3. 看浏览器 `F12` 控制台里的日志，确认发送时带上了 `session_id`。

### ❓ 提示「AI 调用失败（HTTP 401）」

Key 填错了，或者复制的时候多了空格 / 少了一截。
打开 `.env` 检查 `DEEPSEEK_API_KEY=` 后面那串是不是完整的。

### ❓ 提示「AI 调用失败（HTTP 402）」

DeepSeek 账户余额不足，去 https://platform.deepseek.com 充值。
（新注册账号一般会送一些额度）

### ❓ 提示「模型名 'xxx' 不存在」

官方调整了模型名。去 https://platform.deepseek.com 看看你可用的模型叫什么，
然后改 `.env` 里的 `DEEPSEEK_MODEL`，重启后端。

### ❓ 提示「AI 响应超时」

网络慢，或者 DeepSeek 正忙。可以在 `.env` 里把 `DEEPSEEK_TIMEOUT` 调大，
比如改成 `120`，然后重启后端。

### ❓ `ModuleNotFoundError: No module named 'httpx'`（或 `'dotenv'`）

新依赖没装。回到 `backend` 目录重新装一次：

```powershell
cd 你的目录\backend
pip install -r requirements.txt
```

### ❓ `ModuleNotFoundError: No module named 'db'`

没有先 `cd backend`。请务必：

```powershell
cd 你的目录\backend
python -m uvicorn main:app --reload
```

### ❓ 改了 `.env` 但没生效

`.env` 只在后端**启动时**读一次，而且 `--reload` 不监视 `.env`。
必须按 `Ctrl+C` 停掉后端再重新启动。

### ❓ `pip install` 报 `Permission denied`

你这台电脑的 Python 是微软商店版，系统目录不可写。用虚拟环境：

```powershell
cd 你的目录
python -m venv venv
venv\Scripts\activate
pip install -r backend\requirements.txt
```

以后每次开发前都要先激活（命令行前面会出现 `(venv)`）。

### ❓ 端口 8000 被占用

```powershell
python -m uvicorn main:app --reload --port 8001
```

同时要把 `frontend/js/app.js` 里的 `API_BASE` 改成 `8001`。

### ❓ 想清空所有测试数据

删掉 `database\zhixue.db`，然后重启后端，会自动重新建一个空库。

### ❓ 想清掉迁移留下的旧表

确认新数据都正常之后，可以手动删掉备份表：

```powershell
cd 你的目录
python -c "import sqlite3; c=sqlite3.connect('database/zhixue.db'); c.execute('DROP TABLE dialogues_backup_20260918_190916'); c.commit()"
```

（把表名换成你自己的那个。`database/backup/` 里的文件也可以一起删。）

---

## 十、下一步计划

- [x] 项目骨架 + 前后端连通
- [x] SQLite 表结构 + 错题录入接口
- [x] 前端错题录入界面（表单 + 最近记录列表）
- [x] 接入 DeepSeek：自动识别知识点、判断错因、生成苏格拉底式引导语
- [x] 前端 Loading 动画（Spinner + 计时 + 诊断日志面板）
- [x] 多轮对话：带着历史上下文，AI 能连续追问
- [x] 多会话管理：新建 / 切换 / 删除会话，聊天界面像微信
- [x] 统计接口：根据 `messages` 里的知识点生成 `reports` 学习报告
- [x] 用 ECharts 把掌握度画成雷达图
- [x] 用户登录：让学生用自己的账号，而不是手动填学生 ID
- [x] 支持拍照上传错题（OCR 识别成文字）
- [ ] **下一步计划正在计划**
## 十一、联系方式
欢迎反馈问题:邮箱 XiXiHUAWEI19870915@gmail.com
                XiXiHUAWEI19870915@outlook.com


**该项目隶属于江苏省天一中学宛山湖分校高一19班研发团队**
