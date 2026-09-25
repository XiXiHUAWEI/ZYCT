"""
智愈错题 —— 后端主程序（FastAPI）v0.5 多轮对话版

【启动方式】
一定要先进入 backend 目录（因为要用到同目录的 db.py 和 ai_service.py）：

    cd D:\\0\\1\\backend
    python -m uvicorn main:app --reload

【启动后可以访问】
    http://127.0.0.1:8000/            前端聊天界面
    http://127.0.0.1:8000/docs        自动生成的接口文档（可以点按钮直接测）

【接口一览】
    GET    /hello                        测试后端是否启动
    GET    /api/ai_status                查看 AI 是否已配置
    POST   /api/new_session              新建会话
    GET    /api/sessions/{student_id}    某个学生的所有会话
    DELETE /api/sessions/{session_id}    删除一个会话
    POST   /api/sessions/{session_id}/pin 切换会话置顶状态
    GET    /api/messages/{session_id}    某个会话的全部聊天记录
    POST   /api/chat                     发一条消息并拿到 AI 回复（核心）
    POST   /api/submit_error             【旧版兼容】单轮录入错题
    POST   /api/students                 创建学生
    GET    /api/students                 查看所有学生

【关于 AI】
调用 DeepSeek 的代码在 ai_service.py，
API Key 从项目根目录的 .env 文件里读取，不会出现在代码里。
"""

from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import ai_service
import db


# ---------------------------------------------------------------
# ★ 只有这两个阶段允许出现【知识点】【错因】标签。
#
#   diagnosing  首次诊断 —— 第一次看这道错题，当然要写标签
#   practicing  变式练习 —— 做错了要重新诊断，也要写标签
#
#   guiding     引导追问 —— 只该有引导语，不许有标签
#   solved      已解决   —— 只该有鼓励语，不许有标签
#
# 放在这里当成一份"白名单"，main.py 和 ai_service.py 用的是同一套判断。
# ---------------------------------------------------------------
_TAG_ALLOWED_STATES = (db.STATUS_DIAGNOSING, db.STATUS_PRACTICING)


# ---------------------------------------------------------------
# 1. 生命周期函数（lifespan）
#    服务启动时建表、检查 AI 配置；关闭时打印一行日志。
# ---------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    print(f"[智愈错题] 数据库已就绪：{db.DB_PATH}")

    # 检测旧版表：如果用户还没跑迁移脚本，给一个显眼的提醒
    if db.has_legacy_table():
        print("=" * 64)
        print("[智愈错题] ! 检测到旧版的 dialogues 表！")
        print("[智愈错题]   新版本用的是 sessions + messages 表。")
        print("[智愈错题]   请先停止服务，运行迁移脚本（会自动备份，数据不会丢）：")
        print("[智愈错题]       cd D:\\0\\1")
        print("[智愈错题]       python database/migrate.py")
        print("=" * 64)

    if ai_service.is_configured():
        print(f"[智愈错题] AI 已配置，模型：{ai_service.DEEPSEEK_MODEL}")
    else:
        print("[智愈错题] ! 未检测到 DEEPSEEK_API_KEY，AI 诊断功能将不可用")
        print("[智愈错题]   请在项目根目录创建 .env 文件（可参考 .env.example）")

    yield
    print("[智愈错题] 服务已关闭")


