"""
智愈错题 —— 接口测试脚本（v0.5 多轮对话版）

【特点】只用 Python 自带的库，不需要 pip 安装任何东西。

【怎么用】
第 1 步：另开一个终端，启动后端
        cd D:\\0\\1\\backend
        python -m uvicorn main:app --reload

第 2 步：回到项目根目录，运行本脚本
        cd D:\\0\\1
        python test_api.py

【它会做什么】
模拟一个学生完整的一次学习过程：
    新建会话 -> 发第一道错题 -> 追问 -> 再追问 -> 查看聊天记录
并额外测试几个错误场景。
"""

import json
import os
import sys
import urllib.error
import urllib.request

# 让中文在 Windows 终端里能正常显示，避免 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ---------------------------------------------------------------
# 配置（端口可以通过环境变量覆盖）
# ---------------------------------------------------------------
BASE_URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000")
STUDENT_ID = 1


def call(method: str, path: str, body: dict | None = None):
    """发一个 HTTP 请求，返回 (状态码, 响应内容字典)。"""

    url = BASE_URL + path

    data = None
    if body is not None:
        # ensure_ascii=False 保证中文按原样编码，而不是变成 \uXXXX
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8")
        try:
            return error.code, json.loads(text)
        except json.JSONDecodeError:
            return error.code, {"原始返回": text}

    except urllib.error.URLError as error:
        print("\n[错误] 连不上后端，请确认：")
        print("       1. 后端那个终端窗口还开着吗？")
        print("       2. 提示里是不是 'Uvicorn running on http://127.0.0.1:8000'？")
        print(f"       具体原因：{error.reason}")
        sys.exit(1)


def show(title: str, status: int, data: dict) -> None:
    print("\n" + "=" * 62)
    print(title)
    print("=" * 62)
    print(f"状态码：{status}")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":

    print(f"正在测试后端：{BASE_URL}")

    # ---------- 1. 连通性 ----------
    show("【1】GET /hello —— 后端启动了吗", *call("GET", "/hello"))

    # ---------- 2. AI 配置 ----------
    show("【2】GET /api/ai_status —— AI 配好了吗", *call("GET", "/api/ai_status"))

    # ---------- 3. 新建会话 ----------
    status, data = call("POST", "/api/new_session", {"student_id": STUDENT_ID})
    show("【3】POST /api/new_session —— 新建一个会话", status, data)

    if status != 200:
        print("\n新建会话失败，后面没法继续测了。")
        sys.exit(1)

    session_id = data["session_id"]
    print(f"\n>>> 拿到的 session_id = {session_id}")

    # ---------- 4. 第一轮：发一道错题 ----------
    show(
        "【4】POST /api/chat —— 第 1 轮：发一道错题",
        *call("POST", "/api/chat", {
            "student_id": STUDENT_ID,
            "session_id": session_id,
            "user_input": "解方程 2x + 5 = 13，我算出来 x = 3，但正确答案是 4",
        }),
    )

    # ---------- 5. 第二轮：追问（关键！看 AI 记不记得上文）----------
    show(
        "【5】POST /api/chat —— 第 2 轮：追问（AI 应该记得上一轮）",
        *call("POST", "/api/chat", {
            "student_id": STUDENT_ID,
            "session_id": session_id,
            "user_input": "我还是不太明白，为什么移项要变号？",
        }),
    )

    # ---------- 6. 第三轮 ----------
    show(
        "【6】POST /api/chat —— 第 3 轮：再追问一次",
        *call("POST", "/api/chat", {
            "student_id": STUDENT_ID,
            "session_id": session_id,
            "user_input": "哦！所以是 x = 8 除以 2，等于 4 对吗？",
        }),
    )

    # ---------- 7. 查看聊天记录 ----------
    show(
        f"【7】GET /api/messages/{session_id} —— 查看这个会话的聊天记录",
        *call("GET", f"/api/messages/{session_id}"),
    )

    # ---------- 8. 会话列表 ----------
    show(
        f"【8】GET /api/sessions/{STUDENT_ID} —— 该学生的会话列表",
        *call("GET", f"/api/sessions/{STUDENT_ID}"),
    )

    # ---------- 9. 错误场景：空消息 ----------
    show(
        "【9】POST /api/chat 空消息 —— 应该返回 400",
        *call("POST", "/api/chat", {
            "student_id": STUDENT_ID,
            "session_id": session_id,
            "user_input": "     ",
        }),
    )

    # ---------- 10. 错误场景：会话不存在 ----------
    show(
        "【10】POST /api/chat 到一个不存在的会话 —— 应该返回 404",
        *call("POST", "/api/chat", {
            "student_id": STUDENT_ID,
            "session_id": 999999,
            "user_input": "测试",
        }),
    )

    # ---------- 11. 错误场景：会话不属于这个学生 ----------
    show(
        "【11】POST /api/chat 用别的学生的会话 —— 应该返回 403",
        *call("POST", "/api/chat", {
            "student_id": 8888,
            "session_id": session_id,
            "user_input": "测试",
        }),
    )

    print("\n" + "=" * 62)
    print("全部测试跑完了。")
    print("上面出现 200 / 400 / 403 / 404 都是正常的。")
    print("=" * 62)
input("\n请按回车键（Enter）退出...")