"""可靠的多段 str-replace 编辑(从 OpenClaw edit-diff 移植要点)。

`apply_edits` 是纯函数:对每段 `{old_text, new_text}` 在【当前内容】里定位 old_text,
依次尝试 精确 → Unicode 归一(引号/破折号)→ 逐行尾空白容错;命中必须**唯一**,否则报
可操作的错误(让模型补上下文)。全部成功才返回新内容(原子;任一失败抛 ValueError,
调用方据此不写盘)。比 write_file 整文件覆盖更安全:不会丢掉文件其余部分。
"""

from __future__ import annotations

import json

# Unicode 归一映射:1:1 替换(不改变长度→匹配到的索引可直接用于原文),把模型常"美化"
# 的字符还原成 ASCII,用于精确未命中时的模糊匹配。
_CANON = {
    "‘": "'",
    "’": "'",
    "‛": "'",  # 单引号变体
    "“": '"',
    "”": '"',
    "‟": '"',  # 双引号变体
    "–": "-",
    "—": "-",
    "−": "-",  # en/em dash、减号
    " ": " ",  # 不换行空格
}


def _canon(s: str) -> str:
    return "".join(_CANON.get(ch, ch) for ch in s)


def _detect_newline(s: str) -> str:
    """文件主流换行风格:存在 \\r\\n 且不少于裸 \\n 则视为 CRLF,否则 LF。"""
    crlf = s.count("\r\n")
    lf = s.count("\n") - crlf
    return "\r\n" if crlf and crlf >= lf else "\n"


def _restore_newline(s: str, nl: str) -> str:
    return s.replace("\n", nl) if nl == "\r\n" else s


def _locate_line_trim(content: str, old: str, label: str) -> tuple[int, int] | None:
    """逐行尾空白不敏感匹配:把 old 当作整行序列,在 content 的行窗口里找(每行 rstrip 后比较)。
    覆盖"模型丢了/加了行尾空白"的常见情况。命中多处抛 ValueError;唯一→返回原文字符 span;无→None。"""
    c_lines = content.split("\n")
    o_lines = old.split("\n")
    if len(o_lines) > 1 and o_lines[-1] == "":
        o_lines = o_lines[:-1]  # old 末尾换行 = "匹配这些整行",不再额外要求一个空行
    k = len(o_lines)
    if k == 0 or k > len(c_lines):
        return None
    # 每行在 content 中的起始偏移
    offsets: list[int] = []
    pos = 0
    for ln in c_lines:
        offsets.append(pos)
        pos += len(ln) + 1  # +1 = 行后的 "\n"
    o_norm = [ln.rstrip() for ln in o_lines]
    matches: list[tuple[int, int]] = []
    for i in range(len(c_lines) - k + 1):
        if [c_lines[j].rstrip() for j in range(i, i + k)] == o_norm:
            last = i + k - 1
            matches.append((offsets[i], offsets[last] + len(c_lines[last])))
    if len(matches) > 1:
        raise ValueError(
            f"{label}: old_text matched {len(matches)} places "
            "(trailing-whitespace–insensitive); add more surrounding context to make it unique"
        )
    return matches[0] if matches else None


def _locate(content: str, old: str, idx: int) -> tuple[int, int]:
    """在 content 里定位 old 的唯一替换区间 [start, end);定位失败/不唯一抛 ValueError。"""
    label = f"edit #{idx + 1}"
    # 1) 精确
    n = content.count(old)
    if n == 1:
        s = content.index(old)
        return s, s + len(old)
    if n > 1:
        raise ValueError(
            f"{label}: old_text matched {n} places; add more surrounding context to make it unique"
        )
    # 2) Unicode 归一(1:1,保索引)
    cc, co = _canon(content), _canon(old)
    n = cc.count(co)
    if n == 1:
        s = cc.index(co)
        return s, s + len(old)  # len(co) == len(old)
    if n > 1:
        raise ValueError(
            f"{label}: old_text matched {n} places (after normalizing quotes/dashes); "
            "add more surrounding context to make it unique"
        )
    # 3) 逐行尾空白容错
    span = _locate_line_trim(content, old, label)
    if span is not None:
        return span
    raise ValueError(
        f"{label}: old_text not found in file "
        "(also tried quote/dash and trailing-whitespace–insensitive matching)"
    )


def apply_edits(original: str, edits: object) -> str:
    """顺序应用多段 str-replace,全部成功才返回新内容(原子)。任一段失败抛 ValueError。

    edits 可为 list[{old_text,new_text}],也兼容被模型整体发成 JSON 字符串的情况。
    """
    if isinstance(edits, str):  # 有的模型把数组整体发成 JSON 字符串
        try:
            edits = json.loads(edits)
        except json.JSONDecodeError as exc:
            raise ValueError(f"edits is not valid JSON: {exc}") from exc
    if not isinstance(edits, list) or not edits:
        raise ValueError("edits must be a non-empty array of {old_text, new_text}")

    # 全程在 LF 空间匹配/编辑,最后按文件主流换行风格还原。否则 line-trim 阶段(按行 rstrip
    # 比较)会把编辑区内的 \r 吃掉,静默把 CRLF 文件改成混合/LF 换行。注意:这会把【整文件】
    # 规整为主流换行(混合换行的文件会被统一)—— 对编辑工具是可接受甚至期望的行为。
    nl = _detect_newline(original)
    content = original.replace("\r\n", "\n")
    for idx, e in enumerate(edits):
        if not isinstance(e, dict) or "old_text" not in e or "new_text" not in e:
            raise ValueError(f"edit #{idx + 1}: each edit needs old_text and new_text")
        old, new = e["old_text"], e["new_text"]
        if not isinstance(old, str) or not isinstance(new, str):
            raise ValueError(f"edit #{idx + 1}: old_text and new_text must be strings")
        old = old.replace("\r\n", "\n")  # 在 LF 空间匹配:模型常把 CRLF 文件的片段按 LF 发来
        new = new.replace("\r\n", "\n")
        if old == "":
            raise ValueError(f"edit #{idx + 1}: old_text must not be empty")
        if old == new:
            raise ValueError(f"edit #{idx + 1}: old_text and new_text are identical (no-op)")
        start, end = _locate(content, old, idx)
        content = content[:start] + new + content[end:]
    return _restore_newline(content, nl)