# ---------------------------------------------------------------
# 2. 创建 FastAPI 应用
# ---------------------------------------------------------------
app = FastAPI(
    title="智愈错题 API",
    description="基于 AI 的错题诊断与个性化学习平台 —— 后端接口（多轮对话版）",
    version="0.5.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------
# 3. 跨域配置
# ---------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===============================================================
# 4. 请求数据模型（Pydantic）
#
#    定义一个类，FastAPI 就会自动：
#      - 校验前端传过来的 JSON 格式对不对
#      - 在 /docs 页面显示每个字段的含义
#      - 格式不对时自动返回 422 错误，不用自己写判断
# ===============================================================

class NewSessionRequest(BaseModel):
    """新建会话时要传的数据。"""

    student_id: int = Field(..., description="学生 ID，必须是整数")
    title: str | None = Field(None, description="可选。不填就叫「新会话」")


class ChatRequest(BaseModel):
    """发消息时要传的数据。"""

    student_id: int = Field(..., description="学生 ID")
    session_id: int = Field(..., description="会话 ID（从 /api/new_session 拿到的）")
    user_input: str = Field(..., description="学生说的话")


class ErrorSubmit(BaseModel):
    """【旧版兼容】录入错题时传的数据。"""

    student_id: int = Field(..., description="学生 ID，必须是整数")
    error_text: str = Field(..., description="错题内容")


class BatchDeleteRequest(BaseModel):
    """批量删除会话时传的数据。"""

    session_ids: list[int] = Field(
        ...,
        description="要删除的会话 ID 列表，例如 [1, 2, 3]",
    )


class VariantRequest(BaseModel):
    """生成变式练习题时传的数据。"""

    session_id: int = Field(..., description="会话 ID（变式题会插到这个会话里）")
    knowledge_point: str = Field(..., description="要考查的知识点，比如「一元一次方程」")


class OcrRequest(BaseModel):
    """上传错题图片做 OCR 时传的数据。"""

    image_base64: str = Field(
        ...,
        description="图片的 base64 字符串（不含 data:image/xxx;base64, 前缀）",
    )
    mime_type: str = Field(
        "image/jpeg",
        description="图片类型：image/jpeg / image/png / image/gif / image/webp",
    )


class StudentCreate(BaseModel):
    """创建学生时传的数据。"""

    name: str = Field(..., description="学生姓名")
    student_id: int | None = Field(
        None,
        description="可选。想手动指定 ID 就填，不填则由数据库自动分配",
    )


# ===============================================================
# 5. 内部小工具
# ===============================================================

def make_title(text: str, limit: int = 20) -> str:
    """
    从第一条消息里截一段，当作会话标题。

    这就是为什么 ChatGPT 的左侧列表能显示出聊天主题 —— 同一个套路。
    """
    # split() 会把换行、连续空格都切开，join 再拼成一行
    one_line = " ".join(text.split())
    if not one_line:
        return "新会话"
    if len(one_line) <= limit:
        return one_line
    return one_line[:limit] + "…"


async def run_chat_turn(session: dict, user_input: str) -> dict:
    """
    执行"一轮对话"：存学生消息 → 带历史调 AI → 存 AI 回复。

    /api/chat 和旧版的 /api/submit_error 都调用它，
    这样逻辑只写一遍。
    """
    session_id = session["id"]

    # ---- 第 1 步：先把学生说的话存下来 ----
    # 同样遵循"先保存再调 AI"的原则：
    # 万一 AI 挂了，学生打的字也不会丢。
    #
    # 这里要挡一下 IntegrityError：
    # 极端情况下（比如刚检查完会话，另一个请求立刻把它删了），
    # 外键约束会直接抛异常变成 HTTP 500。
    # 捕获它，改成一句看得懂的 404。
    try:
        user_message = db.save_message(session_id, "user", user_input)
    except sqlite3.IntegrityError as exc:
        # ★ 注意：IntegrityError 不一定就是"会话被删了"！
        #   也可能是字段约束问题（比如往 NOT NULL 列塞了 None）。
        #   之前这里不分青红皂白就报"会话已被删除"，
        #   把真正的 bug 藏了起来，害得排查了半天。
        #   所以现在：先确认会话是不是真的没了，再决定怎么报。
        if db.get_session(session_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"会话 {session_id} 已被删除，请重新新建一个会话",
            )
        # 会话还在 -> 是别的原因，如实报出来，别再冤枉会话了
        ai_service.log_error(f"[智愈错题] 保存消息失败（会话 #{session_id}）：{exc}")
        raise HTTPException(
            status_code=500,
            detail=f"保存消息到数据库时出错：{exc}",
        )

    # ---- 第 2 步：如果是这个会话的第一条消息，用它给会话命名 ----
    if db.count_messages(session_id) == 1:
        db.update_session_title(session_id, make_title(user_input))

    # ---- 第 3 步：取出历史（包含刚存的这一条）----
    history = db.get_history_for_ai(session_id)

    # ---- 第 4 步：调用 AI ----
    # ---- 第 3.5 步：看看这个会话现在处于哪个教学阶段 ----
    # AI 的提示词会随状态变化：首次诊断要输出标签，后续引导不要标签
    current_status = session.get("status") or db.STATUS_DIAGNOSING

    # ---- 第 4 步：调用 AI ----
    # 这几个变量必须【先初始化】。
    # 因为下面 try 里如果 AI 调用失败，赋值语句根本轮不到执行，
    # 最后拼返回字典时就会用到未定义的变量，直接崩成 500。
    ai_success = False
    ai_error = None
    ai_error_code = None
    ai_message = None
    knowledge_point = None
    error_type = None
    error_category = None
    new_status = current_status

    # ★ 每次请求都打印"当前状态"，方便你核对状态机走得对不对
    #   这里先算一次"能不能结课"，下面的日志和后面的判断用的是同一个函数，
    #   保证你看到的就是实际生效的结论。
    will_close = ai_service.looks_like_student_understood(user_input, current_status)

    print("")
    print("╔" + "═" * 58 + "╗")
    print(f"║ [状态机] 会话 #{session_id}  收到学生消息")
    print(f"║ [状态机] 当前状态　　：{current_status}"
          f"（{ai_service.STATUS_CN.get(current_status, '未知')}）")
    print(f"║ [状态机] 本轮允许标签：{current_status in _TAG_ALLOWED_STATES}"
          f"　（只有首次诊断/变式练习才允许）")
    print(f"║ [状态机] 学生原话　　：{user_input[:40]!r}")
    print(f"║ [状态机] 判定可结课？：{will_close}"
          f"　（否定词优先；'答案是'这类答案信号只在引导中/变式练习才认）")
    print("╚" + "═" * 58 + "╝")

    try:
        result = await ai_service.generate_reply(history, status=current_status)

        # ★ 把完整的提取结果打印出来，方便核对有没有被截断
        print("[智愈错题] ===== AI 提取结果 =====")
        print(f'[智愈错题]   知识点：{result["knowledge_point"]!r}  （{len(result["knowledge_point"])} 字）')
        print(f'[智愈错题]   错因　：{result["error_type"]!r}  （{len(result["error_type"])} 字）')
        print(f'[智愈错题]   状态　：{result.get("status")!r}  （AI 写了标签吗：{result.get("has_tags")}）')
        print(f'[智愈错题]   引导语：{result["response_text"][:60]!r}...  （共 {len(result["response_text"])} 字）')
        print("[智愈错题] ========================")

        # * 根据 AI 写的【状态】决定会话接下来进入哪个阶段
        new_status = ai_service.map_status_text(
            result.get("status"), fallback=current_status
        )

        # ===========================================================
        # ★★★ 兜底一：学生明确说"我懂了"，后端强制结课 ★★★
        #
        # 提示词再怎么强调，大模型也只是"大概率听话"。
        # 你要录视频，不能赌它这一轮心情好不好。
        # 所以这里后端自己留一票否决权：只要学生说了"我懂了/明白了"，
        # 或者（已经在引导中）抛出了一个答案，一律强制结课。
        #
        # 注意：这里【不用】"连续多轮没有新错题"这种判断。
        #   因为学生卡住、正在思考的时候，本来就好几轮没有新错题，
        #   按那个规则会把最需要帮助的学生踢出课堂。
        # ===========================================================
        force_solved = will_close and current_status != db.STATUS_SOLVED

        # ===========================================================
        # ★★★ 兜底二：硬性截断 ★★★
        #
        # 就算 AI 乖乖写了【状态】已解决，它也常常"意犹未尽"，
        # 在标记后面再甩一道新题：
        #     【引导语】太棒了，你完全掌握了。
        #     【状态】已解决
        #     如果把题目改成 g(x)=ln(-x²+2x)，你会怎么求单调区间呢？
        # 这段尾巴必须砍掉，否则气泡里还有问号，学生以为课没上完。
        #
        # 这里【不依赖 force_solved】—— 只要 AI 自己说了"已解决"，
        # 就说明它认为课上完了，那它后面写的东西就是不该有的，一律砍。
        # ===========================================================
        truncated, did_truncate = ai_service.cut_after_solved_marker(
            result["response_text"]
        )
        if did_truncate:
            ai_service.log_ok(
                "[截断] ★ AI 在【状态】已解决后面还写了内容，已被后端砍掉"
            )
            print(f"[截断]   砍掉的部分：{result['response_text'][len(truncated):][:80]!r}")
            result["response_text"] = truncated
            # AI 自己都说已解决了，状态就按已解决算
            force_solved = True

        # ===========================================================
        # ★★★ 兜底三：结课轮次一律不留标签、不留问号 ★★★
        # ===========================================================
        if force_solved:
            ai_service.log_ok("[结课] ★ 判定可以结课 -> 后端强制结课")
            if new_status != db.STATUS_SOLVED:
                ai_service.log_ok(
                    f"[结课] AI 本来想进入 {new_status}，已被后端改写为 solved"
                )
            new_status = db.STATUS_SOLVED
            # 把 AI 那些还在追问的句子删掉，只留鼓励
            fixed = ai_service.force_close_text(result["response_text"])
            if fixed != result["response_text"]:
                ai_service.log_ok("[结课] AI 回复里的追问句已被后端清除")
                print(f"[结课]   清除前：{result['response_text'][:80]!r}")
                print(f"[结课]   清除后：{fixed[:80]!r}")
            result["response_text"] = fixed

        # ===========================================================
        # ★★★ 兜底二：不该有标签的轮次，后端直接丢掉标签 ★★★
        #
        # 你测试时遇到的"引导轮次却冒出【知识点】【错因】"就是这里挡住的。
        # 只有"首次诊断"和"变式练习"两个阶段允许标签；
        # 引导追问 / 已解决这两类轮次，AI 就算写了标签也一律丢弃，
        # 既不存进数据库，也不会出现在返回给前端的 JSON 里。
        # ===========================================================
        is_closing_turn = new_status == db.STATUS_SOLVED
        allow_tags = (current_status in _TAG_ALLOWED_STATES) and not is_closing_turn

        if result.get("has_tags") and not allow_tags:
            ai_service.log_error(
                f"[标签] ⚠ AI 在「{ai_service.STATUS_CN.get(current_status, current_status)}」"
                f"轮次里违规写了标签，已被后端丢弃："
                f"知识点={result['knowledge_point']!r} 错因={result['error_type']!r}"
            )

        # * 只有在 AI 真的写了标签、并且本轮允许标签时，才保存标签。
        #   引导轮次 AI 是不写标签的；如果把兜底的"待补充"也存进去，
        #   前端就会冒出一个假标签，界面又乱了。
        if result.get("has_tags") and allow_tags:
            knowledge_point = result["knowledge_point"]
            error_type = result["error_type"]
            error_category = result["error_category"]

        # ★ 结课轮次一律不带标签（前端靠这个保证已解决的气泡是干净的）
        if is_closing_turn:
            knowledge_point = None
            error_type = None
            error_category = None

        # ★ 结课状态检查 —— 你录视频时盯这一行就够了
        print(
            f"[状态机] >>> 本轮结束状态：{new_status}"
            f"（{ai_service.STATUS_CN.get(new_status, new_status)}）"
            f"　|　是否处于结课状态：{is_closing_turn}"
            f"　|　本轮带标签：{allow_tags and result.get('has_tags')}"
            f"　|　是否后端强制：{force_solved}"
        )
        print(
            f"[状态机] >>> 前端将收到 is_solved = {is_closing_turn}"
            f"　->　{'显示「生成同类练习题」按钮' if is_closing_turn else '不显示按钮'}"
        )

        # 同样挡一下：等 AI 的十几秒里，会话有可能被删掉了
        try:
            ai_message = db.save_message(
                session_id,
                role="assistant",
                content=result["response_text"],
                knowledge_point=knowledge_point,
                error_type=error_type,
                error_category=error_category,
            )
        except sqlite3.IntegrityError as exc:
            # ★ 注意：IntegrityError 不一定就是"会话被删了"！
            #   也可能是字段约束问题（比如往 NOT NULL 列塞了 None）。
            #   之前这里不分青红皂白就报"会话已被删除"，
            #   把真正的 bug 藏了起来，害得排查了半天。
            #   所以现在：先确认会话是不是真的没了，再决定怎么报。
            if db.get_session(session_id) is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"会话 {session_id} 已被删除，请重新新建一个会话",
                )
            # 会话还在 -> 是别的原因，如实报出来，别再冤枉会话了
            ai_service.log_error(f"[智愈错题] 保存消息失败（会话 #{session_id}）：{exc}")
            raise HTTPException(
                status_code=500,
                detail=f"保存消息到数据库时出错：{exc}",
            )
        ai_success = True

        # * 把新状态写回数据库
        if new_status != current_status:
            db.set_session_status(session_id, new_status)
            print(
                f"[智愈错题] 会话 #{session_id} 状态变化："
                f"{ai_service.STATUS_CN.get(current_status, current_status)}"
                f" -> {ai_service.STATUS_CN.get(new_status, new_status)}"
            )

        print(
            f"[智愈错题] 会话 #{session_id} 共 {db.count_messages(session_id)} 条消息"
            f"（本次带了 {result.get('history_count', 0)} 条历史上下文）："
            f"{knowledge_point or '（本轮无标签）'} / {error_type or '—'}"
        )

    except ai_service.AIServiceError as exc:
        ai_error = str(exc)
        ai_error_code = getattr(exc, "code", "unknown")
        ai_service.log_error(
            f"[智愈错题] 会话 #{session_id} AI 回复失败"
            f"（类型：{ai_error_code}）：{ai_error}"
        )

    return {
        "user_message": user_message,
        "ai_message": ai_message,
        "ai_success": ai_success,
        "ai_error": ai_error,
        "ai_error_code": ai_error_code,
        # * 告诉前端：这道题解出来了没有？
        #   前端靠它决定要不要显示"生成同类练习题"按钮
        "is_solved": new_status == db.STATUS_SOLVED,
        "session_status": new_status,
        "session": db.get_session(session_id),
    }


