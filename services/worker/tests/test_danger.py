"""危险操作确认(轻量权限)测试:规则 / 指纹 / 单次放行 / E2E wiring。"""

from agent_cloud_common import ToolCall, ToolResult
from agent_cloud_worker.danger import (
    ConfirmingExecutor,
    assess_danger,
    extract_approvals,
    fingerprint,
)


def _bash(cmd):
    return ToolCall(id="1", name="bash", arguments={"command": cmd})


def test_assess_danger_hits_destructive_patterns():
    dangerous = [
        "rm -rf build",
        "rm -fr /workspace/data",
        "rm -r old_dir",
        "rm -f *.log",
        "git reset --hard HEAD~1",
        "git clean -fd",
        "git checkout .",
        "find . -name '*.tmp' -delete",
        "ls | xargs rm",
        "truncate -s 0 app.log",
        "cd /tmp && rm -rf cache",  # 组合命令中的片段也要抓
        "rm -f -r build",  # 旗标乱序(审查 M1)
        "rm -f -R build",
        "rm --recursive old/",  # 长旗标
    ]
    for cmd in dangerous:
        assert assess_danger(_bash(cmd)) is not None, cmd


def test_assess_danger_ignores_normal_commands():
    safe = [
        "ls -la",
        "rm notes.txt",  # 单文件 rm 不拦(误报会让人烦到关掉这个功能)
        "grep -r 'rm -rf' docs/",  # 引号里的文本会误中?——会拦(保守可接受,批准即过)
        "python3 script.py",
        "git status",
        "git checkout main",  # 切分支不拦(不是 checkout .)
        "mkdir -p a/b && touch a/b/c.txt",
        "cat file | head -5",
    ]
    for cmd in [
        "ls -la",
        "rm notes.txt",
        "rm -f single.log",  # -f 无 -r:不拦
        "python3 script.py",
        "git status",
        "git checkout main",
        "git checkout .config",  # 点开头文件名不是 checkout .(误报回归,审查建议钉死)
        "git checkout .gitignore",
    ]:
        assert assess_danger(_bash(cmd)) is None, cmd
    # 非 bash 工具一律不拦
    assert assess_danger(ToolCall(id="1", name="write_file", arguments={"path": "x"})) is None


def test_fingerprint_stable_and_sensitive():
    a = fingerprint(_bash("rm -rf build"))
    assert a == fingerprint(_bash("rm -rf build"))  # 同命令稳定
    assert a != fingerprint(_bash("rm -rf build2"))  # 参数变即变
    assert len(a) == 16


def test_extract_approvals():
    fp = fingerprint(_bash("rm -rf build"))
    assert extract_approvals(f"允许执行该操作(批准码 {fp})") == frozenset({fp})
    assert extract_approvals("好的,继续") == frozenset()
    assert extract_approvals("") == frozenset()


class _Inner:
    def __init__(self):
        self.executed = []

    def specs(self):
        return []

    async def execute(self, call):
        self.executed.append(call.arguments.get("command"))
        return ToolResult(call_id=call.id, content="ran", is_error=False)


async def test_blocks_without_approval_and_passes_with():
    inner = _Inner()
    cmd = "rm -rf build"
    fp = fingerprint(_bash(cmd))
    # 无批准:拦截,不执行,结果带批准码引导
    ex = ConfirmingExecutor(inner)
    r = await ex.execute(_bash(cmd))
    assert r.is_error and fp in r.content and "拦截" in r.content
    assert inner.executed == []
    # 带批准:放行执行
    ex2 = ConfirmingExecutor(inner, approvals=frozenset({fp}))
    r2 = await ex2.execute(_bash(cmd))
    assert not r2.is_error and inner.executed == [cmd]
    # 批准了 A,改跑 B(参数变了)→ 仍拦
    r3 = await ex2.execute(_bash("rm -rf /other"))
    assert r3.is_error and inner.executed == [cmd]


async def test_safe_commands_pass_through_untouched():
    inner = _Inner()
    ex = ConfirmingExecutor(inner)
    r = await ex.execute(_bash("ls -la"))
    assert not r.is_error and inner.executed == ["ls -la"]
