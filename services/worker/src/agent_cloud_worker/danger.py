from __future__ import annotations

import hashlib
import json
import re

from agent_cloud_common import ToolCall, ToolResult

from agent_cloud_worker.tools import ToolExecutor

# 危险操作确认(轻量权限):worker 拦截销毁性 bash 命令,不执行、返回带「批准码」(操作
# 指纹)的错误结果 —— LLM 据此向用户解释并等待;前端在被拦的工具卡上渲染【允许执行并
# 继续】按钮,点击自动发送含批准码的确认消息;下一回合 worker 从最后一条 user 消息提取
# 批准码,指纹匹配才放行这一次(参数变了指纹不同 → 再拦,安全兜底)。
#
# 架构取舍:本系统回合是「一跑到底」的(worker loop 自主执行到 turn_done),没有回合内
# 暂停等输入的机制;拦截-确认-重试把确认动作放进正常消息流,零架构手术,且天然兼容
# 排队/断流恢复。规则刻意保守(只拦明确销毁性的模式)——误报会让用户烦到想关掉它。
#
# ⚠️ 已知边界(有意不拦,非遗漏——审查 M3):写脚本再执行(write_file x.sh + sh x.sh)、
# `bash -c "$(cat x)"` 等间接执行、base64/编码管道、`python -c` 解释器内删除(shutil.rmtree)、
# find -exec rm、rsync --delete、`> file` 截断。封堵这些需要语义级分析(展开脚本/解码/跨
# 工具数据流),远超「轻量防手滑」的定位,强行加只会催生误报。本层是防误操作的护栏,
# 不是对抗恶意 LLM/prompt 注入的安全边界(那由沙箱隔离承担)。

# 危险 bash 模式 → 人话原因。对「命令文本」逐个匹配(含管道/&& 组合中的片段)。
_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*[rR][a-zA-Z]*)\b"), "递归强制删除(rm -rf)"),
    # 扫描任意位置的 -r/-R 旗标(审查 M1:`rm -f -r x` 旗标乱序不能漏)+ --recursive 长旗标
    (re.compile(r"\brm\b(?:\s+-[a-zA-Z]+)*\s+-[a-zA-Z]*[rR]\b"), "递归删除目录(rm -r)"),
    (re.compile(r"\brm\b[^;|&]*--recursive\b"), "递归删除目录(rm --recursive)"),
    (re.compile(r"\brm\s+(?:-\S+\s+)*[^\s;|&]*\*"), "按通配符批量删除(rm *)"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "丢弃全部未提交修改(git reset --hard)"),
    (re.compile(r"\bgit\s+clean\s+-\S*[fd]"), "删除未跟踪文件(git clean)"),
    (re.compile(r"\bgit\s+checkout\s+(?:--\s+)?\.(?:\s|$)"), "丢弃工作区修改(git checkout .)"),
    (re.compile(r"\bfind\b[^;|&]*-delete\b"), "按条件批量删除(find -delete)"),
    (re.compile(r"\bxargs\b[^;|&]*\brm\b"), "管道批量删除(xargs rm)"),
    (re.compile(r"\btruncate\s+-s\s*0\b"), "清空文件内容(truncate -s 0)"),
    (re.compile(r"\bshred\b"), "不可恢复地擦除文件(shred)"),
    (re.compile(r"\bmkfs\b|\bdd\s+[^;|&]*of=/dev/"), "底层设备写入(mkfs/dd)"),
]

# 批准码在确认消息里的形态(跨端契约:web/app 的确认按钮发送同样的文本;人话可读,
# 不做隐藏 marker——「允许」本身就是用户该看到的动作)。
_APPROVAL_RE = re.compile(r"批准码\s*([a-f0-9]{16})")


def assess_danger(call: ToolCall) -> str | None:
    """该工具调用是否销毁性操作。目前只看 bash 命令(write_file/edit 是 AI 工作流核心且
    有 diff 可见,不拦——规则保守是这个功能可用的前提)。返回人话原因;安全则 None。"""
    if call.name != "bash":
        return None
    command = (call.arguments or {}).get("command")
    if not isinstance(command, str):
        return None
    for pattern, reason in _DANGEROUS_PATTERNS:
        if pattern.search(command):
            return reason
    return None


def fingerprint(call: ToolCall) -> str:
    """操作指纹(批准码):工具名 + 规范化参数的稳定 hash。同一命令重试指纹一致(可被
    批准放行);参数有任何变化指纹即变(旧批准码失效,再次拦截)。"""
    canonical = json.dumps(
        {"tool": call.name, "args": call.arguments or {}}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def extract_approvals(text: str) -> frozenset[str]:
    """从(最后一条)用户消息文本里提取全部批准码。"""
    return frozenset(_APPROVAL_RE.findall(text or ""))


class ConfirmingExecutor:
    """装饰 ToolExecutor:销毁性操作拦截层(套在 sandbox 执行器外,最靠近真实执行的位置,
    其它 worker 原生工具不经过它)。approvals = 本回合用户消息里带的批准码集合。"""

    def __init__(self, inner: ToolExecutor, *, approvals: frozenset[str] = frozenset()) -> None:
        self._inner = inner
        self._approvals = approvals

    def specs(self):
        return self._inner.specs()

    async def execute(self, call: ToolCall) -> ToolResult:
        reason = assess_danger(call)
        if reason is None:
            return await self._inner.execute(call)
        fp = fingerprint(call)
        if fp in self._approvals:
            return await self._inner.execute(call)  # 用户已确认这枚指纹:放行本回合
        return ToolResult(
            call_id=call.id,
            content=(
                f"⚠️ 已拦截可能有破坏性的操作:{reason}(批准码 {fp})。"
                "该命令未执行。请向用户简要说明这个命令会做什么、影响哪些文件,"
                "然后等待用户确认;用户发送包含上述批准码的确认消息后,"
                "重试完全相同的命令即可执行。不要擅自改用其它方式绕过这次确认。"
            ),
            is_error=True,
        )