# ===============================================================
# 6. 接口
# ===============================================================

@app.get("/hello", summary="测试后端是否启动")
def hello():
    return {"message": "智愈错题后端已启动"}


@app.get("/api/ai_status", summary="查看 AI 是否已配置")
def api_ai_status():
    """
    前端用这个接口提前知道 AI 有没有配好，
    免得学生等了 20 秒才发现 Key 没填。
    注意：这里只返回"有没有配置"，绝不返回 Key 本身。
    """
    return {
        "configured": ai_service.is_configured(),
        "model": ai_service.DEEPSEEK_MODEL,
        "base_url": ai_service.DEEPSEEK_BASE_URL,
        "max_history": ai_service.MAX_HISTORY_MESSAGES,
        # 把超时时间也告诉前端，这样界面上"最长等待 xx 秒"的提示
        # 会自动跟着 .env 走，不用手改前端
        "timeout": int(ai_service.DEEPSEEK_TIMEOUT),
    }


# ------------------------- 会话管理 -------------------------

@app.post("/api/new_session", summary="新建会话")
def api_new_session(payload: NewSessionRequest):
    """
    创建一个新会话，返回 session_id。

    前端点「新建会话」按钮时调用它。
    """

    if payload.student_id <= 0:
        raise HTTPException(status_code=400, detail="student_id 必须是正整数")

    title = (payload.title or "").strip() or "新会话"

    # 如果这个学生还不存在，自动建一个，省得测试时还要先建档
    student, student_created = db.get_or_create_student(payload.student_id)

    session = db.create_session(payload.student_id, title)

    return {
        "success": True,
        "message": "会话创建成功",
        "session_id": session["id"],          # 前端最需要这个
        "session": session,
        "student": student,
        "student_created": student_created,
    }


