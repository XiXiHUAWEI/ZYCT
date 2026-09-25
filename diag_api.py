"""
诊断脚本：一次测 4 种参数组合。

⚠️【已过期，仅作历史记录】⚠️
   本脚本是项目早期排查"正文为空"问题时写的，当时还在用 JSON 模式。
   现在项目已经改成纯文本标记（【知识点】【错因分类】【引导语】【状态】），
   不再使用 json_object 模式，所以 A/B 两组对比已经没有意义了。
   保留它只是因为 C/D 两组（温度、思考模式）偶尔还有参考价值。
   平时测试请直接用根目录的 test_api.py。

【怎么用】
    1. 先确认后端那个终端里 uvicorn 已经停掉（Ctrl+C），避免端口冲突
       （其实不用停也行，这个脚本直接连 DeepSeek，不经过我们的后端）
    2. 在本项目根目录运行：
           cd D:\\0\\1
           python diag_api.py

它会用你的 .env 里的 Key 直接调用 DeepSeek，测 4 种组合：
    A. 当前设置（json_object 模式）
    B. 去掉 json_object 模式
    C. 去掉 json_object + 提高温度 + 加重复惩罚
    D. 打开思考模式（看看思维链里有没有内容）

注意：这个脚本会消耗一点点 API 额度（4 次调用，每次几分钱），可以接受。
"""

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# 让中文在 Windows 终端能正常显示
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------- 读 .env ----------
ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=ROOT / ".env")

API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

if not API_KEY:
    print("没读到 DEEPSEEK_API_KEY，请检查 .env 文件")
    input("\n按回车键退出...") # 遇到错误也保留终端
    sys.exit(1)

print(f"模型：{MODEL}")
print(f"地址：{BASE_URL}")

# ---------- 用一段精简的提示词，排除提示词过长的影响 ----------
SYSTEM_PROMPT = """你是一位初中数学老师，用苏格拉底式提问引导学生。
只输出一个 json 对象，包含三个字段：
knowledge_point（知识点，12字以内）、error_type（错因）、response_text（给学生的引导语，80-180字，只提问不给答案）。
json 格式样例：{"knowledge_point": "一元一次方程", "error_type": "计算失误", "response_text": "我们先不急着对答案。你觉得把 5 移到右边时符号应该变成什么？"}"""

USER_TEXT = "解方程 2x + 5 = 13，我算出来 x = 3，但正确答案是 4。这是一道比较复杂的题。"


def describe(content: str) -> str:
    """描述返回的正文长什么样。"""
    if content is None:
        return "None（字段不存在）"
    if content == "":
        return "空字符串（长度 0）"
    if not content.strip():
        return f"★ 全是空白字符（长度 {len(content)}，strip 后 0）"
    return f"正常文字（长度 {len(content)}）：{content[:80]}"


def try_once(name: str, extra: dict, drop_json_mode: bool) -> None:
    """尝试一种参数组合。"""
    print("\n" + "=" * 70)
    print(f"【{name}】")
    print("=" * 70)

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEXT},
        ],
        "temperature": extra.pop("temperature", 0.7),
        "max_tokens": 2000,
        "stream": False,
    }
    if not drop_json_mode:
        payload["response_format"] = {"type": "json_object"}
    payload.update(extra)

    # 把要发的参数打印出来（不含 Key）
    print("发送的参数：", json.dumps(
        {k: v for k, v in payload.items() if k != "messages"},
        ensure_ascii=False))

    try:
        response = httpx.post(
            f"{BASE_URL}/chat/completions",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}",
            },
            timeout=180.0,
        )
    except Exception as exc:
        print(f"  请求失败：{type(exc).__name__}: {exc}")
        return

    print(f"  HTTP {response.status_code}")

    if response.status_code != 200:
        print(f"  服务端返回：{response.text[:600]}")
        return

    body = response.json()
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    reasoning = message.get("reasoning_content")
    usage = body.get("usage") or {}

    print(f"  finish_reason     : {choice.get('finish_reason')}")
    print(f"  completion_tokens : {usage.get('completion_tokens')}")
    print(f"  content           : {describe(content)}")

    if reasoning:
        print(f"  reasoning_content : 有！长度 {len(reasoning)}")
        print(f"                      末尾 100 字：...{reasoning[-100:]}")
    else:
        print(f"  reasoning_content : 没有这个字段")


print("=" * 70)
print("开始诊断，一共 4 次调用")
print("=" * 70)

# A. 当前设置
try_once("A. 当前设置（json_object 模式 + 温度0.7）", {}, drop_json_mode=False)

# B. 去掉 json_object
try_once("B. 去掉 json_object 模式（温度0.7）", {}, drop_json_mode=True)

# C. 去掉 json_object + 高温 + 重复惩罚
try_once(
    "C. 去掉 json_object + 温度1.0 + frequency_penalty 0.5",
    {"temperature": 1.0, "frequency_penalty": 0.5},
    drop_json_mode=True,
)

# D. 打开思考模式
try_once(
    "D. json_object + 显式打开思考模式",
    {"thinking": {"type": "enabled"}},
    drop_json_mode=False,
)

print("\n" + "=" * 70)
print("诊断结束")

input("\n请按回车键（Enter）退出...")