import json

import pytest
from agent_cloud_common.edit import apply_edits


def test_exact_unique_replace():
    assert apply_edits("a foo b", [{"old_text": "foo", "new_text": "bar"}]) == "a bar b"


def test_not_unique_is_actionable_error():
    with pytest.raises(ValueError, match="matched 2 places"):
        apply_edits("foo foo", [{"old_text": "foo", "new_text": "x"}])


def test_not_found_error():
    with pytest.raises(ValueError, match="not found"):
        apply_edits("hello", [{"old_text": "nope", "new_text": "x"}])


def test_multi_edit_sequential():
    out = apply_edits(
        "alpha beta",
        [{"old_text": "alpha", "new_text": "A"}, {"old_text": "beta", "new_text": "B"}],
    )
    assert out == "A B"


def test_atomic_second_edit_failure_raises_without_partial():
    # 第二段找不到 → 整体抛错;调用方据此不写盘(原子)。
    with pytest.raises(ValueError, match="edit #2"):
        apply_edits(
            "x = 1",
            [{"old_text": "x = 1", "new_text": "x = 2"}, {"old_text": "zzz", "new_text": "q"}],
        )


def test_unicode_quote_normalization_match():
    # 文件里是直引号,模型发来弯引号 → 归一后唯一命中。
    content = "msg = 'hi'\n"
    out = apply_edits(content, [{"old_text": "msg = ‘hi’", "new_text": "msg = 'bye'"}])
    assert out == "msg = 'bye'\n"


def test_trailing_whitespace_insensitive_match():
    # 第一行尾有多余空格,使精确匹配失败(差异在 old 中段,非后缀)→ 逐行尾空白容错命中。
    content = "x = 1   \ny = 2\n"
    out = apply_edits(content, [{"old_text": "x = 1\ny = 2", "new_text": "x = 100\ny = 200"}])
    assert out == "x = 100\ny = 200\n"


def test_indentation_is_respected_not_stripped():
    # 仅尾空白容错;前导缩进必须严格匹配(不能误命中不同缩进的行)。
    content = "    x\nx\n"
    out = apply_edits(content, [{"old_text": "    x", "new_text": "    y"}])
    assert out == "    y\nx\n"


def test_edits_as_json_string_is_parsed():
    edits = json.dumps([{"old_text": "foo", "new_text": "bar"}])
    assert apply_edits("foo", edits) == "bar"


def test_identical_old_new_is_rejected():
    with pytest.raises(ValueError, match="identical"):
        apply_edits("foo", [{"old_text": "foo", "new_text": "foo"}])


def test_empty_old_text_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        apply_edits("foo", [{"old_text": "", "new_text": "x"}])


def test_empty_edits_rejected():
    with pytest.raises(ValueError, match="non-empty array"):
        apply_edits("foo", [])


def test_malformed_edit_shape_rejected():
    with pytest.raises(ValueError, match="needs old_text and new_text"):
        apply_edits("foo", [{"old_text": "foo"}])
