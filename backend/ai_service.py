"""
智愈错题 —— AI 服务模块（v0.5 多轮对话版）

负责调用 DeepSeek API。相比上一版，最大的区别是：
    上一版：analyze_error(一道错题)      —— 一问一答，没有记忆
    本  版：generate_reply(整段聊天历史) —— 带着上下文，能连续追问

【API Key 怎么配置】
在项目根目录新建 .env 文件，写入 DEEPSEEK_API_KEY=sk-你的密钥。
详见 README 的「配置 DeepSeek API Key」一节。

【为什么 Key 必须放在后端？】
因为前端的 JavaScript 在浏览器里按 F12 就能看到全部代码。
如果把 Key 写在前端，任何人打开网页都能偷走你的 Key。
所以正确做法是：前端 → 我们的后端 → DeepSeek。Key 只存在后端，永不出门。
"""

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------
# 1. 读取 .env 配置
# ---------------------------------------------------------------

# 项目根目录 = backend 的上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# load_dotenv 会把 .env 文件里的内容读进环境变量，
# 之后就能用 os.getenv() 拿到了。
# 注意：它不会覆盖系统里已经存在的同名环境变量（这是好事）。
load_dotenv(dotenv_path=ENV_PATH)

# 用 os.getenv("名字", "默认值") 读取，读不到就用默认值，程序不会崩
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
).strip().rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()

# ★ 读超时（秒）：发出请求后，最多等 AI 多久。
#
#   这个数字是个【取舍】：
#      调大（比如 180）-> 复杂题目能等到答案，但学生要干等更久
#      调小（比如 30） -> 快速失败、界面不卡，但复杂题目几乎必定超时
#
#   现在是 180 秒，给复杂的高中数学题留足思考时间。
DEEPSEEK_TIMEOUT = float(os.getenv("DEEPSEEK_TIMEOUT", "180"))

# ★ AI 单次最多输出多少 token。
#
#   推理模型"光想就开始花 token"，很容易把正文挤没。
#   所以给到 6000（注意：这个上限同时包含思考消耗和正文输出）。
MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "6000"))

# ★ 思考模式开关，三档可选：
#
#     auto  不传这个参数，用服务端的默认行为  ← 【推荐，实测最稳】
#     on    显式打开思考模式
#     off   显式关闭思考模式
#
#   ── 为什么推荐 auto？──
#   2026-xx 实测发现：传 {"thinking": {"type": "disabled"}} 会让模型
#   返回"全是空格的 content"（completion_tokens 有 74，但内容是 74 个空格），
#   而且可复现。不传这个参数时，思考内容正常放在 reasoning_content 里，
#   正文 content 是完全正常的 JSON。
#
#   也就是说：思考模式开着【不影响】正文，别去手动关它。
AI_THINKING_MODE = os.getenv("AI_THINKING", "auto").strip().lower()

# 每次最多带多少条历史消息给 AI（约等于 10 轮对话）
# 带太多会又慢又贵，还可能超出模型的上下文长度限制
MAX_HISTORY_MESSAGES = int(os.getenv("AI_MAX_HISTORY", "20"))


# ---------------------------------------------------------------
# 终端彩色输出
#
# 用 ANSI 转义码给日志上色，纯文本环境会自动忽略，不影响使用。
# Windows 10/11 自带的终端（Windows Terminal、新版 PowerShell）
# 都支持；如果看到一堆乱码，说明你的终端太老，可以忽略。
# ---------------------------------------------------------------
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def log_error(text: str) -> None:
    """打印红色错误日志，一眼就能在刷屏的日志里看到。"""
    print(f"{RED}{text}{RESET}", flush=True)


def log_ok(text: str) -> None:
    """打印绿色成功日志。"""
    print(f"{GREEN}{text}{RESET}", flush=True)


def log_info(text: str) -> None:
    """打印青色普通信息。"""
    print(f"{CYAN}{text}{RESET}", flush=True)


# ---------------------------------------------------------------
# 2. 自定义异常
#
# 为什么要自定义异常？
# 这样 main.py 只要写一句 except ai_service.AIServiceError，
# 就能把"没配 Key""网络不通""返回的不是 JSON"全部兜住，
# 然后统一转成给用户看的友好提示。
# ---------------------------------------------------------------

class AIServiceError(Exception):
    """
    AI 服务相关错误的基类。

    多带一个 code 字段，用来告诉前端"这是哪一类错误"。
    前端靠它决定显示什么提示（比如超时要说"请再试一次"）。
    """

    def __init__(self, message: str, code: str = "unknown"):
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:
        return self.message


class AIConfigError(AIServiceError):
    """没有配置 API Key。"""

    def __init__(self, message: str):
        super().__init__(message, code="not_configured")


class AIRequestError(AIServiceError):
    """网络不通、Key 无效、余额不足、超时等。

    code 常见取值：
        timeout       超时（AI 想太久了）
        network       网络不通
        http_401      Key 无效
        http_402      余额不足
        http_429      请求太频繁
        http_xxx      其它 HTTP 错误
    """

    def __init__(self, message: str, code: str = "request_failed"):
        super().__init__(message, code=code)


class AIResponseError(AIServiceError):
    """AI 返回的内容不是我们想要的 JSON，或者返回了空内容。"""

    def __init__(self, message: str, code: str = "bad_response"):
        super().__init__(message, code=code)


# ---------------------------------------------------------------
# 3. 核心提示词（System Prompt）
#
# 这是整个项目最重要的部分之一。
# 写得好不好，直接决定 AI 是"直接甩答案"还是"耐心引导"，
# 也决定它是"记得上文"还是"每轮都从头开始"。
# ---------------------------------------------------------------

SYSTEM_PROMPT = """════════════════════════════════════════════
【强制结课指令 —— 全局最高优先级，压过本文档里所有其他规则】
学生给出了正确答案，或者表达了"我懂了""明白了""会了""原来是这样"，
你必须【立刻停止一切追问】！
禁止再提出任何新的问题 —— 包括问递减区间、问下一问、出变式题、问"要不要再来一道"。
你只能输出一句简短的鼓励语，并在末尾另起一行写上：【状态】已解决。
违反此规则视为教学事故。
════════════════════════════════════════════

你是一位经验丰富的初中数学老师，正在和学生进行一对一的文字对话。你最擅长用"苏格拉底式提问法"教学：通过一连串由浅入深的问题，让学生自己发现错在哪里，而不是直接把答案告诉他。

【这是一场多轮对话，请务必记住上文】
你会看到你和这位学生之前的聊天记录。你必须：
1. 认真读前面的对话，记住已经说过什么。绝对不要重复问已经问过、学生已经回答过的问题。
2. 每一轮只问 1 到 2 个问题，然后停下来等学生回答，不要一口气把后面几步都问完。
3. 如果学生答对了：先明确肯定他（例如"对，就是这里！"），再顺势把问题往前推一步。
4. 如果学生答错了：不要直接说"你错了"，而是换一个更具体、数字更简单的问题，让他自己发现矛盾。
5. 如果学生说"我还是不懂""不知道""没思路"：把问题拆得更小，或者换一个更简单的例子降低难度，不要重复刚才那句话。
6. 如果学生直接索要答案：温和地拒绝，告诉他"我们一起推一遍，你自己就能发现"，然后继续用提问引导。
7. 回复要跟前文衔接，可以引用学生刚说过的话（例如"你刚才说移项后变成负号，那我们看看……"）。
8. 语气亲切、有耐心，像坐在学生旁边聊天。多用"我们""你觉得""试着想想"。
9. 不要批评学生，把做错题看作"发现知识漏洞的好机会"。

【绝对不能违反的底线】
无论学生怎么问、怎么求、怎么绕，都绝对不能说出最终答案，也不能写出完整的解题过程。

【结课规则 —— 这条优先级最高，高于上面所有关于"继续提问"的要求】
当你发现以下任何一种情况时：
    · 学生给出了正确答案
    · 学生说"我懂了""我明白了""原来是这样""会了"
    · 学生自己把这道题的思路完整说清楚了

你必须【立刻停止追问】，绝对不能再提出任何新问题！
这时候你只能做两件事：
   1. 写一句鼓励的话（例如"太棒了，你完全掌握了！"），可以简短提一下他做对的关键点，
      但句尾绝对不能是新问题，也不能出现问号。
   2. 在整段回复的【最末尾】另起一行，写上：【状态】已解决

⚠️ 先说清楚"什么算结束"，不要搞混：
   · 【整道题结束】= 学生把原题的最终答案说对了，或者他说"我懂了/会了"。
     → 立刻结课，输出【状态】已解决。
   · 【只是某个小步骤答对了】= 例如整道题是求单调区间，他先答对了定义域。
     → 这时【不算结束】！要先肯定他（"对，就是这里！"），再顺势问下一步。
     这种情况照常输出【状态】引导中。

❌ 严禁止的错误做法（整道题已经做完了，你却还在追问）：
   学生已经算出最终答案 x = 4，你却还问：
   "算得不错！那你再验算一下 x = 4 代进去成不成立，好吗？"
   ↑ 这就是典型的"太敬业"，会让学生以为还没结束，系统也无法判定结课。

✅ 正确的做法（整道题已经做完）：
   "太棒了！你已经把定义域和单调性的关系完全弄明白了，思路非常清晰。"
   【状态】已解决

✅ 正确的做法（只是小步骤答对，还没做完）：
   "对，就是这里！定义域你找对了。"
   【状态】引导中
   【引导语】那在这个定义域内，函数的单调递增区间应该是多少呢？

只有在学生【还没有】解出整道题时，你才继续用提问引导他。
这条规则和"引导学生自己发现答案"并不冲突 —— 学生已经发现答案了，引导任务就完成了。
"""

