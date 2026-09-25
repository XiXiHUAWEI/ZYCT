/**
 * 智愈错题 —— 前端脚本（v0.5 聊天界面版）
 *
 * 相比上一版（一个表单 + 一个列表），这一版变成了类似微信的聊天界面：
 *   左侧：会话列表（可以新建、切换、删除）
 *   右侧：聊天窗口（消息气泡 + 输入框）
 *
 * 涉及的接口：
 *   GET    /api/sessions/{student_id}   拿会话列表
 *   POST   /api/new_session             新建会话
 *   DELETE /api/sessions/{session_id}   删除会话
 *   GET    /api/messages/{session_id}   拿聊天记录
 *   POST   /api/chat                    发消息并拿 AI 回复（核心）
 */

// =============================================================
// 1. 配置
// =============================================================
const API_BASE = "http://127.0.0.1:8000";
const MAX_LOG_LINES = 200;

// =============================================================
// 2. 全局状态
//
//    聊天界面比表单复杂，有些数据需要在多个函数之间共享，
//    所以放在外面当"全局变量"。
// =============================================================
let currentStudentId = 1;      // 当前是哪个学生
let currentSessionId = null;   // 当前打开的是哪个会话（null = 还没选）
let sessions = [];             // 会话列表缓存
let isSending = false;         // 是不是正在等 AI 回复（防止重复发送）
let elapsedTimerId = null;     // "已等待 N 秒"的计时器编号

// =============================================================
// 3. 拿到页面元素
// =============================================================
const connBadge      = document.getElementById("conn-badge");
const aiWarningEl    = document.getElementById("ai-warning");
const studentIdInput = document.getElementById("student-id");
const newSessionBtn  = document.getElementById("new-session-btn");
const sessionListEl  = document.getElementById("session-list");

const chatTitleEl    = document.getElementById("chat-title");
const chatMetaEl     = document.getElementById("chat-meta");
const chatMessagesEl = document.getElementById("chat-messages");
const chatInput      = document.getElementById("chat-input");
const sendBtn        = document.getElementById("send-btn");
const sendSpinner    = document.getElementById("send-spinner");
const sendTextEl     = document.getElementById("send-text");

const logEl          = document.getElementById("ai-log");
const clearLogBtn    = document.getElementById("clear-log-btn");
const themeToggleBtn = document.getElementById("theme-toggle-btn");

const sidebarEl        = document.getElementById("sidebar");
const sidebarToggleBtn = document.getElementById("sidebar-toggle-btn");

const confirmModal     = document.getElementById("confirm-modal");
const confirmTitleEl   = document.getElementById("confirm-title");
const confirmTextEl    = document.getElementById("confirm-text");
const confirmOkBtn     = document.getElementById("confirm-ok");
const confirmCancelBtn = document.getElementById("confirm-cancel");

// 批量管理相关元素
const batchToggleBtn   = document.getElementById("batch-toggle-btn");
const batchBar         = document.getElementById("batch-bar");
const batchCountEl     = document.getElementById("batch-count");
const batchSelectAllBtn = document.getElementById("batch-select-all");
const batchClearBtn    = document.getElementById("batch-clear");
const batchDeleteBtn   = document.getElementById("batch-delete");

// 学习报告相关元素
const reportBtn      = document.getElementById("report-btn");
const reportModal    = document.getElementById("report-modal");
const reportCloseBtn = document.getElementById("report-close");
const reportSubtitle = document.getElementById("report-subtitle");
const reportBody     = document.getElementById("report-body");
const reportEmpty    = document.getElementById("report-empty");
const statSessions   = document.getElementById("stat-sessions");
const statQuestions  = document.getElementById("stat-questions");
const statDiagnosed  = document.getElementById("stat-diagnosed");

// 图片上传 / OCR 相关元素
const imageBtn        = document.getElementById("image-btn");
const imageInput      = document.getElementById("image-input");
const imagePreview    = document.getElementById("image-preview");
const imagePreviewImg = document.getElementById("image-preview-img");
const imagePreviewName = document.getElementById("image-preview-name");
const imagePreviewStatus = document.getElementById("image-preview-status");
const imageRemoveBtn  = document.getElementById("image-remove");

// OCR 相关的小状态
let ocrRunning = false;       // 是否正在识别，防止连点
let currentImageDataUrl = ""; // 当前预览图的 dataURL（清空时要用）

// =============================================================
// 3.1 批量管理状态
//
//     batchMode           是否处于"批量管理"模式
//     selectedSessionIds  被勾选的会话 id 集合（Set 会自动去重）
//
//     这个模式下：
//       · 每个会话左边出现复选框
//       · 点条目 = 勾选/取消勾选（不再切换会话，避免误触）
//       · 顶部出现全选 / 取消全选 / 删除选中
// =============================================================
let batchMode = false;

// 这个会话里最近一次诊断出的知识点（出变式题要用）
let sessionKnowledgePoint = "";
const selectedSessionIds = new Set();

// =============================================================
// 3.2 侧边栏收起 / 展开
//
//     只做一件事：给 #sidebar 加 / 去掉 collapsed 这个 class。
//     宽度变化和滑动动画全部由 CSS 负责。
//
//     右侧聊天区是 flex: 1，侧边栏让出的空间会被它自动吃掉，
//     所以不用写任何 JS 去调整聊天区宽度。
//
//     这个功能跟对话逻辑完全无关，收起侧边栏不会影响
//     当前打开的会话，也不会打断正在等的 AI 回复。
// =============================================================
const SIDEBAR_KEY = "zhixue-sidebar-collapsed";

/** 应用收起 / 展开状态。collapsed 为 true 表示收起。 */
function applySidebarCollapsed(collapsed) {
    sidebarEl.classList.toggle("collapsed", collapsed);
    document.body.classList.toggle("sidebar-collapsed", collapsed);

    sidebarToggleBtn.title = collapsed ? "展开会话侧边栏" : "收起会话侧边栏";
    sidebarToggleBtn.setAttribute("aria-label", sidebarToggleBtn.title);

    try {
        localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
    } catch (error) {
        /* 隐私模式可能不让用 localStorage，忽略 */
    }
}

/** 当前是不是收起状态。 */
function isSidebarCollapsed() {
    return sidebarEl.classList.contains("collapsed");
}

/** 切换收起 / 展开。 */
function toggleSidebar() {
    const next = !isSidebarCollapsed();
    applySidebarCollapsed(next);
    log(next ? "已收起侧边栏" : "已展开侧边栏");
}

// =============================================================
// 3.3 通用确认弹窗（替代原生 confirm）
//
//     showConfirm({...}) 返回一个 Promise：
//       用户点"确认" -> resolve(true)
//       点"取消" / 按 Esc / 点蒙层 -> resolve(false)
//
//     调用方式（注意前面要加 await）：
//         const ok = await showConfirm({ title: "...", text: "..." });
// =============================================================
function showConfirm(options) {
    return new Promise(function (resolve) {

        // 每次打开前先套用这次的文案
        confirmTitleEl.textContent = options.title || "确定要继续吗？";
        confirmTextEl.textContent = options.text || "";
        confirmOkBtn.textContent = options.okText || "确认";

        confirmModal.classList.remove("d-none");

        // 把这次用到的回调集中定义，方便等下统一解绑，
        // 不然多次打开会累积一堆重复的监听器
        function finish(result) {
            confirmModal.classList.add("d-none");

            confirmOkBtn.removeEventListener("click", onOk);
            confirmCancelBtn.removeEventListener("click", onCancel);
            confirmModal.removeEventListener("click", onMaskClick);
            document.removeEventListener("keydown", onKeyDown);

            resolve(result);
        }

        function onOk() { finish(true); }
        function onCancel() { finish(false); }

        // 点蒙层（弹窗外的灰色区域）也算取消
        function onMaskClick(event) {
            if (event.target === confirmModal) finish(false);
        }

        // 按 Esc 也算取消，这是弹窗的通用习惯
        function onKeyDown(event) {
            if (event.key === "Escape") finish(false);
        }

        confirmOkBtn.addEventListener("click", onOk);
        confirmCancelBtn.addEventListener("click", onCancel);
        confirmModal.addEventListener("click", onMaskClick);
        document.addEventListener("keydown", onKeyDown);
    });
}