@app.get("/api/sessions/{student_id}", summary="获取某学生的所有会话")
def api_list_sessions(student_id: int):
    """
    返回该学生的会话列表，最近有消息的排在前面。

    前端左侧边栏用它来渲染历史会话列表。
    """

    student = db.get_student(student_id)
    if student is None:
        # 学生还没建过，说明一个会话都没有，返回空列表就好，不算错误
        return {"student": None, "count": 0, "sessions": []}

    sessions = db.list_sessions(student_id)
    return {
        "student": student,
        "count": len(sessions),
        "sessions": sessions,
    }


@app.delete("/api/sessions/{session_id}", summary="删除一个会话（连同聊天记录）")
def api_delete_session(session_id: int):
    """
    彻底删除一个会话。

    数据库层做了两步（在同一个事务里）：
        1. 删掉 messages 里所有属于这个会话的记录
        2. 删掉 sessions 里这个会话本身

    返回值里带上实际删掉了几条消息，方便你确认真的清干净了。
    """

    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    result = db.delete_session(session_id)

    print(
        f"[智愈错题] 已彻底删除会话 #{session_id}："
        f"{result['messages']} 条消息 + {result['sessions']} 条会话记录"
    )

    return {
        "success": True,
        "message": "会话及其聊天记录已彻底删除",
        "session_id": session_id,
        "deleted_messages": result["messages"],
        "deleted_sessions": result["sessions"],
    }