# ---------------------------------------------------------------
# ★ 输出格式段落 —— 单独拆出来，不再无脑拼在基础提示词后面
#
# 为什么要拆？
#   引导追问（guiding）和已解决（solved）这两个阶段是【不允许出现标签】的。
#   但下面这段"✅ 正确的输出"范例里，本身就写着【知识点】【错因分类】。
#   模型看到具体范例，往往比看到"不要写标签"这句话更听话 ——
#   于是它就把标签一起带出来了（你测试时遇到的"标签乱飘"就是这么来的）。
#
#   与其反复叮嘱"不要写"，不如在这两个阶段干脆不把这段范例发给它，
#   从源头上断掉模仿的机会。
#
# 只有这两种阶段需要它：
#   diagnosing  首次诊断 —— 要写标签
#   practicing  变式练习 —— 做对了不写，做错了要写，所以格式也得给它
# ---------------------------------------------------------------
TAG_FORMAT_SECTION = """
【输出格式 —— 这是硬性规定，没有任何商量余地】
你的回复必须、且只能包含下面这些标记行。不许多说一个字，不许少写一个标记。

必须使用的标记（全角方括号【】，一个都不能少，不许换别的写法）：
【知识点】
【错因分类】
【错因分析】
【引导语】
【状态】
⚠️【错因分类】只能从下面 7 个里挑一个，一个字都不能改（系统按这 7 个统计图表）：
   计算失误 / 概念混淆 / 审题不清 / 步骤遗漏 / 公式记错 / 逻辑推理错误 / 其他
   ❌ 不要写"概念不清""思路错误""单位换算错误"这类列表外的词。
【错因分析】的写法有严格要求（这一条很重要，系统会检查）：
   必须是一句通顺完整的话，严禁在句尾使用省略号，也绝不允许强行截断。
   如果错因超过 20 个字，请做高度概括，但务必保证句子意思完整。
   ❌ 绝对不要这样写：移项时把 5 从左边移到右边忘记变号所以计算失…
   ✅ 应该这样写：移项时忘记改变符号，导致后续计算全部出错
【状态】说明（写在回复的最末尾）：
   还在引导他思考 -> 【状态】引导中
   他已经把整道题弄明白了 -> 【状态】已解决
   他做变式题做错了，需要重新诊断 -> 【状态】需要诊断

【✅ 正确的输出 —— 请照着这个写】
【知识点】复合函数单调性
【错因分类】概念混淆
【错因分析】忽略定义域对单调区间的限制
【引导语】我们先别急着看单调区间。你想想，log 里面的式子必须满足什么条件？
【状态】引导中

【❌ 严禁出现的错误写法】
错误一：不加方括号
    知识点：复合函数单调性
    错因：忽略定义域限制
错误二：用 Markdown 加粗或标题代替
    **知识点**：复合函数单调性
    ### 错因
错误三：用 JSON 或代码块包裹
    {"知识点": "复合函数单调性"}
    ```
    【知识点】复合函数单调性
    ```
错误四：完全不写标记，直接写一大段话
    这道题你错在忽略了定义域限制，我们来看看……
错误五：用别的词代替标记（比如写成"考查内容""错误原因""回答"）
错误六：忘了写【状态】这一行

【关于【引导语】】
它写在最后（如果你写了【状态】，就把【状态】放在【引导语】前面），
可以换行、可以写很多句，想写多长就写多长，直到你说完为止。
除了这些标记开头的文字，你的回复里不要出现任何别的东西 ——
不要开场白（比如"好的，我来分析一下"），不要结束语（比如"希望对你有帮助"），
也不要解释你正在做什么。
"""


# ===============================================================
# 状态机：同一个 AI，在不同教学阶段要说不同的话
#
# 为什么需要这个？
#   如果每一轮都输出"知识点 + 错因"，学生看到的界面会满是标签，
#   引导的过程反而被淹没了。而且题目还没做出来就冒出
#   "生成同类练习题"按钮，逻辑上也不对。
#
# 四个阶段：
#   diagnosing  首次诊断 —— 输出三个标记（知识点/错因/引导语）
#   guiding     引导追问 —— 只输出【状态】和【引导语】，不写标签
#   solved      讲解成功 —— 只输出鼓励的话，不写标签
#   practicing  变式练习 —— 出题让学生做；做错了才重新输出标签
#
# 实现方式：SYSTEM_PROMPT 是"基础人格 + 默认输出格式"，
# 下面这段是"本轮的特殊要求"，追加在后面并明确声明覆盖前面的格式。
# 这样基础人格只写一份，不用维护四份完整提示词。
# ===============================================================
_STATE_OVERRIDES = {

    # ---------- 引导追问中 ----------
    "guiding": """
【本轮的特殊要求 —— 这一条覆盖所有其他说明】
学生还在思考，你正在一步步引导他。本轮你【只输出两行】：

【状态】引导中
【引导语】你的引导语

⚠️ 本轮【绝对不要】输出【知识点】【错因分类】【错因分析】这些标记。
   它们只在第一次诊断时写，中间每一轮引导都不要再写，一个字都不要写。
⚠️ 本轮【引导语】只写你新问的那个问题，不要重复罗列知识点，也不要把整道题重新分析一遍。

例外情况：如果你从学生的回答里看出他已经自己推出了正确结论，
就立刻执行上面的【强制结课指令】—— 只输出下面两行，绝对不能再问任何新问题：
【状态】已解决
【引导语】一句鼓励的话（例如"太棒了！你已经把这道题完全弄明白了"）
""",

    # ---------- 学生已经做对 ----------
    "solved": """
【本轮的特殊要求 —— 这一条覆盖所有其他说明】
学生已经把这道题弄明白了。本轮你【只输出两行】：

【状态】已解决
【引导语】真诚地祝贺他，简单总结一下他这次做对的关键点，鼓励他继续。

⚠️ 本轮【绝对不要】输出【知识点】【错因分类】【错因分析】这些标记，也不要再出题。
⚠️ 本轮【引导语】里绝对不能再出现问号，也不能问"要不要再来一道""你确定吗"之类的话。
   这一轮之后这道题就结束了，学生答对了就是答对了，不要再反复确认。
""",

    # ---------- 变式练习中 ----------
    "practicing": """
【本轮的特殊要求 —— 这一条覆盖上面关于输出格式的所有说明】
学生正在做你之前出的变式练习题。请根据他的回答判断：

情况 A：他做对了
    只输出两行：
    【状态】已解决
    【引导语】热情地表扬他（例如"太棒了！你完全掌握了这个知识点"）。
    ⚠️ 绝对不要输出【知识点】和【错因】，也绝对不要再提出新问题。

情况 B：他做错了、或者做不出来
    输出四行，重新给出诊断标签：
    【状态】需要诊断
    【知识点】这道变式题考查的知识点
    【错因分类】从固定列表里挑一个：计算失误 / 概念混淆 / 审题不清 / 步骤遗漏 / 公式记错 / 逻辑推理错误 / 其他
    【错因分析】一句通顺完整的话，说清他这次错在哪
    【引导语】不要直接说答案，用提问引导他自己发现问题。
""",
}


# 这两个阶段不允许出现任何标签
_TAG_FREE_STATES = ("guiding", "solved")


# ---------------------------------------------------------------
# ★ 终极结课格式 —— 拼在最终提示词的【最末尾】
#
# 为什么放在最后，而不是写在 SYSTEM_PROMPT 里面？
#   大模型对"开头"和"结尾"最敏感，中间容易被忽略。
#   这段是最后一道文字防线，必须让它成为模型读到的最后几句话。
#
# 注意：这里给出的是一个【字面模板】。
#   前面几轮的教训是"给范例就会被模仿" ——
#   但这次我们就是要它模仿，而且是逐字模仿，所以给模板是对的。
#   真正的保底仍然是后端代码截断，这段只是尽量让 AI 一开始就写对。
# ---------------------------------------------------------------
FINAL_CLOSING_FORMAT = """

════════════════════════════════════════════
【终极结课格式 —— 这是你读到的最后一条规则，优先级最高】
如果你认为学生已经解答正确，你只能返回以下格式，不能多写一个字：

太棒了，你完全掌握了！【状态】已解决

绝对禁止在结课回复中出现任何新问题、递减区间、变式题或下一问。
绝对禁止在【状态】已解决【后面】再写任何内容 —— 一个字都不行。
════════════════════════════════════════════
"""


def build_system_prompt(status: str) -> str:
    """
    根据会话当前的教学阶段，拼出这一轮该用的系统提示词。

    参数 status 取值：diagnosing / guiding / solved / practicing
    （传了不认识的值，就按 guiding 处理，不会报错）

    ★ 关键点：guiding / solved 这两个阶段【不拼接 TAG_FORMAT_SECTION】。
      因为那段里带着【知识点】【错因分类】的示范，
      一并发过去，模型就照着写，标签就飘出来了。
      这两个阶段只发"基础人格 + 本轮要求"，并要求它只写【状态】和【引导语】。

    ★ 不论哪个阶段，最后都会追加 FINAL_CLOSING_FORMAT（终极结课格式）。
    """
    if status not in _STATE_OVERRIDES:
        # diagnosing：首次诊断，要写标签，所以格式段落必须给
        body = SYSTEM_PROMPT + "\n" + TAG_FORMAT_SECTION
    elif status in _TAG_FREE_STATES:
        # 引导追问 / 已解决：严禁标签 —— 连格式范例都不给它看
        body = SYSTEM_PROMPT + "\n\n" + _STATE_OVERRIDES[status]
    else:
        # practicing：做错了要重新出标签，所以格式段落还得给
        body = SYSTEM_PROMPT + "\n" + TAG_FORMAT_SECTION + "\n\n" + _STATE_OVERRIDES[status]

    # ★ 终极结课格式永远在最后
    return body + FINAL_CLOSING_FORMAT