// =============================================================
// 3.5 深色模式切换
//
//     这里只做两件事：
//       1. 在 <html> 上设置 data-theme="dark" 或 "light"
//       2. 把选择记进 localStorage，下次打开还保持
//
//     所有的颜色变化都由 style.css 里的 CSS 变量负责，
//     这里一行颜色都不用写，也不会碰到任何对话逻辑。
//
//     补充：页面刚打开时的"提前设置主题"写在 index.html 的 <head> 里，
//     目的是避免刷新时先闪一下浅色再变深色。
// =============================================================
const THEME_KEY = "zhixue-theme";

/** 看现在是什么主题。 */
function getCurrentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark"
        ? "dark"
        : "light";
}

/** 应用某个主题，并记住它。 */
function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try {
        localStorage.setItem(THEME_KEY, theme);
    } catch (error) {
        /* 浏览器的隐私模式下可能不让用 localStorage，忽略即可 */
    }
}

/** 在深色 / 浅色之间切换。 */
function toggleTheme() {
    const next = getCurrentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    log("已切换到" + (next === "dark" ? "深色" : "浅色") + "模式");

    // 如果学习报告正开着，让图表也跟着换配色，
    // 否则会白底黑字配深色弹窗，很刺眼
    if (!reportModal.classList.contains("d-none") && window.echarts) {
        const charts = document.querySelectorAll(".report-chart");
        if (charts.length > 0 && reportBodyLastData) {
            renderReportCharts(reportBodyLastData);
        }
    }
}

// 记一份最近一次的报告数据，切换主题时重新画图要用
let reportBodyLastData = null;

// =============================================================
// 4. 小工具函数
// =============================================================

/** 转义 HTML，防止用户输入的内容被当成代码执行（XSS）。 */
function escapeHtml(text) {
    return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

/** 只在浏览器控制台打印，方便按 F12 排查。 */
function debug(...args) {
    console.log("[智愈错题]", ...args);
}

/** 往页面上的"AI 诊断日志"面板追加一行。 */
function log(message, level) {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    const ss = String(now.getSeconds()).padStart(2, "0");

    const line = document.createElement("div");
    line.className = "ai-log-line" + (level ? " ai-log-" + level : "");
    line.textContent = `[${hh}:${mm}:${ss}] ${message}`;

    logEl.appendChild(line);
    while (logEl.childElementCount > MAX_LOG_LINES) {
        logEl.removeChild(logEl.firstElementChild);
    }
    logEl.scrollTop = logEl.scrollHeight;

    debug(message);
}

/** 把 "2025-01-01 12:34:56" 变成 "12:34"。 */
function formatTime(text) {
    if (!text) return "";
    const parts = String(text).split(" ");
    return parts.length >= 2 ? parts[1].slice(0, 5) : text;
}

/** 把 "2025-01-01 12:34:56" 变成 "01-01 12:34"（侧边栏用，带上日期）。 */
function formatDateTime(text) {
    if (!text) return "";
    const parts = String(text).split(" ");
    if (parts.length < 2) return text;
    return parts[0].slice(5) + " " + parts[1].slice(0, 5);
}

/** 读取输入框里的学生 ID。 */
function getStudentId() {
    const value = parseInt(studentIdInput.value, 10);
    return Number.isInteger(value) && value > 0 ? value : 1;
}

/**
 * 把消息区滚动到最底部。
 *
 * 这是聊天界面体验的关键：发完消息、AI 回复完、切换会话之后，
 * 都应该自动看到最新的一条。
 *
 * ── 为什么要包一层 requestAnimationFrame？ ──
 * 刚把消息插进页面时，浏览器还没算好它的高度，
 * 这时候读 scrollHeight 拿到的是"旧高度"，结果就差一点点没滚到底。
 * requestAnimationFrame 的意思是"等浏览器画完下一帧再执行"，
 * 那时高度已经算好了，滚得就准了。
 */
function scrollToBottom() {
    requestAnimationFrame(function () {
        chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    });
}

/** 从后端错误响应里读出人能看懂的说明。 */
async function readErrorDetail(response) {
    try {
        const data = await response.json();
        if (typeof data.detail === "string") return data.detail;
        if (Array.isArray(data.detail) && data.detail.length > 0) {
            return data.detail[0].msg || "提交的数据格式不对";
        }
        return "请求失败（状态码 " + response.status + "）";
    } catch (error) {
        return "请求失败（状态码 " + response.status + "）";
    }
}

// =============================================================
// 5. 检查后端 & AI 配置
// =============================================================
async function checkBackend() {
    log("检查后端连接...");
    try {
        const response = await fetch(API_BASE + "/hello");
        if (!response.ok) throw new Error("状态码 " + response.status);

        connBadge.className = "badge bg-success";
        connBadge.textContent = "后端已连接";
        log("后端已连接 " + API_BASE, "ok");
        return true;

    } catch (error) {
        connBadge.className = "badge bg-danger";
        connBadge.textContent = "后端未连接";
        log("后端连接失败：" + error.message, "error");
        return false;
    }
}

// 从后端拿到的超时秒数（用来显示"最长等待 xx 秒"）。
// 初始值先随便给一个，checkAiStatus 拿到真实值后会覆盖。
let aiTimeoutSeconds = 180;

async function checkAiStatus() {
    log("检查 AI 配置...");
    try {
        const response = await fetch(API_BASE + "/api/ai_status");
        if (!response.ok) {
            log("无法获取 AI 状态（HTTP " + response.status + "）", "error");
            return;
        }

        const data = await response.json();

        if (data.configured) {
            // 超时秒数由后端说了算，前端不写死
            if (data.timeout) aiTimeoutSeconds = data.timeout;

            log("AI 已配置，模型：" + data.model, "ok");
            log("每次最多带 " + data.max_history + " 条历史消息给 AI");
            log("单次最长等待 " + aiTimeoutSeconds + " 秒");
            aiWarningEl.classList.add("d-none");
        } else {
            log("AI 未配置：没有读到 DEEPSEEK_API_KEY", "error");
            aiWarningEl.innerHTML =
                "<strong>还没有配置 DeepSeek API Key</strong><br>" +
                "消息可以正常发送和保存，但 AI 不会回复。<br>" +
                "请在项目根目录创建 <code>.env</code> 文件（可复制 <code>.env.example</code>），" +
                "填入 <code>DEEPSEEK_API_KEY</code> 后<strong>重启后端</strong>。";
            aiWarningEl.classList.remove("d-none");
        }

    } catch (error) {
        log("检查 AI 配置时出错：" + error.message, "error");
    }
}

// =============================================================
// 6. 会话列表（左侧边栏）
// =============================================================

/**
 * 把 "2025-03-01 10:00:00" 这样的服务器时间字符串，转成 Date 对象。
 * 转不了就返回 null。
 */
function parseServerTime(text) {
    if (!text) return null;

    const parts = String(text).split(" ");
    if (parts.length < 2) return null;

    const ymd = parts[0].split("-").map(Number);
    const hms = parts[1].split(":").map(Number);
    if (ymd.length < 3 || hms.length < 2) return null;

    // 注意：月份从 0 开始，所以 ymd[1] 要减 1
    return new Date(ymd[0], ymd[1] - 1, ymd[2], hms[0], hms[1], hms[2] || 0);
}

/**
 * 判断一个会话属于哪个时间分组。
 * 返回："今天" / "昨天" / "最近 7 天" / "更早"
 */
function getTimeGroup(text) {
    const date = parseServerTime(text);
    if (!date) return "更早";

    const now = new Date();

    // 把两个时间都"抹掉时分秒"，只留下日期，这样相减得到的就是整天数
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const thatDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());

    // 一天 = 24 * 60 * 60 * 1000 毫秒
    const diffDays = Math.round((today - thatDay) / 86400000);

    if (diffDays <= 0) return "今天";      // 0 = 今天；负数说明时钟有偏差，也算今天
    if (diffDays === 1) return "昨天";
    if (diffDays <= 7) return "最近 7 天";
    return "更早";
}