@app.post("/api/sessions/batch_delete", summary="批量彻底删除会话")
def api_batch_delete_sessions(payload: BatchDeleteRequest):
    """
    一次删掉多个会话（连同它们的全部聊天记录）。

    ── 为什么推荐用它，而不是前端循环调用单删接口？──
    前端循环调用的问题是"删到一半失败"：
    比如要删 10 个，删到第 6 个时网络断了，
    结果前 5 个没了、后 5 个还在，界面和数据库就对不上了。

    批量接口把这批删除放在【一个数据库事务】里：
    要么全部成功，要么一条都不删，绝不会出现删一半的中间状态。
    """

    # 去重 + 过滤非法值
    ids = sorted({int(i) for i in payload.session_ids if isinstance(i, int) and i > 0})

    if not ids:
        raise HTTPException(status_code=400, detail="没有提供要删除的会话 ID")

    if len(ids) > 200:
        raise HTTPException(
            status_code=400,
            detail="一次最多删除 200 个会话，请分批操作",
        )

    # 记下哪些是真实存在的（有些可能已经被别的操作删掉了，不算错误）
    existing_ids = [i for i in ids if db.get_session(i) is not None]

    result = db.delete_sessions(ids)

    print(
        f"[智愈错题] 批量删除完成：请求 {len(ids)} 个会话，"
        f"实际删掉 {result['sessions']} 条会话记录 + {result['messages']} 条消息"
    )

    return {
        "success": True,
        "message": f"已彻底删除 {result['sessions']} 个会话",
        "requested_session_ids": ids,
        "deleted_session_ids": existing_ids,
        "deleted_sessions": result["sessions"],
        "deleted_messages": result["messages"],
    }