# 变式题要求里必须出现的那句话（需求里明确规定的）
VARIANT_INSTRUCTION = "请解答这道题，如果做错我会帮你诊断。"


# ---------------------------------------------------------------
# ★ 兜底装置：学生说自己懂了，后端就强制结课
#
# 为什么需要它？
#   提示词再怎么强调，大模型也只是"大概率听话"，不是"必然听话"。
#   你要录视频，不能赌它这一轮心情好不好。
#   所以判断这件事不能全交给模型 —— 后端自己也要有一票否决权。
#
# 判断规则：学生的话里出现"我懂了/明白了/原来是这样"这类表述，
#           并且【没有】出现"不懂/不明白/不会"这类否定表述。
# ---------------------------------------------------------------

# 表示"我懂了"的措辞
_UNDERSTOOD_PHRASES = (
    "我懂了", "我明白了", "我理解了", "我知道了", "我清楚了",
    "懂了", "明白了", "理解了", "清楚了",
    "原来是这样", "原来如此", "恍然大悟",
    "我会了", "我搞懂了", "弄明白了", "想通了", "看懂了",
    "完全掌握", "学会了", "彻底懂了", "没问题了", "搞清楚了",
)

# 表示"我还没懂"的措辞。
# ★ 必须先检查这一组：因为"不懂"里也含"懂"，
#   如果先检查上面那组，"我还是不懂"会被误判成"我懂了"。
_NOT_UNDERSTOOD_PHRASES = (
    "不懂", "没懂", "不明白", "没明白", "不理解", "没理解",
    "不会", "不清楚", "不知道", "搞不懂", "看不懂", "听不懂",
    "想不通", "想不明白", "有点懵", "还是不会", "仍然不会",
)

# ★ 第二类信号："学生在陈述一个答案"。
#
# 这类信号的措辞本身不能证明答案是对的（后端不会做数学题），
# 所以只在【已经引导过至少一轮】之后才认它。
# 否则会话第一条消息（"这道题答案是4，我算出来3"）就会把课堂当场结束掉。
_ANSWER_SIGNAL_PHRASES = (
    "答案是", "答案就是", "我的答案是", "所以答案是",
    "应该是", "结果是", "所以是", "算出来是", "我算出来是",
    "我求出来", "得出来是", "区间是", "最终答案",
)


def looks_like_student_understood(text: str, status: str = "") -> bool:
    """
    判断学生这句话是不是"可以结课了"。

    返回 True 才触发后端的强制结课。

    两类信号：
      第一类（任何状态都认）：学生明确说"我懂了/明白了/原来是这样"
      第二类（只有非首次诊断才认）：学生在陈述一个答案 —— "答案是 (2,+∞)"

    参数 status 是会话当前阶段。传空字符串表示"不限制状态"（只认第一类）。

    为什么第二类要限制状态？
        因为你发第一道错题时，原话很可能就是
        "解方程 2x+5=13，我算出来 x=3，但正确答案是 4" ——
        这里含"算出来"和"答案是"。如果在首次诊断也认它，
        课堂会在你刚坐下、还没开始讲的时候就结束。
        所以只有已经引导过至少一轮（guiding / practicing），
        学生再抛出一个答案，才算他真的在回答你的问题。
    """
    if not text:
        return False

    raw = text.strip()

    # ★ 第一优先：否定词先否决。
    #   "我还是不懂"、"这题我不会" 里都含"懂/会"，先挡住它们。
    for phrase in _NOT_UNDERSTOOD_PHRASES:
        if phrase in raw:
            return False

    # 第一类信号：明确表示懂了
    for phrase in _UNDERSTOOD_PHRASES:
        if phrase in raw:
            return True

    # 第二类信号：在陈述答案（只在已经引导过的阶段才认）
    if status in ("guiding", "practicing"):
        for phrase in _ANSWER_SIGNAL_PHRASES:
            if phrase in raw:
                return True

    return False


# 【状态】已解决 的各种可能写法。
# AI 偶尔会写"状态：已解决"（用冒号）或者带别的小变体，都收进来。
_SOLVED_MARKER_VARIANTS = (
    "【状态】已解决",
    "【状态】 已解决",
    "状态：已解决",
    "状态:已解决",
    "【状态】：已解决",
    "【状态】:已解决",
)


def cut_after_solved_marker(text: str) -> tuple[str, bool]:
    """
    ★ 硬性截断：找到"【状态】已解决"的位置，把它【后面】的内容全部砍掉。

    为什么必须做这一步？
        AI 就算乖乖写上了【状态】已解决，也常常"意犹未尽"，
        在标记后面又甩出一道新题，例如：
            【引导语】太棒了，你完全掌握了。
            【状态】已解决
            如果把题目改成 g(x)=ln(-x²+2x)，你会怎么求单调区间呢？
        这段尾巴会让接口返回的正文里带问号，
        学生（和你的录屏）会觉得"AI 还在讲"，界面很割裂。
        所以后端直接一刀切掉 —— 标记之后的一切都不要。

    返回 (截断后的文本, 是否真的截断过)。
    """
    if not text:
        return "", False

    raw = text
    hit = -1
    hit_marker = ""
    for marker in _SOLVED_MARKER_VARIANTS:
        pos = raw.find(marker)
        if pos != -1 and (hit == -1 or pos < hit):
            hit = pos
            hit_marker = marker

    if hit == -1:
        return raw.strip(), False

    # 保留【状态】已解决 之前的所有内容（标记本身也不要，前端不显示它）
    head = raw[:hit].strip()
    return head, True


# 结课轮次里【不该出现】的话题词。
# 只要一句话里含这些词，整句丢掉 —— 结课文案里不该提到任何"新题"。
_CLOSING_FORBIDDEN_WORDS = (
    "变式", "练习题", "下一题", "下一问", "再来一道", "新题",
    "巩固一下", "再试一道", "换个题",
)


def force_close_text(text: str) -> str:
    """
    把 AI 一段"还在追问"的回复，改写成干净的结课语。

    处理顺序（每一步都在上一步的结果上继续）：
        第 1 步：砍掉"【状态】已解决"后面的所有内容
                 —— AI 最爱在标记后面追加一道新题
        第 2 步：把带问号的句子整句删掉
                 —— AI 也可能把新问题写在标记前面
        第 3 步：删掉【变式练习】整块
                 —— 结课轮次绝对不该出现新题
        第 4 步：兜底自检 —— 如果还有问号，整段换成标准结课文案

    AI 违规时的典型输出是：
        "对，你说得对！那你想想递减区间怎么求呢？"
    强制结课后如果原样显示，学生（和你录的视频）会看到
    按钮弹出来了、可 AI 还在问问题，非常割裂。

    所以这里把带问号的句子删掉，只留下肯定和鼓励。
    如果删完啥都不剩，就补一句标准结课语。
    """
    raw = (text or "").strip()

    # ---- 第 1 步：砍掉"【状态】已解决"后面的一切 ----
    # AI 最爱在这个标记后面追加"如果把题目改成……你会怎么求呢？"
    raw, _cut = cut_after_solved_marker(raw)

    # ---- 第 3 步（先做，因为要整块删）：删掉【变式练习】整段 ----
    if "【变式练习】" in raw:
        raw = raw.split("【变式练习】")[0].strip()

    # ---- 第 2 步：按句号切句，丢掉含问号的句子 ----
    #
    # 除了问号句，还要丢掉"提到新题"的句子。
    # 因为 AI 可能这样写：
    #     "咱们来做一道变式练习。【变式练习】求 y=ln(x) 的单调区间。"
    # 前半句没有问号，但它是"准备继续上课"的信号，
    # 留着会和后面的鼓励语打架（"来做一道变式练习。太棒了，你完全掌握了！"）。
    kept: list[str] = []
    for line in raw.splitlines():
        for sentence in re.split(r"(?<=[。！!])", line):
            sentence = sentence.strip()
            if not sentence:
                continue
            if "？" in sentence or "?" in sentence:
                continue
            if any(word in sentence for word in _CLOSING_FORBIDDEN_WORDS):
                continue
            kept.append(sentence)

    body = "".join(kept).strip()

    # 顺手把可能残留的标记符号去掉（结课文案不该出现【】）
    for marker in _HISTORY_MARKERS:
        body = body.replace(marker, "")
    body = body.strip()

    if not body:
        body = "太棒了！这道题你已经完全弄明白了，思路非常清晰。"

    # 结尾统一补一句结课文案（如果本来就已经收过尾就不重复加）
    if "完全掌握" not in body and "弄明白" not in body and "太棒了" not in body:
        body = body + "太棒了，这道题你已经完全弄明白了！"

    # ---- 第 4 步：兜底自检 ----
    # 走完上面三步还残留问号，说明句子切分没覆盖到这种写法。
    # 这时候不冒险，整段换成标准结课文案 —— 保证"结课语里永无问号"这条铁律。
    if "？" in body or "?" in body:
        return "太棒了，你完全掌握了！"

    return body


# 历史消息里出现过的所有标记词。
# 用途：把历史里 AI 自己说过的助手消息"洗"成纯文本，
#       免得模型看到"我上一轮写了【知识点】"，这一轮就跟着写。
_HISTORY_MARKERS = (
    "【知识点】", "【错因分类】", "【错因分析】", "【错因】",
    "【引导语】", "【状态】", "【变式练习】",
)