/** 造一个分组标题（"📌 置顶" / "今天" 这种）。 */
function buildGroupHeader(label, isPinned) {
    const header = document.createElement("div");
    header.className = "session-group" + (isPinned ? " session-group-pinned" : "");
    header.textContent = label;
    return header;
}

/**
 * 造一个会话条目。
 *
 * 只负责画出这一条长什么样，
 * 点击切换会话的逻辑还是原来的 selectSession，没有改动。
 */
function buildSessionItem(session) {
    const item = document.createElement("div");
    item.className = "session-item";
    if (session.id === currentSessionId) {
        item.classList.add("active");
    }
    if (batchMode && selectedSessionIds.has(session.id)) {
        item.classList.add("selected");
    }

    // ---- 批量模式：最左边多一个复选框 ----
    if (batchMode) {
        const box = document.createElement("span");
        box.className = "session-checkbox" +
            (selectedSessionIds.has(session.id) ? " checked" : "");
        // 图标写死在这里，不含用户输入，用 innerHTML 是安全的
        box.innerHTML =
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="m4 12.5 5.5 5.5L20 6.5"/></svg>';
        item.appendChild(box);
    }

    // ---- 中间：标题 + 时间 + 消息数 ----
    const body = document.createElement("div");
    body.className = "session-body";

    const title = document.createElement("div");
    title.className = "session-title";
    title.textContent = session.title || "新会话";
    body.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "session-meta";
    meta.textContent =
        formatDateTime(session.last_message_at || session.created_at) +
        " · " + session.message_count + " 条";
    body.appendChild(meta);

    item.appendChild(body);

    if (batchMode) {
        // 批量模式：点整行 = 勾选 / 取消勾选。
        // 注意这里【没有】调用 selectSession，所以不会误切会话。
        item.addEventListener("click", function () {
            toggleSessionSelection(session.id);
        });
        return item;      // 批量模式下不显示图钉和删除按钮
    }

    // ---- 正常模式：点中间区域切换会话 ----
    body.addEventListener("click", function () {
        selectSession(session.id);
    });

    // ---- 右侧：图钉（置顶 / 取消置顶）----
    const pinBtn = document.createElement("button");
    pinBtn.className = "session-pin" + (session.is_pinned ? " pinned" : "");
    pinBtn.type = "button";
    pinBtn.title = session.is_pinned ? "取消置顶" : "置顶这个会话";
    // 图标写死在这里，不含任何用户输入，所以用 innerHTML 是安全的
    pinBtn.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M12 17v5"/>' +
        '<path d="M9 10.8V4h6v6.8l2 3.2H7l2-3.2Z"/>' +
        "</svg>";
    pinBtn.addEventListener("click", function (event) {
        event.stopPropagation();       // 别让点击冒泡到"切换会话"
        togglePin(session.id);
    });
    item.appendChild(pinBtn);

    // ---- 最右：删除按钮 ----
    const delBtn = document.createElement("button");
    delBtn.className = "session-delete";
    delBtn.type = "button";
    delBtn.textContent = "×";
    delBtn.title = "删除这个会话";
    delBtn.addEventListener("click", function (event) {
        event.stopPropagation();
        deleteSession(session.id);
    });
    item.appendChild(delBtn);

    return item;
}

/**
 * 渲染左侧会话列表。
 *
 * 渲染规则：
 *   1. 置顶的会话单独成一组，标题「📌 置顶」，永远排最上面
 *   2. 剩下的按最后活动时间分成：今天 / 昨天 / 最近 7 天 / 更早
 *   3. 空的分组不显示
 *
 * 注意：这里只负责"排序和分组显示"，
 * 点击条目依然是调用 selectSession，切换逻辑完全没变。
 */
function renderSessions() {

    // 没有会话时的空状态
    if (sessions.length === 0) {
        sessionListEl.innerHTML =
            '<div class="session-empty">' +
            "还没有会话，点上面的「新建会话」开始吧" +
            "</div>";
        return;
    }

    // 用 DOM 一个个创建，而不是拼 innerHTML 字符串，
    // 这样标题里的特殊符号不会被当成 HTML。
    sessionListEl.innerHTML = "";

    // ---- 先分成"置顶"和"普通"两拨 ----
    const pinned = sessions.filter(function (s) { return s.is_pinned; });
    const normal = sessions.filter(function (s) { return !s.is_pinned; });

    // ---- 1) 置顶组永远排最上面 ----
    if (pinned.length > 0) {
        sessionListEl.appendChild(buildGroupHeader("📌 置顶", true));
        pinned.forEach(function (session) {
            sessionListEl.appendChild(buildSessionItem(session));
        });
    }

    // ---- 2) 普通会话按时间分组 ----
    // 用数组保存顺序，这样渲染出来的分组顺序是固定的：
    // 今天 → 昨天 → 最近 7 天 → 更早
    const GROUP_ORDER = ["今天", "昨天", "最近 7 天", "更早"];
    const groups = { "今天": [], "昨天": [], "最近 7 天": [], "更早": [] };

    normal.forEach(function (session) {
        const stamp = session.last_message_at || session.created_at;
        groups[getTimeGroup(stamp)].push(session);
    });

    GROUP_ORDER.forEach(function (label) {
        const list = groups[label];
        if (list.length === 0) return;      // 空分组直接跳过

        sessionListEl.appendChild(buildGroupHeader(label, false));
        list.forEach(function (session) {
            sessionListEl.appendChild(buildSessionItem(session));
        });
    });
}

/**
 * 切换某个会话的置顶状态。
 *
 * ⚠️ 它只调用 /pin 接口然后刷新列表，
 *    完全不影响当前打开的会话（currentSessionId 不会被改），
 *    所以正在聊的对话不会被打断。
 */
async function togglePin(sessionId) {
    log("切换置顶状态（会话 #" + sessionId + "）...");

    try {
        const response = await fetch(
            API_BASE + "/api/sessions/" + sessionId + "/pin",
            { method: "POST" }
        );

        if (!response.ok) {
            log("置顶失败：" + (await readErrorDetail(response)), "error");
            return;
        }

        const data = await response.json();
        log("会话 #" + sessionId + " " + data.message, "ok");

        // 重新拉一次列表（后端已经按 is_pinned 排好序了）
        await loadSessions();

    } catch (error) {
        log("置顶出错：" + error.message, "error");
    }
}

// =============================================================
// 6.5 批量管理
// =============================================================

/** 刷新批量操作栏上的文字和按钮可用状态。 */
function updateBatchBar() {
    batchCountEl.textContent = "已选 " + selectedSessionIds.size + " 个";

    // 一个都没选时，"删除选中"按钮置灰
    batchDeleteBtn.disabled = selectedSessionIds.size === 0;
    batchBar.classList.toggle("d-none", !batchMode);
    document.body.classList.toggle("batch-mode", batchMode);

    batchToggleBtn.title = batchMode ? "退出批量管理" : "批量管理会话";
    batchToggleBtn.setAttribute("aria-label", batchToggleBtn.title);
}