@app.get("/api/debug/check", summary="检查数据库里有没有残留的垃圾数据")
def api_debug_check():
    """
    排查用的小接口：统计各表行数，并检查有没有"孤儿消息"。

    孤儿消息 = session_id 指向一个已经不存在的会话。
    正常情况下这个数字必须永远是 0。

    删完会话后打开这个地址，看到 orphan_messages 是 0，
    就说明数据真的清干净了。
    """
    counts = db.count_rows()
    return {
        "counts": counts,
        "orphan_messages": db.count_orphan_messages(),
        "healthy": db.count_orphan_messages() == 0,
    }


# ------------------------- 学习报告 -------------------------

@app.get("/api/report/{student_id}", summary="学习报告：知识点与错因统计")
def api_report(student_id: int):
    """
    统计某个学生的知识点和错因分布，给前端画图表用。

    返回的结构：
        summary          总览数字（会话数、做题数、诊断数）
        knowledge_points [{name: "一元一次方程", count: 3}, ...]  柱状图
        error_types      [{name: "计算失误",     count: 2}, ...]  饼图
        recent           最近 8 条诊断记录

    统计时会自动排除"变式练习"，只算真正诊断出来的错因。
    """

    student = db.get_student(student_id)
    if student is None:
        # 学生还没建过，返回一份空报告，不算错误
        return {
            "student": None,
            "summary": {
                "total_sessions": 0,
                "total_questions": 0,
                "diagnosed": 0,
                "knowledge_count": 0,
                "error_type_count": 0,
            },
            "knowledge_points": [],
            "error_types": [],
            "recent": [],
        }

    report = db.get_study_report(student_id)
    report["student"] = student
    return report


# ------------------------- 举一反三：变式练习 -------------------------

@app.post("/api/generate_variant", summary="举一反三：生成同类变式练习题")
async def api_generate_variant(payload: VariantRequest):
    """
    根据当前会话里之前的错题，让 AI 出一道同知识点的变式练习题。

    生成结果会作为一条普通的 AI 消息存进 messages 表，
    所以刷新页面后它还在，和学习报告也能对得上。

    注意：这条消息的 error_type 固定是"变式练习"，
    学习报告统计时会把它排除掉，免得把知识点计数刷高。
    """

    knowledge_point = (payload.knowledge_point or "").strip()
    if not knowledge_point:
        raise HTTPException(status_code=400, detail="缺少知识点，没法出变式题")

    session = db.get_session(payload.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"会话 {payload.session_id} 不存在",
        )

    # 取出这个会话之前的聊天记录，让 AI 知道原题长什么样
    history = db.get_history_for_ai(payload.session_id)

    ai_success = False
    ai_error = None
    ai_message = None

    try:
        result = await ai_service.generate_variant(history, knowledge_point)

        try:
            ai_message = db.save_message(
                payload.session_id,
                role="assistant",
                content=result["response_text"],
                knowledge_point=result["knowledge_point"],
                error_type=result["error_type"],
            )
        except sqlite3.IntegrityError as exc:
            # ★ 注意：IntegrityError 不一定就是"会话被删了"！
            #   也可能是字段约束问题（比如往 NOT NULL 列塞了 None）。
            #   之前这里不分青红皂白就报"会话已被删除"，
            #   把真正的 bug 藏了起来，害得排查了半天。
            #   所以现在：先确认会话是不是真的没了，再决定怎么报。
            if db.get_session(payload.session_id) is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"会话 {payload.session_id} 已被删除，请重新新建一个会话",
                )
            # 会话还在 -> 是别的原因，如实报出来，别再冤枉会话了
            ai_service.log_error(f"[智愈错题] 保存消息失败（会话 #{payload.session_id}）：{exc}")
            raise HTTPException(
                status_code=500,
                detail=f"保存消息到数据库时出错：{exc}",
            )

        ai_success = True

        # * 出了变式题，会话就进入"练习中"阶段。
        #   学生做得对还是错，由下一轮的 AI 来判定。
        db.set_session_status(payload.session_id, db.STATUS_PRACTICING)
        print(
            f"[智愈错题] 会话 #{payload.session_id} 已生成变式题"
            f"（知识点：{result['knowledge_point']}）"
        )

    except ai_service.AIServiceError as exc:
        ai_error = str(exc)
        print(f"[智愈错题] 生成变式题失败：{ai_error}")

    return {
        "success": True,
        "ai_success": ai_success,
        "ai_error": ai_error,
        "message": "变式题已生成" if ai_success else "变式题生成失败",
        "knowledge_point": knowledge_point,
        "ai_message": ai_message,
    }