def strip_markers_for_history(text: str) -> str:
    """
    把一条 AI 历史回复里的标记行清理掉，只留下学生看得懂的那部分。

    为什么必须做这一步？
        模型有很强的"模仿上文"倾向。历史记录里只要出现过
        \"【知识点】…【错因】…\"，它下一轮就会照样再写一遍，
        哪怕系统提示词里三令五申说"不要写标签"也没用。
        所以在把历史发给它之前，先把这些行删干净 —— 釜底抽薪。

    保留的内容就是【引导语】/【状态】后面的正文；
    万一解析不出正文，就退回"逐行删掉标记行"的笨办法。
    """
    if not text:
        return ""

    raw = text.strip()
    if not any(marker in raw for marker in _HISTORY_MARKERS):
        # 本来就没有标记，原样返回（绝大多数引导轮次都走这里）
        return raw

    # 首选：交给正式的解析器，它最懂标记的切法
    try:
        parsed = extract_ai_data(raw)
        body = (parsed.get("response_text") or "").strip()
        if body:
            return body
    except Exception:
        pass

    # 兜底：一行一行看，把标记行丢掉，保留普通文字
    kept: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        # 【状态】这一行整行丢掉（它只是个控制信号，没有教学意义）
        if stripped.startswith("【状态】"):
            continue
        # 其他标记行：保留标记后面的内容
        for marker in _HISTORY_MARKERS:
            if stripped.startswith(marker):
                stripped = stripped[len(marker):].strip()
                break
        if stripped:
            kept.append(stripped)

    return "\n".join(kept).strip()


# ---------------------------------------------------------------
# 4. 辅助函数
# ---------------------------------------------------------------

def is_configured() -> bool:
    """检查有没有配置 API Key。"""
    return bool(DEEPSEEK_API_KEY)


def build_context_messages(history: list[dict]) -> list[dict]:
    """
    把数据库里的聊天记录，整理成 DeepSeek 要的 messages 格式。

    这一步是"让 AI 有记忆"的关键：
    如果不带历史，AI 每轮都是失忆的。学生说"我还是不懂"，
    它根本不知道"不懂"的是哪道题，只会重新讲一遍。

    输入：[{"role": "user", "content": "..."}, ...]
    输出：同样格式，但做了清洗、过滤和截断。

    做四件事：
      1. 只保留 role 和 content 两个字段，丢掉 id、时间之类的多余信息
      2. 丢掉空内容（空消息会让部分模型报错）
      3. ★ 丢掉"坏例子"—— 以前解析失败的历史消息（带"未识别""待补充"
         或者错误提示的），不能让 AI 照着学坏习惯
      4. ★ 只保留最近 MAX_HISTORY_MESSAGES 条
      5. ★ 把 AI 历史回复里的【知识点】【错因】等标记洗干净
         —— 这是"标签乱飘"的根源之一：模型会模仿自己上文写过的标记。
    """

    cleaned: list[dict] = []
    skipped = 0

    for item in history:
        role = item.get("role")
        content = (item.get("content") or "").strip()

        # ★ AI 的历史回复先洗掉标记（只洗 assistant，学生的原话不动）
        if role == "assistant":
            content = strip_markers_for_history(content)

        # 只认识这两种角色，其他的一律忽略
        if role not in ("user", "assistant"):
            continue
        # 空消息会让部分模型报错，直接跳过
        if not content:
            continue

        # ★ 过滤掉"坏例子"
        # 这些是之前解析失败或 AI 出错时留下的内容。
        # 如果原样发给 AI，它会以为"原来可以这么回答"，越学越跑偏。
        if _looks_like_bad_example(content):
            skipped += 1
            continue

        cleaned.append({"role": role, "content": content})

    # ★ 只保留最近 N 条
    if len(cleaned) > MAX_HISTORY_MESSAGES:
        cleaned = cleaned[-MAX_HISTORY_MESSAGES:]

    # 小细节：如果截断后第一条正好是 AI 说的话，对话就变成"AI 先开口"，
    # 有点奇怪。去掉它，保证历史一定从用户的话开始。
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)

    if skipped:
        log_info(f"[智愈错题] 历史上下文里过滤掉 {skipped} 条坏例子")

    return cleaned


def _looks_like_bad_example(content: str) -> bool:
    """
    判断一条历史消息是不是"坏例子"，不该发给 AI 学习。

    什么算坏例子？
      · 解析失败留下的占位符（未识别、待补充）
      · 我们自己的报错提示（超时、连不上、格式不对）
      · 空内容提示
    """
    bad_keywords = (
        "未识别",
        "待补充",
        "思考超时",
        "返回了空内容",
        "没有按【知识点】",
        "AI 导师正在深度思考中",
        "消息已保存，但 AI 没有回复",
        "抱歉，这道题太难了，我思考超时了",
    )
    return any(word in content for word in bad_keywords)


def _salvage_from_reasoning(reasoning: str) -> str:
    """
    【兜底用】从 reasoning_content（思维链）里尽量捞出能用的内容。

    什么情况下会用到它？
        万一哪天服务器行为变了，把内容全写进思维链、
        而 content 是空的，这里能救一下。
        （注意：不要去手动传 thinking=disabled 想"关掉思考模式"，
          实测那会让 content 变成一堆空格，反而更糟。）

    两步捞法：
        1. 思维链里其实藏着一段 JSON（模型在"想"的时候把答案写出来了）
           -> 直接抠出来还给上层，走正常解析流程（最理想）
        2. 实在没有 JSON，就从末尾找中文句子
           -> 因为给学生的引导语通常写在思维链的最后

    返回一个 JSON 字符串（和正常返回格式一样），捞不到就返回空字符串。
    """
    text = (reasoning or "").strip()
    if not text:
        return ""

    # ---------- 捞法 1：里面其实已经写好了带标记的文本 ----------
    if "【引导语】" in text or "【知识点】" in text or "【错因】" in text:
        return text

    # ---------- 捞法 2：取末尾的中文句子 ----------
    # 按换行切块，只留下含中文的块
    pieces = [
        p.strip() for p in re.split(r"\n+", text)
        if re.search(r"[\u4e00-\u9fff]", p)
    ]

    # 从后往前累积，凑够 250 字左右就停（末尾才是要给学生看的话）
    picked = []
    total = 0
    for piece in reversed(pieces):
        if len(piece) < 8:      # 太短的多半是零碎词，跳过
            continue
        picked.insert(0, piece)
        total += len(piece)
        if total >= 250:
            break

    if not picked:
        return ""

    # 太长的话只保留最后 800 字，避免把整段思维链塞给学生
    salvaged_text = "\n".join(picked)[-800:].strip()
    if len(salvaged_text) < 10:
        return ""

    # 包成和正常输出一样的"文本标记"格式，这样上层用同一个解析器就行
    return (
        "【知识点】未识别\n"
        "【错因】未识别\n"
        "【引导语】" + salvaged_text
    )


# ---------------------------------------------------------------
# 4.2 文本标记解析（替代 JSON 解析）
#
#     为什么放弃 JSON？
#       JSON 模式要模型严格按结构输出，一旦模型"发挥"了，
#       整段内容就全废了。而"文本标记法"只是让模型写三行带标记的文字，
#       就算它格式写得乱七八糟，我们也能用字符串切割把内容捞出来，
#       最差的情况是把全文当引导语 —— 永远不会整个解析失败。
# ---------------------------------------------------------------

# 三个字段的"标记正则"。
#
# 为什么要用正则而不是简单的 text.find("【知识点】")？
#   因为模型写法五花八门：全角括号、半角括号、只写冒号、
#   markdown 加粗、括号漏掉一半……全都得认。
#
# 关键设计：标记【必须】带括号或冒号才算数。
#   如果只匹配光秃秃的"知识点"三个字，那么引导语里
#   本来就可能出现"这道题考查的知识点是…"，会误判。
_MARKER_PATTERNS = {
    "knowledge_point": (
        r"(?:[\[【]\s*知\s*识\s*点\s*[\]】]"      # 【知识点】 或 [知识点]
        r"|[\[【]\s*知\s*识\s*点\s*[：:]\s*[\]】]"
        r"|\*\*\s*知\s*识\s*点\s*\*\*"            # **知识点**
        r"|知\s*识\s*点\s*[：:])"                  # 知识点：
    ),
    "error_type": (
        r"(?:[\[【]\s*错\s*因\s*[\]】]"
        r"|[\[【]\s*错\s*因\s*[：:]\s*[\]】]"
        r"|\*\*\s*错\s*因\s*\*\*"
        r"|错\s*因\s*[：:]"
        r"|[\[【]\s*错\s*误\s*类\s*型\s*[\]】]"
        r"|[\[【]\s*错\s*误\s*原\s*因\s*[\]】])"
    ),
    "response_text": (
        r"(?:[\[【]\s*引\s*导\s*语\s*[\]】]"
        r"|[\[【]\s*引\s*导\s*语\s*[：:]\s*[\]】]"
        r"|\*\*\s*引\s*导\s*语\s*\*\*"
        r"|引\s*导\s*语\s*[：:]"
        r"|[\[【]\s*回\s*复\s*[\]】]"
        r"|[\[【]\s*解\s*答\s*[\]】])"
    ),
    # ★ 第四个标记：告诉后端"这一轮的教学进展"
    "status": (
        r"(?:[\[【]\s*状\s*态\s*[\]】]"
        r"|[\[【]\s*状\s*态\s*[：:]\s*[\]】]"
        r"|状\s*态\s*[：:])"
    ),
    # ★ 第五、第六个标记：错因的"分类"和"详细分析"要分开存
    #   分类只有 7 个固定选项，专门用来画统计图表（饼图才干净）
    #   分析是给学生看的详细说明（50 字以内）
    "error_category": (
        r"(?:[\[【]\s*错\s*因\s*分\s*类\s*[\]】]"
        r"|[\[【]\s*错\s*因\s*分\s*类\s*[：:]\s*[\]】]"
        r"|错\s*因\s*分\s*类\s*[：:])"
    ),
    "error_analysis": (
        r"(?:[\[【]\s*错\s*因\s*分\s*析\s*[\]】]"
        r"|[\[【]\s*错\s*因\s*分\s*析\s*[：:]\s*[\]】]"
        r"|错\s*因\s*分\s*析\s*[：:])"
    ),
}