/** 进入批量管理模式。 */
function enterBatchMode() {
    batchMode = true;
    selectedSessionIds.clear();       // 每次进来都是干净的
    updateBatchBar();
    renderSessions();
    log("已进入批量管理，点击会话左侧的方框进行勾选");
}

/** 退出批量管理模式，并清空所有勾选。 */
function exitBatchMode() {
    batchMode = false;
    selectedSessionIds.clear();
    updateBatchBar();
    renderSessions();
    log("已退出批量管理，恢复点击切换会话");
}

/** 进入 / 退出批量管理。 */
function toggleBatchMode() {
    if (batchMode) {
        exitBatchMode();
    } else {
        enterBatchMode();
    }
}

/**
 * 勾选 / 取消勾选一个会话。
 *
 * ⚠️ 它只改 selectedSessionIds，不碰 currentSessionId，
 *    所以批量勾选不会影响右边正在看的对话。
 */
function toggleSessionSelection(sessionId) {
    if (selectedSessionIds.has(sessionId)) {
        selectedSessionIds.delete(sessionId);
    } else {
        selectedSessionIds.add(sessionId);
    }
    updateBatchBar();
    renderSessions();
}

/** 全选：把当前列表里所有会话都勾上。 */
function selectAllSessions() {
    sessions.forEach(function (s) {
        selectedSessionIds.add(s.id);
    });
    updateBatchBar();
    renderSessions();
    log("已全选 " + selectedSessionIds.size + " 个会话");
}

/** 取消全选。 */
function clearSessionSelection() {
    selectedSessionIds.clear();
    updateBatchBar();
    renderSessions();
    log("已取消全选");
}

/**
 * 删除所有被勾选的会话。
 *
 * 流程：
 *   1. 弹确认框（显示要删几个）
 *   2. 调后端的批量删除接口（后端在一个事务里把消息和会话一起删掉）
 *   3. 如果被删的里面有"当前正在看的会话"，把右侧清空成"未选择会话"
 *   4. 重新拉一次会话列表，让侧边栏立刻更新
 */
async function deleteSelectedSessions() {
    const ids = Array.from(selectedSessionIds);

    if (ids.length === 0) {
        log("没有勾选任何会话", "error");
        return;
    }

    // ---- 第 1 步：确认 ----
    const confirmed = await showConfirm({
        title: "确定要删除选中的 " + ids.length + " 个会话吗？",
        text: "这些会话的聊天记录将无法恢复。",
        okText: "确认删除",
    });

    if (!confirmed) {
        log("已取消批量删除");
        return;
    }

    // ★ 关键：先记住"当前正在看的会话"是不是在删除名单里。
    //   因为下面刷新列表之后 currentSessionId 可能已经指向一个不存在的会话了。
    const deletingCurrent = ids.indexOf(currentSessionId) !== -1;

    log("批量删除 " + ids.length + " 个会话 ...");

    try {
        const response = await fetch(API_BASE + "/api/sessions/batch_delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_ids: ids }),
        });

        if (!response.ok) {
            log("批量删除失败：" + (await readErrorDetail(response)), "error");
            return;
        }

        const data = await response.json();
        log("已删除 " + data.deleted_sessions + " 个会话、" +
            data.deleted_messages + " 条聊天记录", "ok");

        // ---- 第 3 步：边界处理 ----
        // 如果正在看的那个会话被删了，必须把右侧重置，
        // 否则用户会看到"会话已经不存在"的报错，或者一片空白
        if (deletingCurrent) {
            currentSessionId = null;
            resetChatPanel();
            log("当前查看的会话已被删除，右侧已重置为「未选择会话」");
        }

        // ---- 第 4 步：退出批量模式 + 重新拉列表 ----
        batchMode = false;
        selectedSessionIds.clear();
        updateBatchBar();
        await loadSessions();

    } catch (error) {
        log("批量删除出错：" + error.message, "error");
    }
}

async function loadSessions() {
    currentStudentId = getStudentId();

    try {
        const response = await fetch(
            API_BASE + "/api/sessions/" + currentStudentId
        );
        if (!response.ok) {
            log("加载会话列表失败（HTTP " + response.status + "）", "error");
            return;
        }

        const data = await response.json();
        sessions = data.sessions || [];
        log("加载到 " + sessions.length + " 个会话");
        renderSessions();

    } catch (error) {
        log("加载会话列表出错：" + error.message, "error");
    }
}

async function createSession() {
    const studentId = getStudentId();
    log("新建会话（学生 " + studentId + "）...");

    try {
        const response = await fetch(API_BASE + "/api/new_session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ student_id: studentId }),
        });

        if (!response.ok) {
            log("新建会话失败：" + (await readErrorDetail(response)), "error");
            return;
        }

        const data = await response.json();
        log("会话 #" + data.session_id + " 已创建", "ok");

        await loadSessions();                  // 刷新侧边栏
        await selectSession(data.session_id);  // 自动选中新会话
        chatInput.focus();

    } catch (error) {
        log("新建会话出错：" + error.message, "error");
    }
}

async function deleteSession(sessionId) {
    const target = sessions.find(function (s) { return s.id === sessionId; });
    const name = target ? target.title : ("#" + sessionId);

    // ---- 先弹确认框，用户点了"确认删除"才继续往下走 ----
    // showConfirm 返回 Promise，所以这里用 await 等它。
    // 点"取消" / 按 Esc / 点蒙层都会返回 false，直接 return 什么都不做。
    const confirmed = await showConfirm({
        title: "确定要删除这个会话吗？",
        text: "「" + name + "」的聊天记录将无法恢复。",
        okText: "确认删除",
    });

    if (!confirmed) {
        log("已取消删除会话 #" + sessionId);
        return;
    }

    log("删除会话 #" + sessionId + " ...");

    try {
        const response = await fetch(API_BASE + "/api/sessions/" + sessionId, {
            method: "DELETE",
        });

        if (!response.ok) {
            log("删除失败：" + (await readErrorDetail(response)), "error");
            return;
        }

        log("会话 #" + sessionId + " 已删除", "ok");

        // 如果删的正好是当前打开的会话，就回到"未选择"状态
        if (currentSessionId === sessionId) {
            currentSessionId = null;
            resetChatPanel();
        }

        await loadSessions();

    } catch (error) {
        log("删除会话出错：" + error.message, "error");
    }
}

// =============================================================
// 7. 聊天区
// =============================================================

/** 还没选会话时的样子。 */
function resetChatPanel() {
    chatTitleEl.textContent = "未选择会话";
    chatMetaEl.innerHTML = "&nbsp;";
    renderPlaceholder("请新建或选择一个会话");
    chatInput.disabled = true;
    chatInput.placeholder = "请新建或选择一个会话";
    sendBtn.disabled = true;
    imageBtn.disabled = true;        // 没选会话时也不让传图
    clearImagePreview();
    chatInput.value = "";
}

/**
 * ★ 后端告诉我们"这个会话已经不存在了"时的统一处理。
 *
 * 什么时候会发生？
 *   · 会话被删掉了（可能是别的标签页删的，或者数据库被重置过）
 *   · 但前端还记着旧的 session_id
 *
 * 要做三件事，缺一不可：
 *   1. 清掉前端的当前会话（不然下次还会报同样的错）
 *   2. 把右侧重置成"未选择会话"，并给一句友好的指引
 *   3. 刷新左侧列表，把已经不存在的会话从界面上抹掉
 */