# ------------------------- 图片 OCR -------------------------

@app.post("/api/ocr", summary="错题图片识别文字（OCR）")
async def api_ocr(payload: OcrRequest):
    """
    接收一张错题图片，让 AI 把里面的文字提取出来。

    前端流程：
        用户选图片 -> 浏览器压缩 -> 转成 base64 -> 调这个接口
        -> 拿到文字 -> 自动填进输入框

    ⚠️ 关于"用什么模型"：
        用的是 .env 里配置的 DEEPSEEK_MODEL（默认 deepseek-flash）。
        视觉是 deepseek-flash 自带的能力，不需要换模型、也不用换接口。
        详见 ai_service.py 里 extract_text_from_image 的注释。

    为什么图片要传到后端，而不是前端直接调 DeepSeek？
        因为 API Key 只能放在后端。前端直接调的话，
        任何人打开 F12 都能偷走你的 Key。
    """

    try:
        text = await ai_service.extract_text_from_image(
            payload.image_base64, payload.mime_type
        )
    except ai_service.AIServiceError as exc:
        print(f"[智愈错题] 图片 OCR 失败：{exc}")
        raise HTTPException(status_code=400, detail=str(exc))

    if not text:
        return {
            "success": False,
            "text": "",
            "message": "这张图里好像没有能识别的文字，换一张更清晰的试试？",
        }

    print(f"[智愈错题] 图片 OCR 成功，识别出 {len(text)} 个字")

    return {
        "success": True,
        "text": text,
        "message": f"识别成功，共 {len(text)} 个字",
    }


@app.post("/api/sessions/{session_id}/pin", summary="切换会话置顶状态")
def api_toggle_pin_session(session_id: int):
    """
    切换一个会话的置顶状态（置顶 <-> 取消置顶）。

    前端点会话右边那个小图钉时调用它。
    再点一次就是取消置顶，所以叫"切换"。

    置顶后的会话会在 GET /api/sessions/{student_id} 里排到最前面
    （排序是在 db.list_sessions() 里用 ORDER BY is_pinned DESC 做的）。
    """

    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 取反：原来是 1 就变 0，原来是 0 就变 1
    new_state = not bool(session.get("is_pinned"))
    updated = db.set_session_pinned(session_id, new_state)

    return {
        "success": True,
        "session_id": session_id,
        "is_pinned": bool(updated["is_pinned"]) if updated else new_state,
        "message": "已置顶" if new_state else "已取消置顶",
        "session": updated,
    }


# ------------------------- 消息 -------------------------

@app.get("/api/messages/{session_id}", summary="获取某会话的全部聊天记录")
def api_list_messages(session_id: int):
    """
    返回一个会话里的所有消息，按时间从早到晚。

    前端点开某个会话时调用它，把聊天记录铺到界面上。
    """

    session = db.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    messages = db.list_messages(session_id)
    return {
        "session": session,
        "count": len(messages),
        "messages": messages,
    }


# ------------------------- 核心：多轮对话 -------------------------