# AI 写的【状态】文字 -> 我们数据库里的 status 值
# 只要 AI 写的词里包含左边任意一个关键词，就映射成右边的状态
STATUS_KEYWORD_MAP = (
    ("已解决", "solved"),
    ("解决了", "solved"),
    ("做对", "solved"),
    ("答对", "solved"),
    ("正确", "solved"),
    ("完成", "solved"),
    ("需要诊断", "guiding"),      # 变式题做错了，要重新诊断（这一轮会带标签）
    ("做错", "guiding"),
    ("练习中", "practicing"),
    ("变式", "practicing"),
    ("引导中", "guiding"),
    ("引导", "guiding"),
)

# 数据库里的状态值 -> 中文说明（打日志用）
STATUS_CN = {
    "diagnosing": "首次诊断",
    "guiding": "引导追问",
    "solved": "已解决",
    "practicing": "变式练习",
}


def map_status_text(text: str, fallback: str = "guiding") -> str:
    """把 AI 写的【状态】文字，翻译成数据库里的状态值。"""
    if not text:
        return fallback

    for keyword, status in STATUS_KEYWORD_MAP:
        if keyword in text:
            return status

    return fallback

# 兜底用的默认值。故意不用"未识别"这种冷冰冰的字眼。
DEFAULT_ERROR_TYPE = "待补充"
DEFAULT_KNOWLEDGE = "待补充"


def _short_label(value: str, max_len: int = 120) -> str:
    """
    把一段文字收拾成"标签"该有的样子。

    做两件事：
      1. 只取第一行（防止【引导语】标记缺失时，
         【错因】把后面整段引导语都吞进来）
      2. 限制最大长度，但【优先在句末标点处断开】，
         保证切出来的还是一句完整的话

    ⚠️ max_len 千万不能设小！
       之前这里默认是 20，结果"错因"稍微写长一点
       （比如 50 个字）就被硬砍成 20 个字，
       再好的前端也救不回来 —— 数据在进数据库之前就已经没了。
       现在放宽到 120，只用来挡住"整段话被吞进来"这种极端情况。
    """
    if not value:
        return ""

    # 第 1 步：只取第一行
    first_line = value.split("\n")[0]
    first_line = first_line.strip().strip("：: ").strip()

    if len(first_line) <= max_len:
        return first_line

    # 第 2 步：太长了要截，但优先切在句末标点之后，保证句子完整
    cut = first_line[:max_len]
    for punct in ("。", "！", "？", "；", ".", "!", "?", ";"):
        pos = cut.rfind(punct)
        # 至少保留一半内容，免得切得太碎反而看不懂
        if pos > max_len * 0.5:
            return cut[:pos + 1]

    return cut
def _clean_ai_text(text: str) -> str:
    """先把 AI 回复里多余的包装清掉（markdown 代码块、多余空行）。"""
    if not text:
        return ""

    text = text.strip()

    # 去掉整段被 ``` 包起来的情况
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]                       # 去掉第一行 ``` 或 ```text
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]                  # 去掉最后一行 ```
        text = "\n".join(lines).strip()

    return text


def _guess_knowledge_point(text: str) -> str:
    """
    知识点实在提取不到时，从正文里"猜"一个。

    规则：取开头 12 个字，但【必须】看起来像个知识点词条。
    怎么判断？
        知识点是短词条（"一元一次方程"），不会有句号、问号。
        如果开头就是一句完整的话（"我们先不急着对答案。"），
        那说明猜不出来，宁可返回"待补充"，也不要往数据库里
        塞一句没意义的话 —— 否则学习报告的柱状图上会出现
        "我们先不急着对答案"这种鬼东西，反而更难看。
    """
    if not text:
        return DEFAULT_KNOWLEDGE

    head = text[:12].strip()
    # 去掉标记残留和标点
    head = re.sub(r"^[\[【\s]*", "", head).strip()

    # ★ 关键：看【更宽】的窗口里有没有标点。
    #   只看 12 个字不行 —— 有些句子的逗号正好在第 13 个字，
    #   那样就会把半句话当成知识点。
    #   知识点是短词条（"一元一次方程"），不会有任何句读符号。
    window = text[:20]
    if re.search(r"[。！？!?，,；;、：:]", window):
        return DEFAULT_KNOWLEDGE

    if len(head) < 2:
        return DEFAULT_KNOWLEDGE

    return head


def extract_ai_data(text: str) -> dict:
    """
    【核心】从 AI 的回复里提取知识点、错因、引导语。

    这是整个解析流程的入口，目标只有一个：**无论 AI 写成什么样，都不失败**。

    ── 提取原理 ──
      1. 用正则找出三个标记各自的【位置】（兼容全角/半角括号、冒号、加粗等写法）
      2. 按位置排序，每个字段的内容 = 从自己标记之后，到下一个标记之前
      3. 排在最后的字段自然就是"标记之后的所有文字"

    ── 三层兜底（对应你提的需求）──
      第一层：引导语提取失败 -> 把【错因】之后的所有内容都当引导语
      第二层：知识点提取不到 -> 从正文开头猜一个词条
      第三层：错因提取不到   -> 写"待补充"

    返回的字典里三个 key 一定都在，而且都不会是空字符串。
    """
    result = {
        "knowledge_point": "",
        "error_type": "",
        "error_category": "",     # 固定分类（7 选 1）
        "response_text": "",
        "status": "",          # AI 写的【状态】原文，比如"已解决"
        # ★ AI 这一轮到底有没有主动写【知识点】/【错因】？
        #   这很重要：引导轮次 AI 是不写标签的，
        #   如果我们硬把兜底的"待补充"存进数据库，
        #   前端就会显示出一个假的标签，界面又乱了。
        "has_tags": False,
    }

    cleaned = _clean_ai_text(text)
    if not cleaned:
        result["knowledge_point"] = DEFAULT_KNOWLEDGE
        result["error_type"] = DEFAULT_ERROR_TYPE
        return result

    # ---- 第 1 步：找出所有标记的位置 ----
    hits = []      # 每一项是 (位置, 结束位置, 字段名)
    for field, pattern in _MARKER_PATTERNS.items():
        match = re.search(pattern, cleaned)
        if match:
            hits.append((match.start(), match.end(), field))

    # ---- 一个标记都没有：整段当引导语 ----
    if not hits:
        result["response_text"] = cleaned
        result["knowledge_point"] = _guess_knowledge_point(cleaned)
        result["error_type"] = DEFAULT_ERROR_TYPE
        return result

    hits.sort(key=lambda item: item[0])

    # ---- 第 2 步：按位置把内容切开 ----
    positions = {}
    for index, (start, end, field) in enumerate(hits):
        # 结束位置 = 下一个标记的开头；已经是最后一个就到文本末尾
        next_start = hits[index + 1][0] if index + 1 < len(hits) else len(cleaned)
        value = cleaned[end:next_start]
        # 去掉前后空白、换行，以及模型可能多写的冒号
        value = value.strip().strip("：:").strip()
        positions[field] = value

    result["knowledge_point"] = _short_label(positions.get("knowledge_point", ""), 30)

    # 详细的错因分析：优先用【错因分析】，没有就退回旧的【错因】
    error_detail = positions.get("error_analysis", "") or positions.get("error_type", "")
    result["error_type"] = _short_label(error_detail, 120)

    # 固定分类：优先用 AI 写的【错因分类】，没有就靠关键词猜一个
    result["error_category"] = map_error_category(
        positions.get("error_category", "") or error_detail
    )

    result["response_text"] = positions.get("response_text", "")
    result["status"] = _short_label(positions.get("status", ""), 12)

    # ★ 保险丝：直接用字符串再判一次。
    #   万一标记正则因为模型写法太怪没匹配上，这一句还能救回来。
    #   只认带标记的写法（比如"【状态】已解决"），不去正文里瞎猜，
    #   免得把"这道题还没有解决"这种话误判成已完成。
    if not result["status"]:
        for phrase in ("【状态】已解决", "状态：已解决", "状态:已解决"):
            if phrase in cleaned:
                result["status"] = "已解决"
                break

    # AI 是否真的写了标签？（引导轮次它不会写，我们不能替它编）
    result["has_tags"] = any(
        h[2] in ("knowledge_point", "error_type", "error_analysis", "error_category")
        for h in hits
    )

    # ---- 第 3 步：三层兜底 ----

    # 兜底一：引导语没提取到 -> 把【错因】之后所有内容当引导语
    if not result["response_text"]:
        error_hit = next((h for h in hits if h[2] == "error_type"), None)
        if error_hit:
            tail = cleaned[error_hit[1]:].strip().strip("：:").strip()
            # 去掉可能残留的【引导语】标记本身
            tail = re.sub(r"^[\[【]\s*引\s*导\s*语\s*[\]】]\s*[：:]?\s*", "", tail)
            if tail:
                result["response_text"] = tail

    # 引导语还是空 -> 整段都用上（总比没有好）
    if not result["response_text"]:
        result["response_text"] = cleaned

    # 兜底二：知识点没提取到 -> 从正文猜一个
    if not result["knowledge_point"]:
        result["knowledge_point"] = _guess_knowledge_point(
            result["response_text"] or cleaned
        )

    # 兜底三：错因没提取到 -> "待补充"
    if not result["error_type"]:
        result["error_category"] = result["error_category"] or "其他"
        result["error_type"] = DEFAULT_ERROR_TYPE

    return result