function handleSessionGone(reason) {
    log("会话已失效，正在重置界面：" + reason, "error");

    currentSessionId = null;

    resetChatPanel();
    renderPlaceholder(
        "这个会话已经不存在了。" +
        "请点击左侧的「＋ 新建会话」开始一段新的对话 🙂"
    );

    // 刷新左侧列表，把失效的会话清掉
    loadSessions();
}

function renderPlaceholder(text) {
    chatMessagesEl.innerHTML = "";
    const box = document.createElement("div");
    box.className = "chat-placeholder";
    box.textContent = text;
    chatMessagesEl.appendChild(box);
}

function updateChatHeader() {
    const session = sessions.find(function (s) { return s.id === currentSessionId; });

    if (!session) {
        chatTitleEl.textContent = "会话 #" + currentSessionId;
        chatMetaEl.innerHTML = "&nbsp;";
        return;
    }

    chatTitleEl.textContent = session.title || "新会话";
    chatMetaEl.textContent =
        "会话 #" + session.id + " · 共 " + session.message_count + " 条消息";
}

/**
 * 创建 AI 的小头像（学士帽图标）。
 *
 * ⚠️ 这个函数纯粹管外观，跟接口调用、对话逻辑没有任何关系。
 *    里面的 SVG 是一段写死的图形代码，不包含任何用户输入，所以可以安全地用 innerHTML。
 */
function createAvatarElement() {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M22 10 12 5 2 10l10 5 10-5Z"/>' +
        '<path d="M6 12v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5"/>' +
        "</svg>";
    return avatar;
}

/** 把一条消息变成页面上的一个气泡。 */
function buildMessageElement(message) {
    const row = document.createElement("div");
    row.className = "msg-row " + message.role;

    // AI 那边加个小头像，看起来像聊天软件
    if (message.role === "assistant") {
        row.appendChild(createAvatarElement());
    }

    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap";

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    // 用 textContent 而不是 innerHTML：内容原样显示，绝不会被当成 HTML 执行
    bubble.textContent = message.content;
    wrap.appendChild(bubble);

    // AI 回复如果带知识点和错因，在气泡下面挂两个小标签。
    // ★ 后端只在【首次诊断】和【变式题做错】两种情况才会带上这两个字段，
    //   引导轮次是不带的，所以这里不用再判断会话状态。
    if (message.role === "assistant" && message.knowledge_point) {
        const tags = document.createElement("div");
        tags.className = "msg-tags";

        const kp = document.createElement("span");
        kp.className = "tag tag-knowledge";
        kp.textContent = "📘 " + message.knowledge_point;
        tags.appendChild(kp);

        const et = document.createElement("span");
        et.className = "tag tag-error";
        et.textContent = "🔍 " + (message.error_category || "其他");
        tags.appendChild(et);

        wrap.appendChild(tags);

        // ★ 详细的错因分析单独占一行，会自动换行，保证完整显示
        if (message.error_type) {
            const detail = document.createElement("div");
            detail.className = "error-detail";
            detail.textContent = "📝 " + message.error_type;
            wrap.appendChild(detail);
        }
    }

    // ---- 举一反三：在气泡下面挂一个"生成同类练习题"按钮 ----
    // ★ 只有在【学生已经做对】的那一条回复下面才显示。
    //   后端会给这条消息打上 show_variant_button 标记
    //   （见下面的 renderMessages 和 sendMessage）
    if (message.role === "assistant" && message.show_variant_button) {
        const variantBtn = document.createElement("button");
        variantBtn.className = "variant-btn";
        variantBtn.type = "button";
        variantBtn.innerHTML =
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 7.5 4"/>' +
            '<path d="M21 3v6h-6"/>' +
            '<path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-7.5-4"/>' +
            '<path d="M3 21v-6h6"/></svg>' +
            "<span>生成同类练习题</span>";
        variantBtn.addEventListener("click", function () {
            generateVariant(
                message.knowledge_point || message.variant_knowledge_point || "未指定知识点",
                variantBtn
            );
        });
        wrap.appendChild(variantBtn);
    }

    const meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.textContent = formatTime(message.created_at);
    wrap.appendChild(meta);

    row.appendChild(wrap);
    return row;
}

function renderMessages(messages, sessionStatus) {
    chatMessagesEl.innerHTML = "";

    if (!messages || messages.length === 0) {
        // 空会话：显示一句居中提示
        renderPlaceholder("这是一个新会话，把错题发进来吧 👇");
        scrollToBottom();
        return;
    }

    // ★ 找出这个会话里【最近一次诊断出的知识点】。
    //   为什么要往前找？因为"已经做对"的那条消息本身是不带标签的
    //   （AI 在 solved 状态下不输出知识点），出变式题得用之前那个。
    sessionKnowledgePoint = "";
    messages.forEach(function (m) {
        if (m.knowledge_point) sessionKnowledgePoint = m.knowledge_point;
    });

    // ★ 找到最后一条 AI 回复的下标
    let lastAssistantIndex = -1;
    messages.forEach(function (m, index) {
        if (m.role === "assistant") lastAssistantIndex = index;
    });

    // ★ 只有当前状态是"已解决"，才在最后那条 AI 回复下面挂练习题按钮
    const isSolved = sessionStatus === "solved";

    messages.forEach(function (message, index) {
        if (isSolved && index === lastAssistantIndex) {
            message.show_variant_button = true;
            message.variant_knowledge_point = sessionKnowledgePoint;
        }
        chatMessagesEl.appendChild(buildMessageElement(message));
    });

    // 渲染完滚到底部
    scrollToBottom();
}

/** 只追加一条消息（发消息时用，比整段重绘流畅）。 */
function appendMessage(message) {
    // 顺便记住最近的知识点，出变式题时要用
    if (message.knowledge_point) sessionKnowledgePoint = message.knowledge_point;

    // 如果显示的还是占位提示，先清掉
    const placeholder = chatMessagesEl.querySelector(".chat-placeholder");
    if (placeholder) chatMessagesEl.innerHTML = "";

    chatMessagesEl.appendChild(buildMessageElement(message));
    scrollToBottom();
}

/** 在聊天流里插一条居中的灰色/红色小提示。 */
function appendSystemNote(text, level) {
    const note = document.createElement("div");
    note.className = "system-note" + (level ? " system-note-" + level : "");
    note.textContent = text;
    chatMessagesEl.appendChild(note);
    scrollToBottom();
}

/** 显示"AI 正在思考"的三个跳动小点。 */
function showTyping() {
    hideTyping();

    const row = document.createElement("div");
    row.className = "msg-row assistant";
    row.id = "typing-row";

    row.appendChild(createAvatarElement());

    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap";

    const bubble = document.createElement("div");
    bubble.className = "bubble typing-bubble";
    for (let i = 0; i < 3; i++) {
        const dot = document.createElement("span");
        dot.className = "dot";
        bubble.appendChild(dot);
    }
    wrap.appendChild(bubble);

    const meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.id = "typing-meta";
    // 长句子放在聊天区里（这里空间够），按钮上只留简短的
    meta.textContent = "AI 导师正在深度思考中（最长等待 " + aiTimeoutSeconds + " 秒）…";
    wrap.appendChild(meta);

    row.appendChild(wrap);
    chatMessagesEl.appendChild(row);
    scrollToBottom();
}

function hideTyping() {
    const row = document.getElementById("typing-row");
    if (row) row.remove();
}

async function loadMessages(sessionId) {
    renderPlaceholder("正在加载聊天记录...");

    try {
        const response = await fetch(API_BASE + "/api/messages/" + sessionId);

        if (!response.ok) {
            // ★ 会话不存在（404）：重置界面，别只显示红字
            if (response.status === 404) {
                handleSessionGone(await readErrorDetail(response));
                return;
            }
            renderPlaceholder("加载失败：" + (await readErrorDetail(response)));
            return;
        }

        const data = await response.json();
        renderMessages(data.messages, (data.session || {}).status);
        log("加载会话 #" + sessionId + " 的 " + data.count + " 条消息");

    } catch (error) {
        renderPlaceholder("加载失败，请检查后端是否已启动");
        log("加载消息出错：" + error.message, "error");
    }
}