@app.post("/api/chat", summary="发一条消息并拿到 AI 回复（核心接口）")
async def api_chat(payload: ChatRequest):
    """
    多轮对话的核心接口。

    流程：
        1. 检查这个会话存不存在、是不是这个学生的
        2. 把学生说的话存进 messages 表
        3. 取出这个会话的历史消息
        4. 把【系统提示词 + 历史消息】一起发给 DeepSeek   <- 关键！
        5. 把 AI 的回复也存进 messages 表
        6. 返回这一轮的两条消息

    第 4 步就是"AI 有记忆"的原理：
    DeepSeek 本身是无状态的，它不记得你上次说了什么。
    所谓"记忆"，其实是每次请求都把之前的聊天记录重新发一遍。
    """

    # ---- 第 1 步：校验 ----
    user_input = payload.user_input.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    if payload.student_id <= 0:
        raise HTTPException(status_code=400, detail="student_id 必须是正整数")

    if payload.session_id <= 0:
        raise HTTPException(status_code=400, detail="session_id 必须是正整数")

    session = db.get_session(payload.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"会话 {payload.session_id} 不存在，请先新建一个会话",
        )

    # 防止串会话：这个会话必须真的是这个学生的
    if session["student_id"] != payload.student_id:
        raise HTTPException(
            status_code=403,
            detail=f"会话 {payload.session_id} 不属于学生 {payload.student_id}",
        )

    # ---- 第 2~5 步：交给 run_chat_turn 处理 ----
    result = await run_chat_turn(session, user_input)

    return {
        "success": True,
        "ai_success": result["ai_success"],
        "ai_error": result["ai_error"],
        "message": "AI 已回复" if result["ai_success"] else "消息已保存，但 AI 没有回复",
        # * 把教学状态透传给前端，前端靠它决定显示什么
        "is_solved": result["is_solved"],
        "session_status": result["session_status"],
        "session": result["session"],
        "user_message": result["user_message"],
        "ai_message": result["ai_message"],
    }


# ------------------------- 旧版兼容接口 -------------------------

@app.post("/api/submit_error", summary="【旧版兼容】录入错题并让 AI 诊断")
async def submit_error(payload: ErrorSubmit):
    """
    这是 v0.4 时代的接口，为了不让旧的测试代码报错而保留。

    内部其实做的是：新建一个会话 -> 发第一条消息。
    新代码请直接用 /api/new_session + /api/chat。
    """

    error_text = payload.error_text.strip()
    if not error_text:
        raise HTTPException(status_code=400, detail="错题内容不能为空")

    if payload.student_id <= 0:
        raise HTTPException(status_code=400, detail="student_id 必须是正整数")

    student, student_created = db.get_or_create_student(payload.student_id)
    session = db.create_session(payload.student_id, make_title(error_text))
    result = await run_chat_turn(session, error_text)

    ai_message = result["ai_message"]

    return {
        "success": True,
        "ai_success": result["ai_success"],
        "ai_error": result["ai_error"],
        "message": (
            "AI 诊断完成" if result["ai_success"] else "错题已保存，但 AI 诊断未完成"
        ),
        "student_created": student_created,
        "student": student,
        "session": result["session"],
        "user_message": result["user_message"],
        "ai_message": ai_message,
        # ↓ 旧格式：把这一轮的结果包成一条"对话记录"，方便老代码继续用
        "dialogue": {
            "id": ai_message["id"] if ai_message else result["user_message"]["id"],
            "student_id": payload.student_id,
            "session_id": session["id"],
            "user_input": error_text,
            "ai_response": ai_message["content"] if ai_message else None,
            "knowledge_point": ai_message["knowledge_point"] if ai_message else None,
            "error_type": ai_message["error_type"] if ai_message else None,
            "created_at": result["user_message"]["created_at"],
        },
    }


# ------------------------- 学生 -------------------------

@app.post("/api/students", summary="创建学生")
def api_create_student(payload: StudentCreate):
    """新建一个学生（用于还没接入登录功能时手动建档）。"""

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="学生姓名不能为空")

    if payload.student_id is not None:
        if payload.student_id <= 0:
            raise HTTPException(status_code=400, detail="student_id 必须是正整数")
        if db.get_student(payload.student_id) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"学生 ID {payload.student_id} 已经存在了",
            )
        student = db.create_student_with_id(payload.student_id, name)
    else:
        student = db.create_student(name)

    return {"success": True, "message": "学生创建成功", "student": student}


@app.get("/api/students", summary="查看所有学生")
def api_list_students():
    students = db.list_students()
    return {"count": len(students), "students": students}


# ===============================================================
# 7. 托管前端页面
#
#    注意：这段必须放在所有 @app.xxx 接口的后面，
#          否则 /hello 和 /api/... 会被它拦截掉。
# ===============================================================
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=FRONTEND_DIR, html=True),
        name="frontend",
    )