def _strip_code_fence(text: str) -> str:
    """
    去掉 AI 可能在外面包的 markdown 代码块。

    虽然提示词里说了不要用代码块，但 AI 有时还是会输出：
        ```json
        {"knowledge_point": "..."}
        ```
    所以我们主动兼容一下，把 ``` 那两行去掉。
    """
    text = text.strip()
    if not text.startswith("```"):
        return text

    lines = text.split("\n")
    lines = lines[1:]                            # 去掉第一行（``` 或 ```json）
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]                       # 去掉最后一行 ```
    return "\n".join(lines).strip()


def _parse_ai_json(content: str) -> dict:
    """把 AI 返回的文本解析成字典，尽量宽容一些。"""

    # DeepSeek 官方文档提到：开启 JSON 模式时有概率返回空内容
    if not content or not content.strip():
        raise AIResponseError("AI 这次返回了空内容，请再试一次")

    text = _strip_code_fence(content)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 再试一次：只截取第一个 { 到最后一个 } 之间的部分
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise AIResponseError("AI 返回的内容不是合法的 JSON 格式")
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise AIResponseError("AI 返回的内容不是合法的 JSON 格式")

    if not isinstance(data, dict):
        raise AIResponseError("AI 返回的 JSON 不是一个对象")

    return data


def _normalize(data: dict) -> dict:
    """
    把 AI 返回的字典整理成统一的三个字段。

    做两件保险的事：
      1. 兼容 AI 用中文字段名的情况（知识点 / 错因 / 引导语）
      2. 保证三个字段都不会是 None，前端拿到的永远是可以直接显示的字符串
    """

    def pick(*names: str) -> str:
        for name in names:
            value = data.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    knowledge_point = pick("knowledge_point", "知识点")
    error_type = pick("error_type", "错误类型", "错因")
    response_text = pick(
        "response_text", "引导语", "ai_response", "response", "content"
    )

    # 三个都没拿到，说明 AI 跑偏了
    if not knowledge_point and not error_type and not response_text:
        raise AIResponseError(
            "AI 这次没有按【知识点】【错因】【引导语】的格式输出，"
            "而且内容也是空的，请再试一次。",
            code="bad_format",
        )

    return {
        "knowledge_point": knowledge_point or DEFAULT_KNOWLEDGE,
        "error_type": error_type or DEFAULT_ERROR_TYPE,
        "error_category": (data.get("error_category") or "其他"),
        "response_text": response_text or "AI 这次没有给出引导语，请再试一次。",
        # ★ 把【状态】原样带出去，上层用它决定会话进入哪个阶段
        "status": (data.get("status") or "").strip(),
        # ★ 原样带出去：AI 这一轮到底有没有写标签
        "has_tags": bool(data.get("has_tags")),
    }


def _explain_http_error(response: httpx.Response) -> str:
    """把 HTTP 错误码翻译成高中生能看懂的话。"""

    code = response.status_code

    # 尽量把 DeepSeek 返回的原始错误信息也带上，方便排查
    try:
        body = response.json()
        detail = body.get("error", {}).get("message", "") or str(body)[:200]
    except Exception:
        detail = (response.text or "")[:200]

    hints = {
        400: "请求格式有问题",
        401: "API Key 无效或填错了，请检查 .env 里的 DEEPSEEK_API_KEY",
        402: "DeepSeek 账户余额不足，请到 platform.deepseek.com 充值",
        403: "没有权限使用这个模型",
        404: (
            f"模型名 '{DEEPSEEK_MODEL}' 不存在。请到 platform.deepseek.com "
            "查看你可用的模型名，再修改 .env 里的 DEEPSEEK_MODEL"
        ),
        422: "请求参数有误",
        429: "请求太频繁或已达限额，稍等一会儿再试",
        500: "DeepSeek 服务器内部错误",
        502: "DeepSeek 网关错误",
        503: "DeepSeek 服务器繁忙，请稍后再试",
    }

    hint = hints.get(code, "未知错误")
    return f"AI 调用失败（HTTP {code}）：{hint}。原始信息：{detail}"


# ---------------------------------------------------------------
# 4.5 统一的 DeepSeek 调用函数
#
#     错题诊断、变式题、图片 OCR 三个功能都要"发请求 -> 取正文"，
#     以前是三段几乎一样的代码。现在抽成一个函数，
#     好处是：超时控制、自动重试、错误日志只需要写一遍，
#     以后改一处三个功能一起生效。
# ---------------------------------------------------------------

def _diagnose_empty_content(body: dict, what: str) -> str:
    """
    当 AI 返回的正文是空的时候，尽量分析出真正的原因，
    并把完整的原始返回打印到终端，返回一句人能看懂的说明。

    为什么要专门做这个？
    因为"空内容"有好几种完全不同的原因，
    笼统地说一句"AI 返回了空内容"根本没法排查。
    """
    try:
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
    except Exception:
        choice, message = {}, {}

    finish_reason = choice.get("finish_reason")
    usage = body.get("usage") or {}
    reasoning = message.get("reasoning_content") or ""

    print("=" * 64)
    print(f"[智愈错题] ⚠ AI 返回了空内容（{what}）")
    print(f"[智愈错题]   finish_reason = {finish_reason}")
    print(f"[智愈错题]   usage         = {usage}")
    if reasoning:
        print(f"[智愈错题]   但 reasoning_content 里有 {len(reasoning)} 个字")
    print("[智愈错题]   完整原始返回（截断到 2000 字）：")
    print(json.dumps(body, ensure_ascii=False)[:2000])
    print("=" * 64)

    # 情况 1：被长度限制截断了
    if finish_reason == "length":
        return (
            "AI 的回复被长度限制截断了（finish_reason=length）。"
            "请把 .env 里的 AI_MAX_TOKENS 调大（比如 4000），然后重启后端。"
        )

    # 情况 2：被内容安全过滤
    if finish_reason == "content_filter":
        return "AI 的内容被安全策略拦截了，换个说法再试一次。"

    # 情况 3：开了"思考模式"，正文和思考过程分家了
    if reasoning:
        return (
            "AI 把内容都写进了「思考过程」里，正文是空的。"
            "这是模型的思考模式导致的，把上面终端日志里的 reasoning_content "
            "发给开发者看看，或者再点一次发送试试。"
        )

    # 情况 4：官方文档里提到过的"JSON 模式偶发返回空内容"
    return (
        "AI 这次返回了空内容。这是 DeepSeek 官方文档里提到过的偶发情况"
        "（JSON 模式有概率返回空 content），已经自动重试过一次仍然为空。"
        "请再点一次发送，一般就好了。"
    )