async function selectSession(sessionId) {
    currentSessionId = sessionId;
    renderSessions();          // 让侧边栏高亮跟着变
    updateChatHeader();

    // 可以开始输入了
    chatInput.disabled = false;
    chatInput.placeholder = "把错题粘贴在这里，或继续追问…";
    sendBtn.disabled = false;
    imageBtn.disabled = false;       // 选了会话就可以传图了

    await loadMessages(sessionId);
    log("切换到会话 #" + sessionId);
}

// =============================================================
// 8. 发送消息（核心）
// =============================================================

function startSending() {
    isSending = true;
    sendBtn.disabled = true;
    sendSpinner.classList.remove("d-none");

    const startedAt = Date.now();
    // 按钮很小，放不下长句子，所以这里只写简短的。
    // 完整提示"AI 导师正在深度思考中（最长等待 xxx 秒）"放在聊天区的打字气泡里。
    sendTextEl.textContent = "思考中";

    elapsedTimerId = setInterval(function () {
        const seconds = Math.floor((Date.now() - startedAt) / 1000);
        sendTextEl.textContent = "思考中 " + seconds + "s";

        // 顺便把聊天区那行提示也加上秒数，让人知道还在跑
        const typingMeta = document.getElementById("typing-meta");
        if (typingMeta) {
            typingMeta.textContent =
                "AI 导师正在深度思考中（最长等待 " + aiTimeoutSeconds +
                " 秒）… 已等待 " + seconds + " 秒";
        }
    }, 1000);
}

function stopSending() {
    if (elapsedTimerId !== null) {
        clearInterval(elapsedTimerId);
        elapsedTimerId = null;
    }
    isSending = false;
    sendBtn.disabled = false;
    sendSpinner.classList.add("d-none");
    sendTextEl.textContent = "发送";
}

async function sendMessage() {
    if (isSending) return;

    // ---- 校验 ----
    if (!currentSessionId) {
        appendSystemNote("请新建或选择一个会话", "warn");
        return;
    }

    const userInput = chatInput.value.trim();
    if (!userInput) {
        chatInput.focus();
        return;
    }

    log("发送消息（会话 #" + currentSessionId + "，长度 " + userInput.length + " 字）");

    // ---- 先把学生的话显示出来（乐观点：不等后端返回就先画上去）----
    appendMessage({
        id: "temp-" + Date.now(),
        role: "user",
        content: userInput,
        created_at: "",
    });

    chatInput.value = "";
    chatInput.style.height = "";
    startSending();
    showTyping();

    const startedAt = Date.now();

    try {
        const response = await fetch(API_BASE + "/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                student_id: getStudentId(),
                session_id: currentSessionId,
                user_input: userInput,
            }),
        });

        hideTyping();
        const costSeconds = ((Date.now() - startedAt) / 1000).toFixed(1);

        // ---- 后端报错 ----
        if (!response.ok) {
            const detail = await readErrorDetail(response);
            // ★ 会话不存在（404）：不是网络问题，是前端记着过期的会话
            if (response.status === 404) {
                handleSessionGone(detail);
                return;
            }
            log("发送失败：HTTP " + response.status + " — " + detail, "error");
            appendSystemNote("发送失败：" + detail, "error");
            return;
        }

        const data = await response.json();
        log("后端已响应，HTTP " + response.status + "（耗时 " + costSeconds + " 秒）", "ok");

        // ---- 用后端返回的真实数据替换掉刚才那条临时气泡 ----
        // 这样能拿到数据库生成的真实 id 和服务器时间
        const lastUserRow = chatMessagesEl.querySelector(".msg-row.user:last-of-type");
        if (lastUserRow) lastUserRow.remove();
        appendMessage(data.user_message);

        // ---- AI 回复 ----
        if (data.ai_success && data.ai_message) {
            // * 如果 AI 判断学生已经把这题做对了（is_solved = true），
            //   就在这条回复下面挂上"生成同类练习题"按钮。
            //   其他任何情况都不挂 —— 这正是需求里要求的。
            if (data.is_solved) {
                data.ai_message.show_variant_button = true;
                data.ai_message.variant_knowledge_point = sessionKnowledgePoint;
                log("AI 判定这道题已经解决，显示练习题按钮", "ok");
            }
            appendMessage(data.ai_message);
            log("AI 已回复", "ok");
            log("　知识点：" + data.ai_message.knowledge_point);
            log("　错因：" + data.ai_message.error_type);
            log("　字数：" + (data.ai_message.content || "").length);
        } else {
            const reason = data.ai_error || "未知原因";
            const code = data.ai_error_code || "";
            log("AI 没有回复（" + code + "）：" + reason, "error");

            if (code === "timeout") {
                // 超时是最常见的情况。用一条"AI 气泡"来说，
                // 比红色的系统提示温和，学生也不会觉得是自己操作错了。
                appendMessage({
                    id: "timeout-" + Date.now(),
                    role: "assistant",
                    content:
                        "抱歉，这道题太难了，我思考超时了。" +
                        "请再发送一次，或者我们换一道题试试？",
                    created_at: "",
                });
            } else {
                appendSystemNote("消息已保存，但 AI 没有回复：" + reason, "error");
            }
        }

        // ---- 刷新侧边栏（标题可能刚被自动命名，顺序也可能变了）----
        await loadSessions();
        updateChatHeader();

    } catch (error) {
        hideTyping();
        log("网络错误：" + error.message, "error");
        appendSystemNote("网络错误：连不上后端，请确认服务已经启动", "error");

    } finally {
        stopSending();
        chatInput.focus();
    }
}

// =============================================================
// 8.5 学习报告（ECharts 图表）
// =============================================================

// ECharts 从国内 CDN 加载。
// bootcdn 在国内访问比较稳，国外的 cdn.jsdelivr.net 有时会打不开。
const ECHARTS_CDN =
    "https://cdn.bootcdn.net/ajax/libs/echarts/5.4.3/echarts.min.js";

let echartsPromise = null;
let errorChart = null;      // 错因饼图实例
let knowledgeChart = null;  // 知识点柱状图实例

/**
 * 按需加载 ECharts（第一次点"学习报告"时才下载，不拖慢首页）。
 * 返回一个 Promise，加载完就能用 window.echarts 了。
 */
function loadECharts() {
    if (window.echarts) return Promise.resolve(window.echarts);
    if (echartsPromise) return echartsPromise;   // 正在加载就直接复用

    echartsPromise = new Promise(function (resolve, reject) {
        const script = document.createElement("script");
        script.src = ECHARTS_CDN;
        script.onload = function () {
            if (window.echarts) resolve(window.echarts);
            else reject(new Error("ECharts 加载了但没初始化成功"));
        };
        script.onerror = function () {
            echartsPromise = null;   // 失败后允许重试
            reject(new Error("ECharts 加载失败，请检查网络"));
        };
        (document.head || document.body).appendChild(script);
    });

    return echartsPromise;
}

/** 根据当前是深色还是浅色，给图表配一套颜色。 */
function getChartColors() {
    const isDark = getCurrentTheme() === "dark";
    return isDark
        ? {
            text: "#E8EDF5",        // 主要文字
            subText: "#94A3B8",     // 次要文字
            axis: "#24344D",        // 坐标轴
            split: "rgba(148,163,184,0.14)",
            border: "#131C2E",      // 饼图扇区之间的缝隙，要跟弹窗底色一致
        }
        : {
            text: "#0F172A",
            subText: "#64748B",
            axis: "#E2E8F0",
            split: "rgba(100,116,139,0.14)",
            border: "#FFFFFF",
        };
}