async def _call_deepseek(payload: dict, what: str = "对话") -> str:
    """
    把请求发给 DeepSeek，并把回复的正文取回来。

    参数：
        payload  发给 DeepSeek 的请求体（一个字典）
        what     这次调用是干什么的，只用来打日志

    返回：
        AI 回复的正文（保证是非空的字符串）

    失败时抛出 AIServiceError 的子类，并且一定会在终端打印出原因。
    """

    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }

    # ★ 思考模式参数
    #
    #   auto（默认）：【不加这个字段】，用服务端默认行为。
    #                 实测证明这是最稳的——思考内容会正常放进 reasoning_content，
    #                 正文 content 是完整正常的 JSON。
    #
    #   on / off   ：显式指定。注意 off 实测会让 content 变成一堆空格，
    #                 除非你明确知道自己在干什么，否则别用。
    #
    #   dict(payload) 是复制一份，避免改到调用方传进来的字典。
    payload = dict(payload)

    if AI_THINKING_MODE in ("on", "1", "true", "yes", "enabled"):
        payload["thinking"] = {"type": "enabled"}
        log_info("[智愈错题] 思考模式：显式打开")
    elif AI_THINKING_MODE in ("off", "0", "false", "no", "disabled"):
        payload["thinking"] = {"type": "disabled"}
        log_error("[智愈错题] ⚠ 思考模式：显式关闭 —— 实测这会导致返回空白，慎用！")
    else:
        # auto：什么都不加，保持服务端默认
        pass

    # 把超时拆成几段分别设置，比只写一个数字精确得多。
    # 这样超时的时候能一眼看出是"连不上"还是"AI 想太久"。
    timeout = httpx.Timeout(
        connect=15.0,               # 连上 DeepSeek 服务器最多等 15 秒
        read=DEEPSEEK_TIMEOUT,      # ★ 连上后等 AI 回复最多等多久（复杂题卡这里）
        write=60.0,                 # 把我们的请求发出去最多等 60 秒
        pool=15.0,                  # 从连接池拿一个空闲连接最多等 15 秒
    )

    # ---------------------------------------------------------------
    # 空白内容可能有好几种原因（JSON 模式限制、模型钻牛角尖……），
    # 与其一条路走到黑，不如准备几套参数，一种不行就换一种。
    #
    # 诊断依据：你的日志里 completion_tokens=74，
    # 而 content 是 74 个空格 —— 说明模型"答了"，只是答的全是空白。
    # 这种可复现的空白，多半是 response_format=json_object 逼出来的，
    # 所以第 2、3 套策略都去掉了它（我们本来就有很宽容的 JSON 解析器，
    # 模型就算输出 ```json 包裹或者前后带废话，也能正常抠出来）。
    # ---------------------------------------------------------------
    strategies = (
        ("标准参数（温度 0.7）", {}),
        ("提高温度 + 重复惩罚（打破重复循环）",
         {"temperature": 1.0, "frequency_penalty": 0.4}),
        ("降低温度（更老实）", {"temperature": 0.3}),
    )

    last_empty_reason = "AI 返回了空内容"
    total = len(strategies)

    for index, (strategy_name, overrides) in enumerate(strategies, start=1):

        # 按这次的策略，微调请求体
        this_payload = dict(payload)
        this_payload.update(overrides)

        log_info(
            f"[智愈错题] → 调用 DeepSeek（{what}）第 {index}/{total} 次 | "
            f"策略：{strategy_name} | 模型={DEEPSEEK_MODEL} | "
            f"读超时={DEEPSEEK_TIMEOUT:.0f}s | "
            f"max_tokens={this_payload.get('max_tokens', '?')} | "
            f"temperature={this_payload.get('temperature', '?')}"
        )

        # ★ 把完整请求体打印出来（去掉 messages，因为它太长了；
        #   也绝对不会打印 API Key —— Key 在 headers 里，不在 body 里）。
        #   这样你就能亲眼核对"到底发了哪个模型名"。
        _debug_body = {
            k: v for k, v in this_payload.items() if k != "messages"
        }
        _debug_body["messages"] = (
            f"<共 {len(this_payload.get('messages', []))} 条，"
            f"含 system 提示词 {len(str(this_payload.get('messages', [{}])[0].get('content', '')))} 字>"
        )
        log_info(
            "[智愈错题]   实际请求体："
            + json.dumps(_debug_body, ensure_ascii=False)
        )

        # ---------- 发请求 ----------
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url, json=this_payload, headers=headers
                )

        except httpx.TimeoutException as exc:
            # ================= 超时 =================
            # 这是复杂题目最常见的失败。用红色打印，方便在一堆日志里一眼看到。
            log_error("=" * 64)
            log_error(f"[智愈错题] API Request Timeout after {DEEPSEEK_TIMEOUT:.0f}s")
            log_error(f"[智愈错题] 功能：{what}")
            log_error(f"[智愈错题] 异常类型：{type(exc).__name__}")
            log_error(f"[智愈错题] 详细信息：{exc!r}")
            log_error(f"[智愈错题] 模型：{DEEPSEEK_MODEL}")
            log_error(f"[智愈错题] max_tokens：{payload.get('max_tokens', '?')}")
            log_error("[智愈错题] 说明：AI 在 30 秒内没想完。复杂题目请把 .env 里的")
            log_error("[智愈错题]       DEEPSEEK_TIMEOUT 调大（比如 120），再重启后端。")
            log_error("=" * 64)

            # 返回给前端的提示：友好 + 能操作
            raise AIRequestError(
                f"AI 导师正在深度思考中，请再试一次"
                f"（等待超过 {DEEPSEEK_TIMEOUT:.0f} 秒自动中断）",
                code="timeout",
            )

        except httpx.RequestError as exc:
            log_error("-" * 64)
            log_error(f"[智愈错题] 网络错误（{what}）：{type(exc).__name__}: {exc}")
            log_error("-" * 64)
            raise AIRequestError(
                f"连不上 DeepSeek（{type(exc).__name__}）：{exc}。"
                "请检查网络，或者 .env 里的 DEEPSEEK_BASE_URL 是否正确。",
                code="network",
            )

        # ---------- 状态码不是 200 ----------
        if response.status_code != 200:
            raw = (response.text or "")[:1500]
            log_error("-" * 64)
            log_error(f"[智愈错题] HTTP {response.status_code}（{what}）")
            log_error(f"[智愈错题] 服务端返回：{raw}")
            log_error("-" * 64)
            raise AIRequestError(
                _explain_http_error(response),
                code=f"http_{response.status_code}",
            )

        # ---------- 把返回解析成 JSON ----------
        try:
            body: Any = response.json()
        except ValueError as exc:
            print(f"[智愈错题] ✗ 返回的不是合法 JSON（{what}）：{exc}")
            print(f"[智愈错题]   原始内容：{(response.text or '')[:1500]}")
            raise AIResponseError(
                f"DeepSeek 返回的不是 JSON（{exc}）。具体内容见后端终端日志。",
                code="bad_json",
            )

        # ---------- 取出正文和思维链 ----------
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            log_error(f"[智愈错题] 返回结构看不懂（{what}）：{type(exc).__name__}: {exc}")
            log_error(f"[智愈错题]   完整返回：{json.dumps(body, ensure_ascii=False)[:1500]}")
            raise AIResponseError(
                "DeepSeek 返回的数据结构和预期不一样。详情见后端终端日志。",
                code="bad_structure",
            )

        content = (message.get("content") or "").strip()
        reasoning = (message.get("reasoning_content") or "").strip()

        # ---------- 情况 1：正文正常，收工 ----------
        if content:
            usage = body.get("usage") or {}
            log_ok(
                f"[智愈错题] ✓ 成功（{what}）| 正文 {len(content)} 字 | "
                f"finish_reason={body['choices'][0].get('finish_reason')} | "
                f"total_tokens={usage.get('total_tokens', '?')}"
            )
            return content

        # ---------- 情况 2：正文是空的，但思维链里有东西 ----------
        # 这正是你遇到的情况：思考模式没关，模型把内容全写进 reasoning_content 了。
        if reasoning:
            salvaged = _salvage_from_reasoning(reasoning)

            if salvaged:
                log_error("!" * 64)
                log_error("[智愈错题] ⚠ 正文是空的，但从 reasoning_content 里捞到了内容")
                log_error(f"[智愈错题]   思维链长度：{len(reasoning)} 字")
                log_error(f"[智愈错题]   捞出的长度：{len(salvaged)} 字")
                log_error("[智愈错题]   ★ 注意：不要传 thinking=disabled 来试图解决，")
                log_error("[智愈错题]     实测那会让 content 变成一堆空格。保持 AI_THINKING=auto。")
                log_error("!" * 64)
                return salvaged

            log_error(f"[智愈错题] 正文空、思维链里也没捞出可用内容（{len(reasoning)} 字）")

        # ---------- 情况 3：两边都空 ----------
        # 特别注意：如果 completion_tokens 明显大于 0，但 content 全是空白，
        # 说明模型"答了"，只是答的全是空格 —— 这不是偶发故障，是参数不合适。
        completion_tokens = (body.get("usage") or {}).get("completion_tokens", 0)

        if completion_tokens and completion_tokens > 0:
            log_error(
                f"[智愈错题] ★ 关键线索：模型生成了 {completion_tokens} 个 token，"
                f"但 content 全是空白（长度 {len(content)}）"
            )
            log_error("[智愈错题]   这不属于官方说的'偶发空内容'，是可复现的参数问题")

        last_empty_reason = _diagnose_empty_content(body, what)

        if index < total:
            log_error(
                f"[智愈错题] 第 {index} 次返回空白内容，"
                f"换下一套参数重试（{total - index} 次机会）..."
            )

    # 所有策略都试过了还是空
    raise AIResponseError(last_empty_reason, code="empty_content")


# ---------------------------------------------------------------
# 5. 对外的主函数
# ---------------------------------------------------------------

async def generate_reply(history: list[dict], status: str = "diagnosing") -> dict:
    """
    带着聊天历史，向 DeepSeek 要下一轮回复。

    参数 history 是"到目前为止的全部对话"，
    最后一条通常是学生刚发出的那句话。

    成功时返回：
        {
            "knowledge_point": "一元一次方程",
            "error_type": "计算失误",
            "response_text": "你刚才说移项后变成负号，那我们看看……"
        }

    失败时抛出 AIServiceError 的子类。
    """

    # ---- 检查配置 ----
    if not is_configured():
        raise AIConfigError(
            "还没有配置 DeepSeek API Key。请在项目根目录新建 .env 文件，"
            "写入 DEEPSEEK_API_KEY=sk-你的密钥，然后重启后端。"
        )

    # ---- 整理历史 ----
    context = build_context_messages(history)
    if not context:
        raise AIRequestError("对话历史是空的，没法发给 AI")

    # ---- 组装请求内容 ----
    # 顺序很重要：
    #   第 1 条    system        —— 你是什么身份、要守什么规矩
    #   中间若干条 user/assistant —— 之前聊过的内容（这就是"记忆"）
    #   最后一条   user          —— 学生刚说的话
    payload = {
        "model": DEEPSEEK_MODEL,
        # ★ 提示词随会话状态变化：首次诊断要标签，后续引导不要标签
        "messages": [
            {"role": "system", "content": build_system_prompt(status)}
        ] + context,
        # ★ 不用 response_format 了！让模型自由输出纯文本，
        #   我们自己用"文本标记法"把三个字段切出来。
        #   （JSON 模式对模型约束太强，一旦模型不听话就整段报废）
        "temperature": 0.7,
        # 复杂题目的回复会比较长，给足空间
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }

    # 发送请求的活儿交给统一的 _call_deepseek，
    # 超时、重试、错误日志都在那里处理
    content = await _call_deepseek(payload, what="错题诊断")

    # ---- 用文本标记法切出三个字段 ----
    result = _normalize(extract_ai_data(content))
    result["history_count"] = len(context)     # 方便调试：这次带了多少条历史
    return result


async def analyze_error(error_text: str) -> dict:
    """
    兼容旧版的单轮接口：只给一道错题，没有上下文。

    其实内部就是"只有一条消息的对话"。
    新的 /api/chat 接口请直接用 generate_reply()。
    """
    return await generate_reply([{"role": "user", "content": error_text}])


# ---------------------------------------------------------------
# 6. 举一反三：生成同类型的变式练习题
#
#    和上面的 generate_reply 用的是同一套调用流程，
#    只是换了一份系统提示词（这次要它出题，而不是引导）。
# ---------------------------------------------------------------

VARIANT_SYSTEM_PROMPT = """你是一位初中数学老师。学生刚刚做错了一道题，现在需要一道【同类型的变式练习题】来巩固。

【你要做的事】
读一读上面的对话，找到学生做错的那道题，
然后出一道考查【同一个知识点】、但换了数字或情境的新题。

【必须遵守的原则】
1. 只出题目，绝对不能给出答案，也不能给出完整的解题过程。
2. 新题要和原题"同类型但不同题"：最好换一个情境或换一种问法，
   而不是只把原来的数字改一改。
3. 难度和原题相当，适合初中生独立完成。
4. 题目最后附上 2 条解题提示。提示是"思路上的提醒"，
   比如"先想想这道题要求的是什么"，绝对不能直接把答案说出来。

【三个输出字段的写法】
- 【知识点】沿用原题的知识点，12 个字以内。
- 【错因】固定就填"变式练习"这四个字（系统靠它区分练习题和诊断结果）。
- 【引导语】这一轮的完整内容，格式是：
      【变式练习】<题目正文>
      （空一行）
      💡 提示 1：<提示>
      💡 提示 2：<提示>

【输出格式 —— 严格遵守】
不要输出 JSON，不要用 markdown 代码块。就按下面这样输出纯文本：

【知识点】一元一次方程
【错因】变式练习
【引导语】【变式练习】小明买 3 本笔记本和 1 支笔一共花了 20 元，已知一支笔 5 元，请问一本笔记本多少钱？

💡 提示 1：先想清楚"一共花的钱"是由哪几部分组成的。
💡 提示 2：设笔记本的单价为 x，试着把题目里的关系写成一个等式。

三个标记必须都出现，【引导语】后面可以换行、可以写多句。
"""


async def generate_variant(
    history: list[dict],
    knowledge_point: str,
) -> dict:
    """
    根据之前的对话，生成一道同知识点的变式练习题。

    参数：
        history         这个会话之前的聊天记录（用来让 AI 知道原题是什么）
        knowledge_point 要考查的知识点

    返回：
        {
            "knowledge_point": "一元一次方程",
            "error_type": "变式练习",
            "response_text": "【变式练习】...\\n\\n💡 提示 1：...\\n💡 提示 2：..."
        }
    """

    if not is_configured():
        raise AIConfigError(
            "还没有配置 DeepSeek API Key。请在项目根目录新建 .env 文件，"
            "写入 DEEPSEEK_API_KEY=sk-你的密钥，然后重启后端。"
        )

    context = build_context_messages(history)
    if not context:
        raise AIRequestError("这个会话还没有聊天记录，没法出变式题")

    # 在历史后面追加一条"指令"，告诉 AI 现在要做什么
    instruction = {
        "role": "user",
        "content": (
            f"请根据上面那道题，出一道考查「{knowledge_point}」的同类变式练习题。"
            "只出题目和提示，不要给答案。\n\n"
            # ★ 需求里强制要求加上的这句话
            f"出完题后，请把这句话原样附在题目后面：「{VARIANT_INSTRUCTION}」"
        ),
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": (
            [{"role": "system", "content": VARIANT_SYSTEM_PROMPT}]
            + context
            + [instruction]
        ),
        # ★ 同样不用 response_format，改用文本标记法
        # 出题要稳定一点，温度调低
        "temperature": 0.8,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }

    content = await _call_deepseek(payload, what="生成变式题")

    result = _normalize(extract_ai_data(content))

    # 保险起见：不管 AI 填了什么，error_type 一律强制标成"变式练习"，
    # 这样学习报告才能准确地把练习题排除在外。
    result["error_type"] = "变式练习"
    if not result.get("knowledge_point"):
        result["knowledge_point"] = knowledge_point

    result["history_count"] = len(context)
    return result


# ---------------------------------------------------------------
# 7. 图片 OCR：从错题图片里提取文字
#
#    ⚠️ 重要：这一步【不需要】单独的接口，也【不需要】换模型。
#
#    官方文档（https://api-docs.deepseek.com/zh-cn/guides/vision/）写得很清楚：
#      "deepseek-flash 模型支持在文本之外输入图片"
#    也就是说，视觉能力是 deepseek-flash 这个模型【自带】的，
#    只是发送时要把 content 从"一个字符串"改成"一个块数组"：
#
#      普通文字：  "content": "你好"
#      带图片：    "content": [
#                     {"type": "text",      "text": "帮我识别这张图"},
#                     {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
#                  ]
#
#    另外，网上有些老教程会写 model="deepseek-v4-flash-vision-exp"。
#    这个名字官方标注为"已下线"，虽然还能调用，但请求其实是被
#    最新的 Flash 模型接走的。所以直接用 .env 里的 DEEPSEEK_MODEL 就行。
#
#    官方限制（也写在上面那个链接里）：
#      · 支持格式：JPEG / PNG / GIF / WebP（按文件真实内容判断，不看文件名）
#      · 单张图片最大 32 MiB，整个请求体最大 48 MiB
#      · 图片只允许出现在 user 消息里
# ---------------------------------------------------------------

# 允许的图片类型
ALLOWED_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")

# base64 字符串的长度上限（约 6 MB 的原图）。
# 前端会先把图片压缩到 1 MB 左右再传，所以正常情况远达不到这个值。
MAX_IMAGE_BASE64_CHARS = 8 * 1024 * 1024

# 让 AI 只做"抄写"，不要自由发挥
OCR_PROMPT = """请把这张图片里的题目文字完整、准确地提取出来。

【必须遵守】
1. 只输出图片里真实存在的文字。不要添加任何解释、评论、答案或你的推测。
2. 数学符号用普通文本表示，例如：2x + 5 = 13、x²、√3、1/2、∠ABC。
3. 保留题目原有结构：题号、（1）（2）小问、选项 A/B/C/D、括号、单位都要保留。
4. 图片里有多道题时，按从上到下的顺序全部提取，题目之间空一行。
5. 如果图片模糊到看不清，或者里面根本没有文字，
   就只回复这五个字符：__NO_TEXT__

直接输出提取到的文字，不要用 markdown 代码块包裹，不要写"以下是识别结果"之类的话。"""


async def extract_text_from_image(image_base64: str, mime_type: str) -> str:
    """
    把一张错题图片交给 deepseek-flash 识别文字。

    参数：
        image_base64  图片的 base64 字符串（不含 "data:image/xxx;base64," 前缀）
        mime_type     图片类型，比如 "image/jpeg"

    返回：
        识别出来的文字（字符串）。识别不出内容时返回空字符串。

    失败时抛出 AIServiceError 的子类。
    """

    if not is_configured():
        raise AIConfigError(
            "还没有配置 DeepSeek API Key。请在项目根目录新建 .env 文件，"
            "写入 DEEPSEEK_API_KEY=sk-你的密钥，然后重启后端。"
        )

    # ---- 先做基本检查，别把明显不合法的数据发给 AI 浪费额度 ----
    if not image_base64 or not image_base64.strip():
        raise AIRequestError("没有收到图片数据")

    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise AIRequestError(
            f"不支持的图片格式：{mime_type}。"
            "只支持 JPEG、PNG、GIF、WebP 四种。"
        )

    if len(image_base64) > MAX_IMAGE_BASE64_CHARS:
        raise AIRequestError(
            "图片太大了（超过约 6 MB）。请压缩后再上传，或者拍小一点的照片。"
        )

    # ---- 拼成 data URL ----
    # 这就是官方文档里"Base64 编码图片（内联）"推荐的形式
    data_url = f"data:{mime_type};base64,{image_base64}"

    payload = {
        # ★ 就用平时那个模型，视觉是它自带的能力
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "user",          # 官方要求：图片只能放在 user 消息里
                "content": [
                    # 第 1 块：文字指令
                    {"type": "text", "text": OCR_PROMPT},
                    # 第 2 块：图片本身
                    # detail 选 "high" 保留原图细节，识别手写/小字更准
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "high"},
                    },
                ],
            }
        ],
        # OCR 不需要发散的创造力，温度调到最低，让它老老实实抄写
        "temperature": 0.1,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }

    text = await _call_deepseek(payload, what="图片识别")

    # AI 说"图里没文字"，就返回空字符串，让上层给用户友好提示
    if "__NO_TEXT__" in text:
        return ""

    return text

# 7 个固定的错因分类（学习报告只统计这 7 个，图表才干净）
ERROR_CATEGORIES = (
    "计算失误", "概念混淆", "审题不清", "步骤遗漏",
    "公式记错", "逻辑推理错误", "其他",
)

# ★ 兜底用：AI 忘了写【错因分类】时，靠关键词猜一个
CATEGORY_KEYWORDS = (
    ("概念混淆", ("概念", "定义域", "定义", "理解", "混淆", "误以为", "不清楚")),
    ("审题不清", ("审题", "看错题", "漏看", "没看清", "题目要求")),
    ("公式记错", ("公式", "定理", "记错", "记混", "背错")),
    ("步骤遗漏", ("遗漏", "漏了", "忘记写", "少写", "跳过", "步骤")),
    ("计算失误", ("计算", "算错", "粗心", "符号", "移项", "加减", "乘除")),
    ("逻辑推理错误", ("推理", "逻辑", "思路", "推导", "证明")),
)


def map_error_category(text: str) -> str:
    """
    把 AI 写的错因文字，归到 7 个固定分类里的一个。

    第一优先：AI 写的分类正好是 7 个之一 -> 直接用它
    兜底：靠关键词猜（比如含"定义域""概念"就归到"概念混淆"）
    最后：都猜不到，归到"其他"
    """
    if not text:
        return "其他"

    raw = text.strip()

    # 第一优先：AI 写的正好是 7 个分类之一
    for category in ERROR_CATEGORIES:
        if category in raw:
            return category

    # 第二优先：关键词映射
    for category, keywords in CATEGORY_KEYWORDS:
        for word in keywords:
            if word in raw:
                return category

    return "其他"