/** 把接口返回的数据画成两个图。 */
function renderReportCharts(report) {
    const echarts = window.echarts;
    if (!echarts) return;

    const c = getChartColors();

    // ---------- 饼图：错因分布 ----------
    if (!errorChart) {
        errorChart = echarts.init(document.getElementById("chart-error"));
    }
    errorChart.setOption({
        tooltip: {
            trigger: "item",
            formatter: "{b}：{c} 次（{d}%）",
        },
        legend: {
            bottom: 0,
            textStyle: { color: c.subText, fontSize: 11 },
            itemWidth: 10,
            itemHeight: 10,
        },
        color: ["#2563EB", "#F59E0B", "#EF4444",
                "#10B981", "#8B5CF6", "#06B6D4", "#EC4899"],
        series: [{
            type: "pie",
            radius: ["42%", "66%"],
            center: ["50%", "43%"],
            avoidLabelOverlap: true,
            itemStyle: { borderColor: c.border, borderWidth: 2 },
            label: { color: c.text, fontSize: 11, formatter: "{b}\n{c}次" },
            labelLine: { lineStyle: { color: c.axis } },
            data: report.error_types.map(function (row) {
                return { name: row.name, value: row.count };
            }),
        }],
    }, true);

    // ---------- 柱状图：知识点排行 ----------
    // ECharts 的柱状图默认是从下往上画的，
    // 所以把数组倒过来，让错误次数最多的排在最上面。
    const knowledge = report.knowledge_points.slice().reverse();

    if (!knowledgeChart) {
        knowledgeChart = echarts.init(document.getElementById("chart-knowledge"));
    }
    knowledgeChart.setOption({
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
        grid: { left: 6, right: 20, top: 12, bottom: 6, containLabel: true },
        xAxis: {
            type: "value",
            minInterval: 1,               // 次数都是整数，不要出现 0.5
            axisLabel: { color: c.subText, fontSize: 11 },
            splitLine: { lineStyle: { color: c.split } },
        },
        yAxis: {
            type: "category",
            data: knowledge.map(function (row) { return row.name; }),
            axisLabel: { color: c.text, fontSize: 11 },
            axisLine: { lineStyle: { color: c.axis } },
            axisTick: { show: false },
        },
        series: [{
            type: "bar",
            barMaxWidth: 20,
            itemStyle: { color: "#2563EB", borderRadius: [0, 6, 6, 0] },
            label: { show: true, position: "right", color: c.subText, fontSize: 11 },
            data: knowledge.map(function (row) { return row.count; }),
        }],
    }, true);
}

/** 打开学习报告弹窗。 */
async function openReport() {
    const studentId = getStudentId();

    reportModal.classList.remove("d-none");
    reportSubtitle.textContent = "正在统计学生 " + studentId + " 的学习数据...";
    reportBody.classList.add("d-none");
    reportEmpty.classList.add("d-none");

    log("打开学习报告（学生 " + studentId + "）...");

    try {
        // 两件事并行做：一边拉数据，一边下载 ECharts，省时间
        const [echarts, response] = await Promise.all([
            loadECharts(),
            fetch(API_BASE + "/api/report/" + studentId),
        ]);

        if (!response.ok) {
            reportSubtitle.textContent = "加载失败：" +
                (await readErrorDetail(response));
            return;
        }

        const report = await response.json();
        const s = report.summary;

        statSessions.textContent = s.total_sessions;
        statQuestions.textContent = s.total_questions;
        statDiagnosed.textContent = s.diagnosed;
        reportSubtitle.textContent =
            "学生 " + studentId + " · 共 " + s.knowledge_count + " 个知识点、" +
            s.error_type_count + " 类错因";

        const hasData = report.error_types.length > 0 ||
                        report.knowledge_points.length > 0;

        if (!hasData) {
            reportBody.classList.add("d-none");
            reportEmpty.classList.remove("d-none");
        } else {
            reportEmpty.classList.add("d-none");
            reportBody.classList.remove("d-none");
            reportBodyLastData = report;      // 记下来，切换主题时要重画
            renderReportCharts(report);
        }

        log("学习报告已生成", "ok");

    } catch (error) {
        reportSubtitle.textContent = "出错了：" + error.message;
        log("学习报告出错：" + error.message, "error");
    }
}

/** 关闭学习报告弹窗。 */
function closeReport() {
    reportModal.classList.add("d-none");
}

// =============================================================
// 8.6 举一反三：生成同类变式练习题
// =============================================================
async function generateVariant(knowledgePoint, buttonEl) {
    // 正在等 AI 回复时不允许重复点
    if (isSending) return;

    if (!currentSessionId) {
        appendSystemNote("请先选择一个会话", "warn");
        return;
    }

    log("生成变式题（知识点：" + knowledgePoint + "）...");

    if (buttonEl) buttonEl.disabled = true;

    startSending();
    showTyping();

    try {
        const response = await fetch(API_BASE + "/api/generate_variant", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: currentSessionId,
                knowledge_point: knowledgePoint,
            }),
        });

        hideTyping();

        if (!response.ok) {
            const detail = await readErrorDetail(response);
            // ★ 会话不存在（404）：同样走统一重置
            if (response.status === 404) {
                handleSessionGone(detail);
                return;
            }
            log("生成变式题失败：" + detail, "error");
            appendSystemNote("生成变式题失败：" + detail, "error");
            return;
        }

        const data = await response.json();

        if (data.ai_success && data.ai_message) {
            // 新题目直接作为一条 AI 消息插到聊天记录最底部
            appendMessage(data.ai_message);
            log("变式题已生成并插入聊天记录", "ok");
            await loadSessions();     // 侧边栏的条数也更新一下
        } else {
            const reason = data.ai_error || "未知原因";
            log("变式题生成失败：" + reason, "error");
            appendSystemNote("变式题生成失败：" + reason, "error");
        }

    } catch (error) {
        hideTyping();
        log("生成变式题出错：" + error.message, "error");
        appendSystemNote("生成变式题出错：" + error.message, "error");

    } finally {
        stopSending();
        if (buttonEl) buttonEl.disabled = false;
    }
}

// =============================================================
// 8.7 错题图片上传 + OCR
//
//     完整流程：
//       1. 点 📷 -> 弹出系统选图框
//       2. 浏览器用 canvas 把图片压缩到 1 MB 左右
//          （手机拍的照片动辄 5-10 MB，直接传又慢又费 token）
//       3. 显示缩略图预览
//       4. 转成 base64 发给后端 /api/ocr
//       5. 后端调 deepseek-flash 识别文字，返回纯文本
//       6. 把文字自动填进输入框，用户可以直接改或直接发送
//
//     为什么压缩要在前端做？
//       官方限制单张图片最大 32 MiB、请求体 48 MiB。
//       而且图片按尺寸换算 token 计费，传原图是白花钱。
// =============================================================

/** 更新预览条上的状态文字。cls 可以是 "ok" / "error" / ""。 */
function setImageStatus(text, cls) {
    imagePreviewStatus.textContent = text;
    imagePreviewStatus.className = "image-preview-status" + (cls ? " " + cls : "");
}

/** 清空图片预览（选新图前、识别完、或用户点 × 时用）。 */
function clearImagePreview() {
    currentImageDataUrl = "";
    imagePreviewImg.removeAttribute("src");
    imagePreview.classList.add("d-none");
    imageInput.value = "";           // 清空，否则再选同一张图不会触发 change
}

/**
 * 用 canvas 把图片压缩到指定边长以内，再转成 JPEG 的 dataURL。
 *
 * 为什么不用原图？
 *   手机照片通常 4000×3000、5 MB 以上。压到 1400 像素、
 *   质量 0.82 之后一般只有几百 KB，识别效果几乎没差别，
 *   但上传快很多、也省 token。
 */
function compressImage(file, maxSide, quality) {
    maxSide = maxSide || 1400;
    quality = quality || 0.82;

    return new Promise(function (resolve, reject) {
        const reader = new FileReader();

        reader.onload = function () {
            const img = new Image();

            img.onload = function () {
                let width = img.width;
                let height = img.height;

                // 只缩不放：本来就小的图保持原尺寸
                const longest = Math.max(width, height);
                if (longest > maxSide) {
                    const scale = maxSide / longest;
                    width = Math.round(width * scale);
                    height = Math.round(height * scale);
                }

                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;

                const ctx = canvas.getContext("2d");
                // 先铺白底：PNG 透明区域转 JPEG 会变黑，很难看
                ctx.fillStyle = "#FFFFFF";
                ctx.fillRect(0, 0, width, height);
                ctx.drawImage(img, 0, 0, width, height);

                resolve({
                    dataUrl: canvas.toDataURL("image/jpeg", quality),
                    width: width,
                    height: height,
                });
            };

            img.onerror = function () {
                reject(new Error("这张图片打不开，换一张试试"));
            };
            img.src = reader.result;
        };

        reader.onerror = function () {
            reject(new Error("读取文件出错"));
        };
        reader.readAsDataURL(file);
    });
}

/** 用户选好图片之后的主流程。 */
async function handleImageFile(file) {
    if (!file) return;

    if (ocrRunning) {
        log("上一张图片还在识别中，稍等一下", "error");
        return;
    }

    if (!file.type || file.type.indexOf("image/") !== 0) {
        log("只能上传图片文件", "error");
        return;
    }

    log("选择了图片：" + file.name + "（" + Math.round(file.size / 1024) + " KB）");

    // ---- 预览 + 压缩 ----
    imagePreview.classList.remove("d-none");
    imagePreviewName.textContent = file.name;
    setImageStatus("正在压缩图片...");

    let compressed;
    try {
        compressed = await compressImage(file);
    } catch (error) {
        setImageStatus(error.message, "error");
        log("压缩图片失败：" + error.message, "error");
        return;
    }

    currentImageDataUrl = compressed.dataUrl;
    imagePreviewImg.src = compressed.dataUrl;
    setImageStatus(
        "已压缩到 " + compressed.width + "×" + compressed.height +
        "，正在识别文字..."
    );
    log("图片已压缩为 " + compressed.width + "×" + compressed.height);

    // ---- 送给后端识别 ----
    ocrRunning = true;
    imageBtn.classList.add("busy");
    imageBtn.disabled = true;

    try {
        // dataURL 的格式是 "data:image/jpeg;base64,XXXX"，
        // 逗号后面那一段才是真正的 base64 数据
        const base64 = compressed.dataUrl.split(",")[1];

        const response = await fetch(API_BASE + "/api/ocr", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                image_base64: base64,
                mime_type: "image/jpeg",
            }),
        });

        if (!response.ok) {
            const detail = await readErrorDetail(response);
            setImageStatus("识别失败：" + detail, "error");
            log("图片识别失败：" + detail, "error");
            return;
        }

        const data = await response.json();

        if (!data.success || !data.text) {
            setImageStatus(data.message || "图里没识别到文字", "error");
            log("图片里没有识别到文字", "error");
            return;
        }

        // ---- 识别成功：填进输入框 ----
        // 用 "\n\n" 把新内容和输入框里已有的文字隔开，不覆盖用户已打的字
        const existing = chatInput.value.trim();
        chatInput.value = existing
            ? existing + "\n\n" + data.text
            : data.text;

        // 触发一次 input 事件，让输入框自动长高
        chatInput.dispatchEvent(new Event("input"));
        chatInput.focus();

        setImageStatus("识别成功，已填入输入框", "ok");
        log("图片识别成功，共 " + data.text.length + " 个字", "ok");

    } catch (error) {
        setImageStatus("识别出错：" + error.message, "error");
        log("图片识别出错：" + error.message, "error");

    } finally {
        ocrRunning = false;
        imageBtn.classList.remove("busy");
        imageBtn.disabled = false;
        imageInput.value = "";       // 允许再选同一张图
    }
}

// =============================================================
// 9. 事件绑定
// =============================================================

newSessionBtn.addEventListener("click", createSession);
sendBtn.addEventListener("click", sendMessage);

// 学生 ID 变了，就重新加载他的会话
studentIdInput.addEventListener("change", async function () {
    log("学生 ID 改为 " + getStudentId() + "，重新加载会话列表");
    currentSessionId = null;
    resetChatPanel();
    await loadSessions();
});

// 输入框：Ctrl + Enter 发送
chatInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        sendMessage();
    }
});

// 输入框自动长高（最多约 6 行）
chatInput.addEventListener("input", function () {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + "px";
});

clearLogBtn.addEventListener("click", function () {
    logEl.innerHTML = "";
    log("日志已清空");
});

// 深色模式切换按钮
themeToggleBtn.addEventListener("click", toggleTheme);

// 侧边栏收起 / 展开按钮
sidebarToggleBtn.addEventListener("click", toggleSidebar);

// 批量管理：进入 / 退出
batchToggleBtn.addEventListener("click", toggleBatchMode);
batchSelectAllBtn.addEventListener("click", selectAllSessions);
batchClearBtn.addEventListener("click", clearSessionSelection);
batchDeleteBtn.addEventListener("click", deleteSelectedSessions);

// 学习报告：打开 / 关闭（点蒙层也能关）
reportBtn.addEventListener("click", openReport);
reportCloseBtn.addEventListener("click", closeReport);
reportModal.addEventListener("click", function (event) {
    if (event.target === reportModal) closeReport();
});

// 窗口大小变化时，让图表跟着重新适应尺寸
window.addEventListener("resize", function () {
    if (errorChart) errorChart.resize();
    if (knowledgeChart) knowledgeChart.resize();
});

// ---- 图片上传 / OCR ----
// 点按钮 -> 触发隐藏的文件选择框
imageBtn.addEventListener("click", function () {
    imageInput.click();
});

// 用户选好文件
imageInput.addEventListener("change", function () {
    if (imageInput.files && imageInput.files[0]) {
        handleImageFile(imageInput.files[0]);
    }
});

// 点 × 移除图片
imageRemoveBtn.addEventListener("click", function () {
    clearImagePreview();
    log("已移除图片");
});

// =============================================================
// 10. 启动
// =============================================================
async function init() {
    log("页面加载完成，开始初始化...");

    // 恢复上次的侧边栏状态（默认是展开）
    let savedCollapsed = false;
    try {
        savedCollapsed = localStorage.getItem(SIDEBAR_KEY) === "1";
    } catch (error) {
        /* 忽略 */
    }
    applySidebarCollapsed(savedCollapsed);

    // 批量操作栏初始是隐藏的，"删除选中"按钮初始置灰
    updateBatchBar();

    const backendOk = await checkBackend();
    if (!backendOk) {
        currentSessionId = null;
        resetChatPanel();
        renderPlaceholder("连不上后端服务，请先启动后端");
        return;
    }

    await checkAiStatus();

    // 加载会话列表；如果有会话，自动打开最近的那个
    await loadSessions();

    if (sessions.length > 0) {
        log("自动打开最近的会话 #" + sessions[0].id);
        await selectSession(sessions[0].id);
    } else {
        log("这个学生还没有会话，等待新建");
        resetChatPanel();
    }

    log("初始化结束");
}

init();
